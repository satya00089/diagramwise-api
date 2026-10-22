"""Offline contract tests for approved scope, grounded output and honest failure."""

import asyncio
from copy import deepcopy
import json
import sys
import threading
from types import ModuleType
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from app.models.problem_models import ProblemModel, RequirementSpec
from app.models.request_models import AssessmentRequest, ProblemContext
from app.routers import assessment as assessment_router
from app.services.ai_assessor import AIAssessorService
from app.services.llm_port import LLMResponse
from app.utils.config import Settings
from app.utils.prompts import get_assessment_prompt, get_assessment_requirement_refs


def specification():
    return {
        "revision": "approved-r3",
        "functional": [{"id": "create", "text": "Store submitted documents", "scope": "core"}],
        "nonFunctional": [{"id": "durability", "text": "Preserve committed documents", "scope": "core", "category": "durability"}],
        "assumptions": ["One region is the reference scenario"],
    }


def architecture():
    return AssessmentRequest.model_validate({
        "components": [
            {"id": "api", "type": "backend", "label": "Document API", "properties": {"purpose": "Validate permissions and store documents", "selected": True}},
            {"id": "store", "type": "storage", "label": "Document Store", "properties": {"purpose": "Replicated storage preserves committed documents"}},
        ],
        "connections": [{"id": "write", "source": "api", "target": "store", "label": "Commit document", "type": "HTTPS", "description": "Acknowledge after a durable write"}],
        "problem": {"id": "catalog-doc", "title": "Documents", "description": "Store documents", "requirementSpec": specification()},
        "explanation": "The API acknowledges the replicated write.",
        "keyPoints": ["Retry with an operation identifier"],
        "interviewSession": {"exchanges": [
            {"id": "answered", "question": "When is a write complete?", "answer": "After replication", "createdAt": "2026-10-10"},
            {"id": "skipped", "question": "What is optional?", "skipped": True, "createdAt": "2026-10-10"},
        ]},
    })


def review(score=98):
    return {
        "scores": {dimension: score for dimension in AIAssessorService._SCORE_WEIGHTS},
        "verdict": "strong_alignment",
        "summary": "The submitted path supports document creation and durable commits.",
        "findings": [{"title": "Durable commit path", "explanation": "Writes are acknowledged after replication.", "severity": "positive", "kind": "strength", "evidence_ids": ["write", "interview:answered"], "requirement_ids": ["durability"], "criterion": None}],
        "requirement_coverage": [
            {"requirement_id": "create", "status": "supported", "explanation": "API stores documents", "evidence_ids": ["api", "write"]},
            {"requirement_id": "durability", "status": "supported", "explanation": "Replicated commits", "evidence_ids": ["store", "interview:answered"]},
        ],
        "feedback": [], "strengths": [], "improvements": [], "missing_components": [], "suggestions": [],
    }


class SequenceLLM:
    def __init__(self, *outputs, delay=0):
        self.outputs = outputs
        self.delay = delay
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        output = self.outputs[min(len(self.requests) - 1, len(self.outputs) - 1)]
        if isinstance(output, Exception):
            raise output
        return LLMResponse(content=json.dumps(output) if isinstance(output, dict) else output, trace_id="0123456789abcdef0123456789abcdef", finish_reason="stop")


def service(adapter, **kwargs):
    settings = Settings.model_construct(llm_model="test-model", llm_provider="openai", langfuse_enabled=False)
    return AIAssessorService(llm=adapter, settings=settings, **kwargs)


@pytest.fixture(autouse=True)
def reference_calls(monkeypatch):
    """Isolate the sibling semantic-check implementation from this contract suite."""
    calls = []
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")

    def unexpected_provider(_):
        pytest.fail("Offline tests must inject their LLM provider")

    monkeypatch.setattr("app.services.ai_assessor.create_llm_provider", unexpected_provider)

    async def checks(request):
        calls.append(request)
        return [{"title": "Required storage relationship", "status": "supported", "explanation": "The submitted API connects to document storage."}]

    module = ModuleType("app.services.walkthrough_reference")
    module.get_fallback_reference_checks = checks
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return calls


