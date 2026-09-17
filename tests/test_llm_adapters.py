from types import SimpleNamespace

import pytest

from app.models.recommendation_models import CanvasContextInfo, RecommendationRequest
from app.models.request_models import (
    AssessmentRequest,
    InterviewQuestionsRequest,
    SystemComponent,
    ComponentType,
)
from app.services.ai_assessor import AIAssessorService
from app.services.ai_recommendation_service import AIRecommendationService
from app.services.llm_client import OpenAICompatibleAdapter, _build_sdk_client
from app.services.llm_port import LLMRequest, MockLLMAdapter
from app.utils.config import Settings


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "llm_provider": "openai",
        "llm_model": "gpt-4o-mini",
        "llm_max_tokens": 2000,
        "llm_assessment_max_tokens": 6000,
        "llm_assessment_reasoning_effort": "low",
        "llm_temperature": 0.3,
        "openai_api_key": "test-openai-key",
        "langfuse_enabled": False,
        "langfuse_public_key": None,
        "langfuse_secret_key": None,
    }
    values.update(overrides)
    return Settings.model_construct(**values)


class FakeCompletions:
    def __init__(self) -> None:
        self.options: dict[str, object] | None = None

    async def create(self, **options: object) -> SimpleNamespace:
        self.options = options
        return SimpleNamespace(
            model="gpt-4o-mini",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"ok": true}', refusal=None),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                completion_tokens_details=SimpleNamespace(reasoning_tokens=None),
            ),
        )


class FakeClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions())


@pytest.mark.asyncio
async def test_openai_compatible_adapter_normalizes_response() -> None:
    client = FakeClient()
    adapter = OpenAICompatibleAdapter(client, make_settings())

    response = await adapter.generate(
        LLMRequest(
            task="test.generate",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=100,
            response_format={"type": "json_object"},
            temperature=0.2,
        )
    )

    assert response.content == '{"ok": true}'
    assert response.model == "gpt-4o-mini"
    assert response.usage.prompt_tokens == 10
    assert client.chat.completions.options == {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "hello"}],
        "max_completion_tokens": 100,
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }


@pytest.mark.asyncio
async def test_reasoning_model_uses_reasoning_effort_instead_of_temperature() -> None:
    client = FakeClient()
    adapter = OpenAICompatibleAdapter(
        client,
        make_settings(llm_model="o3-mini"),
    )

    await adapter.generate(
        LLMRequest(
            task="test.reasoning",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=100,
            temperature=0.2,
            reasoning_effort="low",
        )
    )

    assert client.chat.completions.options is not None
    assert "temperature" not in client.chat.completions.options
    assert client.chat.completions.options["reasoning_effort"] == "low"


@pytest.mark.asyncio
async def test_mock_adapter_records_provider_neutral_request() -> None:
    adapter = MockLLMAdapter(content='{"recommendations": []}')
    request = LLMRequest(
        task="recommendations.generate",
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=100,
    )

    response = await adapter.generate(request)

    assert response.content == '{"recommendations": []}'
    assert adapter.requests == [request]


@pytest.mark.asyncio
async def test_recommendation_service_uses_injected_llm_port() -> None:
    adapter = MockLLMAdapter(
        content='{"recommendations": [], "context_summary": "mocked"}'
    )
    service = AIRecommendationService(llm=adapter)
    request = RecommendationRequest(
        canvas_context=CanvasContextInfo(
            node_count=0,
            edge_count=0,
            component_types=[],
            is_empty=True,
        )
    )

    response = await service.get_recommendations(request)

    assert response.context_summary == "mocked"
    assert adapter.requests[0].task == "recommendations.generate"


@pytest.mark.asyncio
async def test_assessor_interview_uses_injected_llm_port() -> None:
    adapter = MockLLMAdapter(content='{"questions": ["How does this scale?"]}')
    service = AIAssessorService(llm=adapter)
    request = InterviewQuestionsRequest(
        architecture=AssessmentRequest(
            components=[
                SystemComponent(
                    id="api",
                    type=ComponentType.BACKEND,
                    label="API",
                )
            ]
        )
    )

    response = await service.generate_interview_questions(request)

    assert response.questions == ["How does this scale?"]
    assert adapter.requests[0].task == "interview.generate-questions"


@pytest.mark.asyncio
async def test_assessor_exposes_llm_trace_id_on_assessment_response() -> None:
    adapter = MockLLMAdapter(
        content=(
            '{"scores":{"scalability":80,"reliability":70,'
            '"security":60,"maintainability":90},"feedback":[],'
            '"findings":[],"strengths":[],"improvements":[],'
            '"missing_components":[],"suggestions":[]}'
        ),
        trace_id="0123456789abcdef0123456789abcdef",
    )
    service = AIAssessorService(llm=adapter)
    request = AssessmentRequest(
        components=[
            SystemComponent(
                id="api",
                type=ComponentType.BACKEND,
                label="API",
            )
        ]
    )

    response = await service.assess_design(request)

    assert response.trace_id == "0123456789abcdef0123456789abcdef"


def test_azure_factory_builds_azure_client_and_uses_deployment_name() -> None:
    settings = make_settings(
        llm_provider="azure_openai",
        azure_openai_api_key="test-azure-key",
        azure_openai_endpoint="https://diagrammatic.openai.azure.com/",
        azure_openai_api_version="2024-10-21",
        azure_openai_deployment="diagrammatic-gpt-4o",
        llm_supports_reasoning=False,
    )

    client, tracing_enabled = _build_sdk_client(settings)
    adapter = OpenAICompatibleAdapter(client, settings)

    assert client.__class__.__name__ == "AsyncAzureOpenAI"
    assert tracing_enabled is False
    assert adapter._model == "diagrammatic-gpt-4o"


def test_azure_factory_reports_missing_configuration() -> None:
    settings = make_settings(llm_provider="azure_openai")

    with pytest.raises(RuntimeError, match="AZURE_OPENAI_API_KEY"):
        _build_sdk_client(settings)
