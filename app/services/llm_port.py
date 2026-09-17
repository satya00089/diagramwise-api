"""Provider-neutral contracts for Diagrammatic's language-model features."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence


LLMMessage = Mapping[str, Any]


@dataclass(frozen=True)
class LLMRequest:
    """Normalized request understood by every provider adapter."""

    task: str
    messages: Sequence[LLMMessage]
    max_tokens: int
    response_format: Mapping[str, Any] | None = None
    temperature: float | None = None
    reasoning_effort: str | None = None
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMUsage:
    """Provider-neutral usage information."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None


@dataclass(frozen=True)
class LLMResponse:
    """Normalized response returned to application services."""

    content: str | None
    model: str | None = None
    trace_id: str | None = None
    finish_reason: str | None = None
    refusal: str | None = None
    usage: LLMUsage = field(default_factory=LLMUsage)
    raw: Any = None

    @property
    def refusal_present(self) -> bool:
        """Whether the provider refused to return the requested content."""

        return bool(self.refusal)


class LLMPort(Protocol):
    """Application-facing port for structured language-model generation."""

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate one normalized response for an application task."""


class MockLLMAdapter:
    """Deterministic adapter for service tests and local development."""

    def __init__(self, content: str = "{}", trace_id: str | None = None) -> None:
        self.content = content
        self.trace_id = trace_id
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(
            content=self.content,
            model="mock",
            trace_id=self.trace_id,
            finish_reason="stop",
        )