def test_additive_requirement_model_preserves_legacy_fields():
    problem = ProblemModel.model_validate({"id": "p", "title": "P", "description": "D", "difficulty": "medium", "category": "design", "estimated_time": "45 minutes", "requirements": ["Legacy mixed requirement"], "constraints": ["Legacy constraint"], "requirementSpec": specification()})
    context = ProblemContext(title="P", description="D", requirementSpec=problem.requirementSpec)
    assert context.requirementSpec == problem.requirementSpec
    assert problem.requirementSpec.schemaVersion == 1
    assert problem.requirements == ["Legacy mixed requirement"]
    assert ProblemContext(title="Custom", description="D").requirementSpec is None


def test_legacy_full_coverage_is_grounded_without_inventing_a_spec():
    request = architecture().model_copy(update={"problem": ProblemContext(
        title="Documents", description="Store documents", requirements="Store submitted documents",
        constraints="Preserve committed documents")})
    output = review()
    output["findings"][0]["requirement_ids"] = ["legacy-constraint:1"]
    output["requirement_coverage"][0]["requirement_id"] = "legacy-requirement:1"
    output["requirement_coverage"][1]["requirement_id"] = "legacy-constraint:1"
    result = service(SequenceLLM(output))._transform_ai_response(output, request)
    assert result.score_available is True
    assert result.requirement_revision is None
    assert len(result.requirement_coverage) == 2
    assert request.problem.requirementSpec is None


def test_oversized_assessment_is_rejected_without_truncating_evidence():
    data = architecture().model_dump()
    data["explanation"] = "x" * (512 * 1024)
    with pytest.raises(ValidationError, match="512 KiB"):
        AssessmentRequest.model_validate(data)


def test_legacy_coverage_still_rejects_unknown_or_partial_anchor_sets():
    request = architecture().model_copy(update={"problem": ProblemContext(
        title="Documents", description="Store documents", requirements="Store submitted documents",
        constraints="Preserve committed documents")})
    output = review()
    output["findings"][0]["requirement_ids"] = ["legacy-constraint:1"]
    output["requirement_coverage"] = [{"requirement_id": "legacy-requirement:1", "status": "supported",
                                       "explanation": "Document API stores", "evidence_ids": ["api"]}]
    assessor = service(SequenceLLM(output))
    with pytest.raises(ValueError, match="every supplied requirement"):
        assessor._transform_ai_response(output, request)


@pytest.mark.parametrize("fault", ["duplicate", "scope", "schema", "revision", "empty_text"])
def test_invalid_specifications_rejected(fault):
    spec = specification()
    if fault == "duplicate":
        spec["nonFunctional"][0]["id"] = "create"
    elif fault == "scope":
        spec["functional"][0]["scope"] = "mandatory"
    elif fault == "schema":
        spec["schemaVersion"] = 2
    elif fault == "revision":
        spec["revision"] = " "
    else:
        spec["functional"][0]["text"] = " "
    with pytest.raises(ValidationError):
        RequirementSpec.model_validate(spec)


def test_prompt_has_readable_grounding_and_distinct_assumptions():
    prompt = get_assessment_prompt(architecture())
    assert 'ID: api;' in prompt
    assert 'api (Document API)' in prompt
    assert 'store (Document Store)' in prompt
    assert 'ID: write;' in prompt
    assert 'HTTPS' in prompt
    assert 'FUNCTIONAL REQUIREMENTS' in prompt
    assert 'NON-FUNCTIONAL REQUIREMENTS' in prompt
    assert 'REFERENCE ASSUMPTIONS' in prompt
    assert 'One region is the reference scenario' in prompt
    assert 'Candidate: Skipped' in prompt
    assert 'interview:answered' in prompt
    assert 'selected' not in prompt
    assert '70% quality threshold' not in prompt
    assert 'score ≤40' not in prompt
    assert '"scalability": 75' not in prompt
    assert '96-100 means excellent alignment' in prompt


