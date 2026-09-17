"""LLM provider factory and SDK adapters.

Application services depend on :mod:`app.services.llm_port` and never receive
an OpenAI or Azure SDK client directly. Provider-specific authentication,
request mapping, response normalization, and optional Langfuse integration
stay in this module.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Mapping
from uuid import uuid4

from openai import AsyncAzureOpenAI, AsyncOpenAI

from app.services.llm_port import LLMPort, LLMRequest, LLMResponse, LLMUsage
from app.utils.config import Settings, get_settings


logger = logging.getLogger(__name__)
_langfuse_setup_attempted = False


def _mask_otel_spans(*, params: Any) -> Any:
    """Remove prompt/completion attributes before Langfuse export.

    The type imports stay inside this function so the application remains
    importable when the optional Langfuse package is not installed.
    """
    from langfuse.types import MaskOtelSpansResult, OtelSpanPatch

    patches: dict[Any, Any] = {}
    for identifier, span in params.spans.items():
        delete_attributes = tuple(
            attribute
            for attribute in span.attributes
            if attribute.startswith(("gen_ai.prompt", "gen_ai.completion"))
        )
        if delete_attributes:
            patches[identifier] = OtelSpanPatch(
                delete_attributes=delete_attributes,
                set_attributes={"diagrammatic.masking_applied": True},
            )
    return MaskOtelSpansResult(span_patches=patches) if patches else None


def is_langfuse_configured(settings: Settings) -> bool:
    """Return whether Langfuse has the minimum configuration to emit traces."""
    return bool(
        settings.langfuse_enabled
        and settings.langfuse_public_key
        and settings.langfuse_secret_key
    )


def _configure_langfuse_environment(settings: Settings) -> None:
    """Expose validated settings to the lazily imported Langfuse SDK."""
    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key or ""
    os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key or ""
    os.environ["LANGFUSE_BASE_URL"] = settings.langfuse_base_url
    os.environ["LANGFUSE_TRACING_ENABLED"] = "true"
    os.environ["LANGFUSE_SAMPLE_RATE"] = str(settings.langfuse_sample_rate)
    os.environ["LANGFUSE_TRACING_ENVIRONMENT"] = settings.langfuse_environment
    if settings.langfuse_release:
        os.environ["LANGFUSE_TRACING_RELEASE"] = settings.langfuse_release


def _provider_name(settings: Settings) -> str:
    """Return the normalized provider identifier from configuration."""

    return settings.llm_provider.strip().lower()


def _is_reasoning_model(model: str) -> bool:
    """Return whether a model/deployment uses reasoning-model parameters."""

    return model.lower().startswith(("gpt-5", "o1", "o3", "o4"))


def _langfuse_client_class(provider: str) -> Any:
    """Resolve the optional Langfuse OpenAI-compatible wrapper class."""

    from langfuse import openai as langfuse_openai

    class_name = "AsyncAzureOpenAI" if provider == "azure_openai" else "AsyncOpenAI"
    return getattr(langfuse_openai, class_name)


def _new_langfuse_trace_id() -> str | None:
    """Create a trace ID that can be returned to the browser for feedback."""
    try:
        from langfuse import Langfuse

        return Langfuse.create_trace_id()
    except Exception:
        logger.exception("Could not create a Langfuse trace ID")
        return None


def _build_sdk_client(settings: Settings) -> tuple[Any, bool]:
    """Build the selected SDK client, including optional tracing."""

    provider = _provider_name(settings)
    if provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is required when LLM_PROVIDER=openai"
            )
        client_kwargs: dict[str, Any] = {"api_key": settings.openai_api_key}
    elif provider == "azure_openai":
        missing = [
            name
            for name, value in (
                ("AZURE_OPENAI_API_KEY", settings.azure_openai_api_key),
                ("AZURE_OPENAI_ENDPOINT", settings.azure_openai_endpoint),
                ("AZURE_OPENAI_DEPLOYMENT", settings.azure_openai_deployment),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Azure OpenAI configuration is incomplete; missing "
                + ", ".join(missing)
            )
        client_kwargs = {
            "api_key": settings.azure_openai_api_key,
            "azure_endpoint": settings.azure_openai_endpoint,
            "api_version": settings.azure_openai_api_version,
        }
    else:
        raise ValueError(
            f"Unsupported LLM_PROVIDER={settings.llm_provider!r}; "
            "supported values are openai and azure_openai"
        )

    if not is_langfuse_configured(settings):
        if provider == "azure_openai":
            return AsyncAzureOpenAI(**client_kwargs), False
        return AsyncOpenAI(**client_kwargs), False

    global _langfuse_setup_attempted
    _configure_langfuse_environment(settings)

    try:
        # Import only after environment variables have been loaded. This keeps
        # Langfuse optional and lets the SDK read Cloud or self-hosted settings.
        if not _langfuse_setup_attempted:
            from langfuse import Langfuse

            langfuse_options: dict[str, Any] = {
                "sample_rate": settings.langfuse_sample_rate,
            }
            if not settings.langfuse_capture_content:
                langfuse_options["mask_otel_spans"] = _mask_otel_spans
            Langfuse(**langfuse_options)

            logger.info(
                "Langfuse tracing enabled environment=%s sample_rate=%s capture_content=%s",
                settings.langfuse_environment,
                settings.langfuse_sample_rate,
                settings.langfuse_capture_content,
            )
            _langfuse_setup_attempted = True

        langfuse_class = _langfuse_client_class(provider)
        return langfuse_class(**client_kwargs), True
    except ImportError:
        logger.warning(
            "Langfuse is configured but the optional package or provider wrapper "
            "is unavailable; continuing without telemetry"
        )
        if provider == "azure_openai":
            return AsyncAzureOpenAI(**client_kwargs), False
        return AsyncOpenAI(**client_kwargs), False
    except Exception:
        # Observability must not take down an assessment request because of a
        # client initialization/configuration issue.
        logger.exception(
            "Langfuse client initialization failed; continuing without telemetry"
        )
        if provider == "azure_openai":
            return AsyncAzureOpenAI(**client_kwargs), False
        return AsyncOpenAI(**client_kwargs), False


class OpenAICompatibleAdapter:
    """Adapter for OpenAI and Azure OpenAI chat-completions clients."""

    def __init__(
        self, client: Any, settings: Settings, *, tracing_enabled: bool = False
    ) -> None:
        self._client = client
        self._settings = settings
        self._tracing_enabled = tracing_enabled
        self._provider = _provider_name(settings)
        self._model = (
            settings.azure_openai_deployment
            if self._provider == "azure_openai"
            else settings.llm_model
        )
        self._supports_reasoning = (
            settings.llm_supports_reasoning
            if settings.llm_supports_reasoning is not None
            else _is_reasoning_model(self._model or "")
        )
        if not self._model:
            raise RuntimeError("An LLM model or Azure deployment must be configured")

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Map a normalized request to the selected compatible SDK."""

        completion_options: dict[str, Any] = {
            "model": self._model,
            "messages": [dict(message) for message in request.messages],
            "max_completion_tokens": request.max_tokens,
        }
        if request.response_format is not None:
            completion_options["response_format"] = dict(request.response_format)

        if self._supports_reasoning:
            if request.reasoning_effort is not None:
                completion_options["reasoning_effort"] = request.reasoning_effort
        elif request.temperature is not None:
            completion_options["temperature"] = request.temperature

        trace_id: str | None = None
        if self._tracing_enabled:
            trace_id = _new_langfuse_trace_id()
            completion_options.update(
                langfuse_options(
                    self._settings,
                    name=request.task,
                    tags=request.tags,
                    metadata=request.metadata,
                    trace_id=trace_id,
                )
            )
        response = await self._client.chat.completions.create(**completion_options)

        choice = response.choices[0] if response.choices else None
        message = choice.message if choice is not None else None
        usage = response.usage
        usage_details = getattr(usage, "completion_tokens_details", None)
        return LLMResponse(
            content=getattr(message, "content", None),
            model=getattr(response, "model", self._model),
            trace_id=trace_id,
            finish_reason=getattr(choice, "finish_reason", None),
            refusal=getattr(message, "refusal", None),
            usage=LLMUsage(
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                reasoning_tokens=getattr(usage_details, "reasoning_tokens", None),
            ),
            raw=response,
        )