@pytest.mark.asyncio
async def test_complete_review_preserves_scores_and_provenance_without_reference_fetch(reference_calls):
    adapter = SequenceLLM(review())
    result = await service(adapter).assess_design(architecture())
    assert result.overall_score == 98
    assert result.score_available
    assert result.is_valid
    assert result.requirement_revision == "approved-r3"
    assert result.rubric_version == "2.0"
    assert result.model_version == "test-model"
    assert result.problem_id == "catalog-doc"
    assert adapter.requests[0].metadata["requirement_revision"] == "approved-r3"
    assert adapter.requests[0].metadata["model_version"] == "test-model"
    assert adapter.requests[0].metadata["rubric_version"] == "2.0"
    assert result.trace_id == "0123456789abcdef0123456789abcdef"
    assert result.structural_checks == []
    assert reference_calls == []


@pytest.mark.asyncio
async def test_missing_optional_extension_does_not_lower_or_invalidate_core_review():
    request = architecture()
    request.problem.requirementSpec.functional.append(RequirementSpec.model_validate({"revision": "r", "functional": [{"id": "export", "text": "Export optional archives", "scope": "extension"}]}).functional[0])
    output = review()
    output["requirement_coverage"].append({"requirement_id": "export", "status": "missing", "explanation": "Optional archives are not represented", "evidence_ids": []})
    output["findings"].append({"title": "Optional archive export", "explanation": "An extra capability beyond required scope", "kind": "extension", "severity": "improvement", "requirement_ids": ["export"], "evidence_ids": [], "criterion": None})
    result = await service(SequenceLLM(output)).assess_design(request)
    assert result.score_available
    assert result.is_valid
    assert result.overall_score == 98


def invalid_review(fault):
    output = review()
    if fault == "missing_score":
        output["scores"].pop("observability")
    elif fault in {"null_score", "string_score", "bool_score", "float_score", "range_score"}:
        output["scores"]["observability"] = {"null_score": None, "string_score": "98", "bool_score": True, "float_score": 98.5, "range_score": 101}[fault]
    elif fault == "extra_score":
        output["scores"]["secret_bonus"] = 100
    elif fault == "unknown_evidence":
        output["findings"][0]["evidence_ids"] = ["invented-node"]
    elif fault == "skipped_answer":
        output["findings"][0]["evidence_ids"] = ["interview:skipped"]
    elif fault == "unknown_requirement":
        output["findings"][0]["requirement_ids"] = ["invented-requirement"]
    elif fault == "missing_kind":
        output["findings"][0].pop("kind")
    elif fault == "invalid_kind":
        output["findings"][0]["kind"] = "guess"
    elif fault == "duplicate_coverage":
        output["requirement_coverage"].append(deepcopy(output["requirement_coverage"][0]))
    elif fault == "missing_coverage":
        output["requirement_coverage"].pop()
    elif fault == "unknown_coverage_evidence":
        output["requirement_coverage"][0]["evidence_ids"] = ["invented-connection"]
    elif fault == "unsupported_coverage":
        output["requirement_coverage"][0]["evidence_ids"] = []
    elif fault == "critical_pass":
        output["findings"][0].update(kind="defect", severity="critical", criterion="reliability")
    elif fault == "strength_without_evidence":
        output["findings"][0]["evidence_ids"] = []
    elif fault == "extension_deduction":
        output["findings"][0].update(kind="extension", severity="improvement", criterion="deliverability")
    elif fault == "clarification_critical":
        output["findings"][0].update(kind="clarification", severity="critical")
        output["verdict"] = "more_context_needed"
    elif fault == "revision_without_gap":
        output["verdict"] = "needs_revision"
    elif fault == "context_without_question":
        output["verdict"] = "more_context_needed"
    elif fault == "missing_verdict":
        output.pop("verdict")
    return output


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["missing_score", "null_score", "string_score", "bool_score", "float_score", "range_score", "extra_score", "unknown_evidence", "skipped_answer", "unknown_requirement", "missing_kind", "invalid_kind", "duplicate_coverage", "missing_coverage", "unknown_coverage_evidence", "unsupported_coverage", "critical_pass", "strength_without_evidence", "extension_deduction", "clarification_critical", "revision_without_gap", "context_without_question", "missing_verdict"])
async def test_invalid_output_gets_exactly_one_repair_then_honest_fallback(fault, reference_calls):
    adapter = SequenceLLM(invalid_review(fault))
    result = await service(adapter).assess_design(architecture())
    assert len(adapter.requests) == 2
    assert len(adapter.requests[0].messages) == 2
    assert len(adapter.requests[1].messages) == 4
    assert result.source == "rule_based"
    assert not result.score_available
    assert not result.is_valid
    assert result.overall_score == 0
    assert result.verdict == "unavailable"
    assert result.model_version == "test-model"
    assert result.requirement_revision == "approved-r3"
    assert all(score == 0 for score in result.scores.model_dump().values())
    assert len(reference_calls) == 1
    assert len(result.structural_checks) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [None, "not json", "[]", "{}", '{"scores":'])
async def test_malformed_output_is_repaired_once(invalid, reference_calls):
    adapter = SequenceLLM(invalid, review())
    result = await service(adapter).assess_design(architecture())
    assert result.source == "ai"
    assert result.overall_score == 98
    assert len(adapter.requests) == 2
    assert reference_calls == []


@pytest.mark.asyncio
async def test_repair_payload_is_bounded():
    adapter = SequenceLLM("x" * 100000, review())
    assessor = service(adapter)
    result = await assessor.assess_design(architecture())
    assert result.score_available
    assert len(adapter.requests[1].messages[2]["content"]) == assessor.MAX_REPAIR_CONTENT_CHARS


@pytest.mark.asyncio
async def test_critical_finding_prevents_pass_without_changing_server_score():
    output = review()
    output["verdict"] = "needs_revision"
    output["findings"] = [{"title": "Contradictory commit description", "explanation": "The write description contradicts the chosen acknowledgement behavior.", "kind": "defect", "severity": "critical", "criterion": "reliability", "requirement_ids": ["durability"], "evidence_ids": ["write"]}]
    result = await service(SequenceLLM(output)).assess_design(architecture())
    assert result.score_available
    assert result.overall_score == 98
    assert not result.is_valid
    assert result.verdict == "needs_revision"
    assert result.findings[0].severity == "critical"


@pytest.mark.asyncio
async def test_low_scores_and_missing_core_are_not_raised_to_a_floor():
    output = review()
    output["scores"]["requirements_alignment"] = 20
    output["verdict"] = "needs_revision"
    output["requirement_coverage"][0].update(status="missing", evidence_ids=[])
    output["findings"] = [{"title": "Missing create capability", "explanation": "The submitted API has no required create flow.", "kind": "defect", "severity": "important", "criterion": "requirements_alignment", "requirement_ids": ["create"], "evidence_ids": ["api"], "scored_gap": True, "recommendation": "Add the document creation path."}]
    result = await service(SequenceLLM(output)).assess_design(architecture())
    assert result.score_available
    assert result.scores.requirements_alignment == 20
    assert not result.is_valid
    assert result.overall_score == 93


@pytest.mark.asyncio
async def test_provider_failure_is_not_retried_as_malformed_output(reference_calls):
    adapter = SequenceLLM(RuntimeError("provider unavailable"))
    result = await service(adapter).assess_design(architecture())
    assert not result.score_available
    assert len(adapter.requests) == 1
    assert len(reference_calls) == 1
    assert [check.status for check in result.integrity_checks] == ["passed"] * 3


@pytest.mark.asyncio
async def test_shared_deadline_bounds_generation_and_repair():
    adapter = SequenceLLM({}, review(), delay=0.02)
    result = await service(adapter, assessment_timeout_seconds=0.03).assess_design(architecture())
    assert not result.score_available
    assert len(adapter.requests) <= 2