def create_llm_provider(settings: Settings | None = None) -> LLMPort:
    """Create the configured provider adapter for application services."""

    resolved_settings = settings or get_settings()
    client, tracing_enabled = _build_sdk_client(resolved_settings)
    return OpenAICompatibleAdapter(
        client, resolved_settings, tracing_enabled=tracing_enabled
    )


# Backwards-compatible name for callers that used the old factory. It now
# returns the provider-neutral port rather than an SDK-specific client.
create_llm_client = create_llm_provider


def langfuse_options(
    settings: Settings,
    *,
    name: str,
    tags: tuple[str, ...] = (),
    metadata: Mapping[str, Any] | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Build Langfuse-only request attributes when tracing is enabled.

    The returned dictionary is empty for the native OpenAI client, avoiding
    unsupported provider arguments when telemetry is disabled.
    """
    if not is_langfuse_configured(settings):
        return {}

    trace_metadata: dict[str, Any] = {
        "langfuse_tags": ["diagrammatic", *tags],
        "feature": name,
    }
    if metadata:
        trace_metadata.update(metadata)
    session_id = trace_metadata.get("langfuse_session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        session_id = f"llm-{uuid4()}"
    # Langfuse's OpenAI integration reads this special metadata field when
    # assigning the generation to a session. Keep it non-empty even when the
    # caller does not provide an application-level conversation id.
    trace_metadata["langfuse_session_id"] = session_id
    options: dict[str, Any] = {"name": name, "metadata": trace_metadata}
    if trace_id:
        options["trace_id"] = trace_id
    return options


def record_langfuse_feedback(
    *,
    trace_id: str | None,
    helpful: bool | None,
    rating: int | None,
    source: str,
    category: str,
    reasons: list[str],
    feedback_id: str | None = None,
    settings: Settings | None = None,
) -> None:
    """Attach user feedback scores to an existing Langfuse trace.

    Feedback remains durable in DynamoDB; Langfuse receives only the
    structured signal and whitelisted context, not the free-text message.
    Observability failures must never make feedback submission fail.
    """
    resolved_settings = settings or get_settings()
    if not trace_id or not is_langfuse_configured(resolved_settings):
        return

    try:
        _configure_langfuse_environment(resolved_settings)
        from langfuse import get_client

        client = get_client()
        metadata = {
            "source": source,
            "category": category,
            "reasons": reasons,
            **({"feedback_id": feedback_id} if feedback_id else {}),
        }
        if helpful is not None:
            client.create_score(
                name="user-helpfulness",
                value=1 if helpful else 0,
                trace_id=trace_id,
                data_type="BOOLEAN",
                metadata=metadata,
            )
        if rating is not None:
            client.create_score(
                name="user-rating",
                value=float(rating),
                trace_id=trace_id,
                data_type="NUMERIC",
                metadata=metadata,
            )
        client.flush()
    except Exception:
        logger.exception(
            "Could not record Langfuse user feedback trace_id=%s", trace_id
        )


def flush_langfuse(settings: Settings | None = None) -> None:
    """Flush queued traces during graceful application shutdown."""
    resolved_settings = settings or get_settings()
    if not is_langfuse_configured(resolved_settings) or not _langfuse_setup_attempted:
        return

    try:
        from langfuse import get_client

        get_client().flush()
    except Exception:
        logger.exception("Langfuse flush failed during application shutdown")