def test_timeout_environment_and_azure_model_provenance(monkeypatch):
    monkeypatch.setenv("LLM_ASSESSMENT_TIMEOUT_SECONDS", "12")
    settings = Settings(
        _env_file=None, JWT_SECRET_KEY="test-key", GOOGLE_CLIENT_ID="test-client",
        AWS_ACCESS_KEY_ID="test-key", AWS_SECRET_ACCESS_KEY="test-secret",
        ANALYTICS_S3_BUCKET="test-bucket", WHISPER_SERVICE_URL="http://localhost",
        LANGFUSE_ENABLED=False,
    )
    assessor = AIAssessorService(llm=SequenceLLM(review()), settings=settings)
    assert assessor._assessment_timeout_seconds == 12
    assessor.settings = Settings.model_construct(llm_provider="azure_openai", azure_openai_deployment="review-deployment", llm_model="configured-base-model")
    assert assessor._fallback_assessment(architecture()).model_version == "review-deployment"


@pytest.mark.asyncio
async def test_invalid_diagram_ids_never_receive_ai_grade(reference_calls):
    request = architecture()
    request.connections[0].target = "absent"
    adapter = SequenceLLM(review())
    result = await service(adapter).assess_design(request)
    assert not result.score_available
    assert adapter.requests == []
    assert reference_calls == []
    assert result.integrity_checks[-1].status == "failed"


@pytest.mark.asyncio
async def test_approved_resolution_runs_off_event_loop_and_preserves_learner_answers():
    request = architecture()
    original = request.model_dump()
    thread_ids = []
    record = {"title": "Approved documents", "description": "Approved brief", "requirementSpec": specification(), "requirements": ["Legacy requirement"], "constraints": ["Approved constraint"], "expected_answer": "DO-NOT-LEAK", "walkthrough": "DO-NOT-LEAK"}

    def lookup(problem_id):
        assert problem_id == "catalog-doc"
        thread_ids.append(threading.get_ident())
        return record

    resolved = await assessment_router.resolve_problem_context(request, lookup)
    assert thread_ids[0] != threading.get_ident()
    assert request.model_dump() == original
    assert resolved.problem.title == "Approved documents"
    assert resolved.problem.requirementRevision == "approved-r3"
    assert resolved.interviewSession == request.interviewSession
    assert resolved.explanation == request.explanation
    assert resolved.keyPoints == request.keyPoints
    assert "DO-NOT-LEAK" not in get_assessment_prompt(resolved)


@pytest.mark.asyncio
async def test_backend_replaces_unapproved_client_spec_and_legacy_records_do_not_gain_it():
    request = architecture()
    request.problem.requirementSpec.functional[0].text = "Unapproved new scope"
    resolved = await assessment_router.resolve_problem_context(request, lambda _: {"requirementSpec": specification()})
    assert resolved.problem.requirementSpec.functional[0].text == "Store submitted documents"
    request.problem.requirementSpec = None
    resolved = await assessment_router.resolve_problem_context(request, lambda _: {"requirements": ["Keep the original mixed scope"], "constraints": ["Actual restriction"]})
    assert resolved.problem.requirementSpec is None
    assert resolved.problem.requirements == "Keep the original mixed scope"


@pytest.mark.asyncio
async def test_revision_conflict_requires_a_visible_context_update():
    request = architecture()
    request.problem.requirementRevision = "saved-r1"
    approved_spec = specification()
    async def lookup(_):
        return {"requirementSpec": approved_spec}
    with pytest.raises(HTTPException) as error:
        await assessment_router.resolve_problem_context(request, lookup)
    assert error.value.status_code == 409
    assert error.value.detail["requested_revision"] == "saved-r1"


@pytest.mark.asyncio
async def test_custom_and_free_form_contexts_remain_permitted():
    request = architecture()
    assert await assessment_router.resolve_problem_context(request, lambda _: None) is request
    request.problem.id = None

    def unexpected_lookup(_):
        pytest.fail("Free-form context must not query the catalog")

    assert await assessment_router.resolve_problem_context(request, unexpected_lookup) is request
    request.problem = None
    assert await assessment_router.resolve_problem_context(request, unexpected_lookup) is request


@pytest.mark.asyncio
async def test_catalog_outage_does_not_trust_client_scope():
    def unavailable(_):
        raise RuntimeError("catalog down")

    request = architecture()
    with pytest.raises(HTTPException) as error:
        await assessment_router.resolve_problem_context(request, unavailable)
    assert error.value.status_code == 503


def test_http_route_uses_injected_catalog_and_returns_the_trust_contract():
    adapter = SequenceLLM(review())
    app = FastAPI()
    app.include_router(assessment_router.router, prefix="/api/v1")
    app.dependency_overrides[assessment_router.get_assessor_service] = lambda: service(adapter)
    app.dependency_overrides[assessment_router.get_problem_lookup] = lambda: lambda _: {"requirementSpec": specification()}
    response = TestClient(app).post("/api/v1/assess", json=architecture().model_dump())
    assert response.status_code == 200
    data = response.json()
    assert data["score_available"]
    assert data["verdict"] == "strong_alignment"
    assert data["assessment_id"]
    assert data["requirement_revision"] == "approved-r3"
    assert len(data["requirement_coverage"]) == 2
    assert data["model_version"] == "test-model"


def scored_defect_review():
    output = review()
    output["verdict"] = "needs_revision"
    output["scores"]["reliability"] = 84
    output["findings"].append({
        "title": "Acknowledgement precedes durable storage",
        "explanation": "The write path acknowledges before durable storage, contradicting the required committed-document durability.",
        "recommendation": "Acknowledge only after the durable write completes.",
        "kind": "defect", "severity": "important", "scored_gap": True,
        "criterion": "reliability", "requirement_ids": ["durability"], "evidence_ids": ["write"],
    })
    return output


@pytest.mark.asyncio
@pytest.mark.parametrize("dimension", list(AIAssessorService._SCORE_WEIGHTS))
async def test_material_deduction_without_a_scored_gap_is_rejected(dimension):
    output = review()
    output["scores"][dimension] = 94
    adapter = SequenceLLM(output)
    result = await service(adapter).assess_design(architecture())
    assert len(adapter.requests) == 2
    assert not result.score_available
    assert result.overall_score == 0
    assert output["scores"][dimension] == 94
    assert dimension in adapter.requests[1].messages[-1]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["unmarked", "no_evidence", "no_core_link", "no_action", "clarification", "optional", "wrong_dimension", "string_flag"])
async def test_material_scored_gaps_require_actionable_core_evidence(fault):
    output = scored_defect_review()
    gap = output["findings"][-1]
    if fault == "unmarked":
        gap["scored_gap"] = False
    elif fault == "no_evidence":
        gap["evidence_ids"] = []
    elif fault == "no_core_link":
        gap["requirement_ids"] = []
    elif fault == "no_action":
        gap["recommendation"] = " "
    elif fault == "clarification":
        gap.update(kind="clarification", scored_gap=False, criterion=None)
        output["verdict"] = "more_context_needed"
    elif fault == "optional":
        gap.update(kind="extension", scored_gap=False, severity="improvement", criterion=None)
        output["verdict"] = "strong_alignment"
    elif fault == "wrong_dimension":
        gap["criterion"] = "cost_efficiency"
    else:
        gap["scored_gap"] = "true"
    adapter = SequenceLLM(output)
    result = await service(adapter).assess_design(architecture())
    assert not result.score_available
    assert len(adapter.requests) == 2


@pytest.mark.asyncio
async def test_justified_material_deduction_is_preserved():
    request = architecture()
    request.connections[0].description = "Acknowledge before the durable write completes."
    adapter = SequenceLLM(scored_defect_review())
    result = await service(adapter).assess_design(request)
    assert result.score_available
    assert result.scores.reliability == 84
    assert result.overall_score == 96
    assert not result.is_valid
    assert len(adapter.requests) == 1


@pytest.mark.asyncio
async def test_positive_only_complete_qualitative_review_is_not_forced_to_100():
    result = await service(SequenceLLM(review(96))).assess_design(architecture())
    assert result.score_available
    assert result.overall_score == 96


@pytest.mark.asyncio
async def test_positive_only_review_is_rejected_for_unexplained_deductions():
    request = architecture()
    archived_result = review(92)
    adapter = SequenceLLM(deepcopy(archived_result))
    result = await service(adapter).assess_design(request)
    assert all(finding["kind"] == "strength" for finding in archived_result["findings"])
    assert not result.score_available
    assert len(adapter.requests) == 2
    assert "Material score deductions require scored_gap" in adapter.requests[1].messages[-1]["content"]


def test_legacy_scope_references_preserve_the_original_text():
    request = architecture()
    request.problem.requirementSpec = None
    request.problem.requirements = "Store documents\nSupport collaboration"
    request.problem.constraints = "Low latency for collaboration"
    original = request.model_dump()
    refs = get_assessment_requirement_refs(request)
    assert refs["legacy-requirement:2"].text == "Support collaboration"
    assert refs["legacy-constraint:1"].text == "Low latency for collaboration"
    assert request.model_dump() == original
    assert request.problem.requirementSpec is None


@pytest.mark.asyncio
async def test_legacy_scope_can_support_an_actionable_deduction():
    request = architecture()
    request.problem.requirementSpec = None
    request.problem.requirements = "Preserve committed documents"
    output = scored_defect_review()
    output["requirement_coverage"] = []
    for finding in output["findings"]:
        finding["requirement_ids"] = ["legacy-requirement:1"]
    result = await service(SequenceLLM(output)).assess_design(request)
    assert result.score_available
    assert result.scores.reliability == 84


@pytest.mark.asyncio
async def test_custom_prefix_never_queries_the_catalog():
    request = architecture()
    request.problem.id = "custom-documents"

    def forbidden(_):
        pytest.fail("Custom IDs must not make catalog reads")

    assert await assessment_router.resolve_problem_context(request, forbidden) is request


@pytest.mark.asyncio
async def test_repair_can_return_a_grounded_lower_score_without_inflation():
    adapter = SequenceLLM(review(92), scored_defect_review())
    result = await service(adapter).assess_design(architecture())
    assert len(adapter.requests) == 2
    assert result.score_available
    assert result.scores.reliability == 84
    assert not result.is_valid
    assert result.findings[-1].scored_gap


@pytest.mark.asyncio
async def test_generation_and_repair_use_the_same_strict_output_schema():
    adapter = SequenceLLM(review(92), scored_defect_review())
    result = await service(adapter).assess_design(architecture())
    assert result.score_available
    assert result.scores.reliability == 84
    first, repair = [item.response_format for item in adapter.requests]
    assert first == repair
    assert first["type"] == "json_schema"
    assert first["json_schema"]["strict"] is True
    schema = first["json_schema"]["schema"]
    assert set(schema["properties"]["scores"]["required"]) == set(AIAssessorService._SCORE_WEIGHTS)
    analysis = schema["properties"]["detailed_analysis"]
    assert analysis["additionalProperties"] is False
    assert "strengths" not in analysis["properties"]
    assert schema["properties"]["strengths"]["type"] == "array"


def test_prompt_verdict_and_evidence_first_order_match_validation():
    prompt = get_assessment_prompt(architecture())
    assert "no unresolved defect or clarification" in prompt
    assert "Map coverage and findings before choosing scores" in prompt


def test_validation_logs_use_fixed_codes_not_learner_or_provider_content():
    assert AIAssessorService._validation_error_code(ValueError("Material score deductions require sensitive example")) == "ungrounded_deduction"
    assert AIAssessorService._validation_error_code(ValueError("private design text")) == "invalid_contract"
