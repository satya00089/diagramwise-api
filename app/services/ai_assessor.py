"""Service for assessing system design diagrams using AI and rule-based methods."""

from typing import Mapping, TypeAlias, cast
import asyncio
import json
import logging
import math
import re
import time

from app.models.request_models import (
    AssessmentRequest,
    InterviewQuestionsRequest,
    InterviewRequest,
)
from app.models.reasoning_models import InterviewQuestionsResponse, InterviewResponse
from app.models.response_models import (
    AssessmentSource,
    AssessmentResponse,
    AssessmentVerdict,
    FeedbackCategory,
    FeedbackType,
    FindingSeverity,
    FindingKind,
    IntegrityCheck,
    RequirementCoverage,
    ReviewFinding,
    ScoreBreakdown,
    StructuralCheck,
    ValidationFeedback,
)
from app.utils.prompts import (
    get_assessment_prompt,
    get_assessment_evidence_ids,
    get_assessment_requirement_refs,
    get_interview_prompt,
    get_interview_questions_prompt,
)
from app.utils.config import Settings, get_settings
from app.services.llm_client import create_llm_provider
from app.services.llm_port import LLMPort, LLMRequest, LLMResponse
from app.utils.assessment_schema import assessment_response_format


logger = logging.getLogger(__name__)

JsonObject: TypeAlias = dict[str, object]


class AIAssessorService:
    """Service to assess system design diagrams using AI and rule-based methods."""

    RUBRIC_VERSION = "2.0"
    ASSESSMENT_TIMEOUT_SECONDS = 45.0
    MAX_REPAIR_CONTENT_CHARS = 24000
    MATERIAL_GAP_THRESHOLD = 96

    def __init__(
        self,
        llm: LLMPort | None = None,
        settings: Settings | None = None,
        assessment_timeout_seconds: float | None = None,
    ):
        self.settings = settings or get_settings()
        self.llm = llm or create_llm_provider(self.settings)
        configured_timeout = getattr(self.settings, "llm_assessment_timeout_seconds", self.ASSESSMENT_TIMEOUT_SECONDS)
        self._assessment_timeout_seconds = (
            assessment_timeout_seconds if assessment_timeout_seconds is not None
            else float(configured_timeout)
        )
        if not math.isfinite(self._assessment_timeout_seconds) or self._assessment_timeout_seconds <= 0:
            raise ValueError("The assessment timeout must be a positive finite number")

    async def _generate_json(
        self,
        *,
        task: str,
        messages: list[dict[str, str]],
        tags: tuple[str, ...] = (),
        metadata: Mapping[str, object] | None = None,
        response_format: Mapping[str, object] | None = None,
    ) -> LLMResponse:
        """Generate structured content through the provider-neutral port."""

        return await self.llm.generate(
            LLMRequest(
                task=task,
                messages=list(messages),
                max_tokens=self.settings.llm_assessment_max_tokens,
                response_format=response_format or {"type": "json_object"},
                temperature=self.settings.llm_temperature,
                reasoning_effort=self.settings.llm_assessment_reasoning_effort,
                tags=tags,
                metadata=metadata or {},
            )
        )

    # ------------------------------------------------------------------
    # Coverage helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _has_meaningful_description(text: str | None) -> bool:
        """Return True if text has at least 10 real characters after stripping HTML."""
        if not isinstance(text, str):
            return False
        stripped = re.sub(r"<[^>]+>", "", text).strip()
        return len(stripped) >= 10

    @staticmethod
    def _parse_json_response(content: str | None) -> JsonObject:
        """Parse a JSON-object model response, including fenced JSON output."""
        if not content or not content.strip():
            raise ValueError("The AI returned an empty response")
        text = content.strip()
        if text.startswith("```"):
            text = text[3:]
            if text[:4].lower() == "json":
                text = text[4:]
            text = text.strip()
            if text.endswith("```"):
                text = text[:-3].rstrip()
        parsed: object = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("The AI response must be a JSON object")
        raw_object = cast(dict[object, object], parsed)
        if not all(isinstance(key, str) for key in raw_object):
            raise ValueError("AI response object keys must be strings")
        return {cast(str, key): value for key, value in raw_object.items()}

    async def assess_design(self, request: AssessmentRequest) -> AssessmentResponse:
        """Review with strict output validation and at most one bounded repair."""
        start_time = time.monotonic()
        deadline = start_time + self._assessment_timeout_seconds
        trace_id: str | None = None
        rejection_reason: str | None = None
        if any(check.status == "failed" for check in self._integrity_checks(request)):
            return self._fallback_assessment(request, processing_time_ms=0)

        messages = self._assessment_messages(request)
        metadata = self._assessment_metadata(request)
        try:
            for attempt in range(2):
                assessment, trace_id, rejection_reason = await self._assessment_attempt(
                    request=request,
                    messages=messages,
                    metadata=metadata,
                    attempt=attempt,
                    deadline=deadline,
                    trace_id=trace_id,
                )
                if assessment is not None:
                    return self._complete_assessment(
                        assessment, trace_id, start_time
                    )
        except Exception as error:
            logger.warning(
                "AI assessment unavailable error_type=%s rejection_reason=%s elapsed_ms=%s",
                type(error).__name__, rejection_reason, int((time.monotonic() - start_time) * 1000),
            )

        return await self._fallback_after_assessment_failure(
            request, start_time, trace_id
        )

    @staticmethod
    def _assessment_messages(request: AssessmentRequest) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "You are a precise system-design reviewer. Evaluate published core "
                    "requirements using submitted evidence. Distinguish defects, "
                    "clarifications, optional extensions and strengths. Return the "
                    "requested JSON only, without reference-answer bias or score floors."
                ),
            },
            {"role": "user", "content": get_assessment_prompt(request)},
        ]

    def _assessment_metadata(self, request: AssessmentRequest) -> dict[str, object]:
        problem = request.problem
        return {
            "component_count": len(request.components),
            "connection_count": len(request.connections or []),
            "has_problem": problem is not None,
            "problem_id": problem.id if problem else None,
            "requirement_revision": self._requirement_revision(request),
            "rubric_version": self.RUBRIC_VERSION,
            "model_version": self._model_version(),
        }

    async def _assessment_attempt(
        self,
        *,
        request: AssessmentRequest,
        messages: list[dict[str, str]],
        metadata: dict[str, object],
        attempt: int,
        deadline: float,
        trace_id: str | None,
    ) -> tuple[AssessmentResponse | None, str | None, str | None]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Assessment deadline exceeded")
        response = await asyncio.wait_for(
            self._generate_json(
                task="assessment.evaluate-design" if attempt == 0 else "assessment.repair-design",
                messages=messages,
                tags=("assessment", "design") if attempt == 0 else ("assessment", "repair"),
                metadata={**metadata, "attempt": attempt, "repair_of_trace_id": trace_id},
                response_format=assessment_response_format(self._SCORE_WEIGHTS),
            ),
            timeout=remaining,
        )
        trace_id = response.trace_id or trace_id
        try:
            if response.refusal_present or response.finish_reason in {"length", "content_filter"}:
                raise ValueError("Provider returned a refused or incomplete assessment")
            assessment = self._transform_ai_response(
                self._parse_json_response(response.content), request=request
            )
        except ValueError as error:
            reason = self._validation_error_code(error)
            if attempt == 1:
                raise
            logger.info(
                "AI assessment output rejected reason=%s; attempting one repair", reason
            )
            self._append_repair_prompt(messages, response.content, error)
            return None, trace_id, reason
        return assessment, trace_id, None

    def _append_repair_prompt(
        self,
        messages: list[dict[str, str]],
        content: str | None,
        error: ValueError,
    ) -> None:
        messages.extend([
            {
                "role": "assistant",
                "content": (content or "")[:self.MAX_REPAIR_CONTENT_CHARS],
            },
            {
                "role": "user",
                "content": (
                    "The preceding output failed validation: "
                    + str(error)[:4000]
                    + "\\nReturn a complete corrected JSON object using the original "
                    "rubric and submitted evidence. Include all twelve integer scores, "
                    "the verdict, finding kinds and exact references, and every "
                    "requirement coverage entry. Every material deduction needs a "
                    "scored_gap=true defect with criterion, submitted evidence, core "
                    "requirement reference and actionable recommendation. Clarifications "
                    "and optional suggestions are unscored. Do not invent evidence to repair an "
                    "invalid reference or change scores to satisfy an acceptance target. "
                    "Keep detailed_analysis limited to eight dimension strings. Put strengths, "
                    "improvements, missing_components, missing_descriptions, unclear_connections, "
                    "suggestions and interview_questions at the top level, never inside detailed_analysis."
                ),
            },
        ])

    def _complete_assessment(
        self,
        assessment: AssessmentResponse,
        trace_id: str | None,
        start_time: float,
    ) -> AssessmentResponse:
        assessment.trace_id = trace_id
        assessment.processing_time_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(
            "AI assessment succeeded score=%s verdict=%s rubric=%s revision=%s",
            assessment.overall_score, assessment.verdict.value,
            assessment.rubric_version, assessment.requirement_revision,
        )
        return assessment

    async def _fallback_after_assessment_failure(
        self,
        request: AssessmentRequest,
        start_time: float,
        trace_id: str | None,
    ) -> AssessmentResponse:

        fallback = self._fallback_assessment(
            request, processing_time_ms=int((time.monotonic() - start_time) * 1000)
        )
        fallback.trace_id = trace_id
        try:
            # The reference checker is deliberately imported and invoked only
            # after AI failure. It must never influence a successful AI review.
            from app.services.walkthrough_reference import get_fallback_reference_checks

            checks = await asyncio.wait_for(get_fallback_reference_checks(request), timeout=5.0)
            fallback.structural_checks = [StructuralCheck.model_validate(check) for check in checks]
        except Exception as error:
            logger.warning("Fallback reference checks unavailable error_type=%s", type(error).__name__)
        fallback.processing_time_ms = int((time.monotonic() - start_time) * 1000)
        return fallback

    async def generate_interview_questions(
        self, request: InterviewQuestionsRequest
    ) -> InterviewQuestionsResponse:
        """Generate questions for the pre-assessment interview dialog."""
        prompt = get_interview_questions_prompt(request)
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "You are a precise system-design interviewer. "
                    "Return only the requested JSON object."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        response = await self._generate_json(
            task="interview.generate-questions",
            messages=messages,
            tags=("interview", "questions"),
        )
        content = response.content
        result = self._parse_json_response(content)
        raw_questions = result.get("questions", [])
        questions = (
            [
                question.strip()
                for question in cast(list[object], raw_questions)
                if isinstance(question, str) and question.strip()
            ]
            if isinstance(raw_questions, list)
            else []
        )

        if not questions:
            raise ValueError("AI interview response did not include questions")

        return InterviewQuestionsResponse(questions=questions[:5])

    async def critique_interview_answer(
        self, request: InterviewRequest
    ) -> InterviewResponse:
        """Critique one answer while reusing the assessment AI configuration."""
        prompt = get_interview_prompt(request)
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "You are a rigorous but supportive system-design interviewer. "
                    "Return only the requested JSON object and keep the candidate thinking."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        response = await self._generate_json(
            task="interview.critique-answer",
            messages=messages,
            tags=("interview", "critique"),
        )
        content = response.content
        result = self._parse_json_response(content)

        critique = result.get("critique")
        if not isinstance(critique, str) or not critique.strip():
            raise ValueError("AI interview response must include a critique")

        def string_list(field: str) -> list[str]:
            value = result.get(field, [])
            if not isinstance(value, list):
                return []
            return [item for item in cast(list[object], value) if isinstance(item, str)]

        next_question = result.get("next_question")
        if next_question is not None and not isinstance(next_question, str):
            next_question = None

        return InterviewResponse(
            critique=critique.strip(),
            strengths=string_list("strengths"),
            gaps=string_list("gaps"),
            nextQuestion=next_question.strip() if isinstance(next_question, str) else None,
        )

    # Fixed denominator: all dimensions remain present for every AI review.
    _SCORE_WEIGHTS: dict[str, float] = {
        "scalability": 2.0,
        "reliability": 2.0,
        "security": 2.0,
        "maintainability": 2.0,
        "performance": 1.5,
        "observability": 1.5,
        "deliverability": 1.5,
        "cost_efficiency": 1.0,
        "requirements_alignment": 1.0,
        "constraint_compliance": 1.0,
        "component_justification": 0.75,
        "connection_clarity": 0.75,
    }

    @staticmethod
    def _validation_error_code(error: ValueError) -> str:
        from pydantic import ValidationError
        if isinstance(error, json.JSONDecodeError):
            return "invalid_json"
        if isinstance(error, ValidationError):
            return "invalid_schema"
        message = str(error)
        for prefix, code in (
            ("Material score deductions", "ungrounded_deduction"),
            ("Requirement coverage", "incomplete_coverage"),
            ("Finding contains unknown", "invalid_finding_reference"),
            ("Coverage contains unknown", "invalid_coverage_reference"),
            ("Strong alignment", "inconsistent_verdict"),
            ("Provider returned", "incomplete_provider_output"),
        ):
            if message.startswith(prefix):
                return code
        return "invalid_contract"

    @staticmethod
    def _requirement_revision(request: AssessmentRequest) -> str | None:
        if not request.problem:
            return None
        if request.problem.requirementSpec:
            return request.problem.requirementSpec.revision
        return request.problem.requirementRevision

    def _model_version(self) -> str | None:
        settings = getattr(self, "settings", None)
        if settings is None:
            return None
        if settings.llm_provider == "azure_openai":
            return settings.azure_openai_deployment or settings.llm_model
        return settings.llm_model

    @staticmethod
    def _integrity_checks(request: AssessmentRequest) -> list[IntegrityCheck]:
        component_ids = [component.id for component in request.components]
        connections = request.connections or []
        all_ids = component_ids + [connection.id for connection in connections]
        valid_ids = bool(all_ids) and all(identifier.strip() for identifier in all_ids)
        unique = valid_ids and len(all_ids) == len(set(all_ids))
        dangling = [
            connection.id for connection in connections
            if connection.source not in component_ids or connection.target not in component_ids
        ]
        return [
            IntegrityCheck(
                check="components_present",
                status="passed" if component_ids else "failed",
                explanation=f"{len(component_ids)} components supplied.",
                evidence_ids=component_ids,
            ),
            IntegrityCheck(
                check="unique_identifiers",
                status="passed" if unique else "failed",
                explanation="Component and connection IDs are nonempty and unique."
                if unique else "Some component or connection IDs are empty or duplicated.",
                evidence_ids=[] if unique else all_ids,
            ),
            IntegrityCheck(
                check="connection_endpoints",
                status="failed" if dangling else "passed",
                explanation="Every supplied connection refers to supplied components."
                if not dangling else "Some connections refer to components absent from this request.",
                evidence_ids=dangling,
            ),
        ]

    def _validate_grounding(
        self, assessment: AssessmentResponse, request: AssessmentRequest
    ) -> None:
        evidence_ids = get_assessment_evidence_ids(request)
        requirement_refs = get_assessment_requirement_refs(request)
        missing_core, core_coverage = self._validate_coverage(
            assessment, request, requirement_refs, evidence_ids
        )
        for finding in assessment.findings:
            self._validate_finding_grounding(
                finding, evidence_ids, requirement_refs, missing_core
            )
        self._validate_material_deductions(assessment)
        self._validate_verdict_coverage(assessment, core_coverage)

    def _validate_coverage(
        self,
        assessment: AssessmentResponse,
        request: AssessmentRequest,
        requirement_refs: dict[str, Any],
        evidence_ids: set[str],
    ) -> tuple[set[str], list[RequirementCoverage]]:
        spec = request.problem.requirementSpec if request.problem else None
        requirements = {
            item.id: item for item in spec.functional + spec.nonFunctional
        } if spec else {}
        coverage = assessment.requirement_coverage
        # Legacy anchors retain the exact brief without pretending it is typed.
        if spec is None and coverage:
            requirements = requirement_refs
        coverage_ids = [item.requirement_id for item in coverage]
        if len(coverage_ids) != len(set(coverage_ids)) or set(coverage_ids) != set(requirements):
            raise ValueError("Requirement coverage must contain every supplied requirement ID exactly once")
        missing_core = {
            item.requirement_id for item in coverage
            if item.status == "missing" and requirements[item.requirement_id].scope == "core"
        }
        for item in coverage:
            self._validate_coverage_evidence(item, evidence_ids)
        core_coverage = [
            item for item in coverage
            if requirements[item.requirement_id].scope == "core"
        ]
        return missing_core, core_coverage

    @staticmethod
    def _validate_coverage_evidence(
        item: RequirementCoverage, evidence_ids: set[str]
    ) -> None:
        if not set(item.evidence_ids) <= evidence_ids:
            raise ValueError("Coverage contains unknown evidence IDs")
        if item.status in {"supported", "partial"} and not item.evidence_ids:
            raise ValueError("Supported or partial coverage requires submitted evidence")

    def _validate_finding_grounding(
        self,
        finding: ReviewFinding,
        evidence_ids: set[str],
        requirement_refs: dict[str, Any],
        missing_core: set[str],
    ) -> None:
        self._validate_finding_references(finding, evidence_ids, requirement_refs)
        if finding.kind == FindingKind.DEFECT:
            self._validate_defect_grounding(finding, requirement_refs, missing_core)
        if finding.kind == FindingKind.STRENGTH and not finding.evidence_ids:
            raise ValueError("A strength must cite submitted evidence")
        if finding.kind != FindingKind.DEFECT and (finding.scored_gap or finding.criterion is not None):
            raise ValueError("Strengths, clarifications and optional extensions cannot justify deductions")
        if finding.scored_gap:
            self._validate_scored_gap(finding, requirement_refs)

    def _validate_finding_references(
        self,
        finding: ReviewFinding,
        evidence_ids: set[str],
        requirement_refs: dict[str, Any],
    ) -> None:
        if not set(finding.evidence_ids) <= evidence_ids:
            raise ValueError("Finding contains unknown evidence IDs")
        if not set(finding.requirement_ids) <= set(requirement_refs):
            raise ValueError("Finding contains unknown requirement IDs")
        if finding.criterion is not None and finding.criterion not in self._SCORE_WEIGHTS:
            raise ValueError("Finding criterion must be a rubric dimension")

    @staticmethod
    def _validate_defect_grounding(
        finding: ReviewFinding,
        requirement_refs: dict[str, Any],
        missing_core: set[str],
    ) -> None:
        if not finding.criterion:
            raise ValueError("A scored defect must name an applicable rubric criterion")
        if not finding.evidence_ids and not set(finding.requirement_ids) & missing_core:
            raise ValueError("A defect needs submitted evidence or a missing core requirement")
        if finding.requirement_ids and all(
            requirement_refs[identifier].scope == "extension"
            for identifier in finding.requirement_ids
        ):
            raise ValueError("An extension-only gap cannot be a required-scope defect")

    @staticmethod
    def _validate_scored_gap(
        finding: ReviewFinding, requirement_refs: dict[str, Any]
    ) -> None:
        if finding.kind != FindingKind.DEFECT or not finding.criterion:
            raise ValueError("A scored_gap must be a defect with an applicable rubric criterion")
        has_core_requirement = any(
            requirement_refs[identifier].scope == "core"
            for identifier in finding.requirement_ids
        )
        if not finding.evidence_ids or not has_core_requirement:
            raise ValueError("A scored_gap requires submitted evidence and a core requirement reference")
        if not finding.recommendation or not finding.recommendation.strip():
            raise ValueError("A scored_gap requires an actionable recommendation")

    def _validate_material_deductions(self, assessment: AssessmentResponse) -> None:
        justified_dimensions = {finding.criterion for finding in assessment.findings if finding.scored_gap}
        unexplained = [
            dimension for dimension in self._SCORE_WEIGHTS
            if getattr(assessment.scores, dimension) < self.MATERIAL_GAP_THRESHOLD
            and dimension not in justified_dimensions
        ]
        if unexplained:
            raise ValueError(
                "Material score deductions require scored_gap findings with criterion, evidence, "
                "core requirement link and action: " + ", ".join(unexplained)
            )

    @staticmethod
    def _validate_verdict_coverage(
        assessment: AssessmentResponse, core_coverage: list[RequirementCoverage]
    ) -> None:
        if assessment.verdict == AssessmentVerdict.STRONG_ALIGNMENT and any(
            item.status != "supported" for item in core_coverage
        ):
            raise ValueError("Strong alignment requires supported core requirement coverage")
        if assessment.verdict == AssessmentVerdict.MORE_CONTEXT_NEEDED and not (
            any(item.status == "needs_clarification" for item in core_coverage)
            or any(finding.kind == FindingKind.CLARIFICATION for finding in assessment.findings)
        ):
            raise ValueError("More context needed requires an unresolved clarification")
        if assessment.verdict == AssessmentVerdict.NEEDS_REVISION and not (
            any(item.status in {"partial", "missing"} for item in core_coverage)
            or any(finding.kind == FindingKind.DEFECT for finding in assessment.findings)
        ):
            raise ValueError("Needs revision requires a defect or a core coverage gap")

    def _transform_ai_response(
        self, ai_result: JsonObject, request: AssessmentRequest | None = None
    ) -> AssessmentResponse:
        """Validate AI output, preserving legacy response fields but no partial grades."""
        scores, overall_score = self._parse_score_breakdown(ai_result)
        findings = self._parse_review_findings(ai_result)
        verdict = AssessmentVerdict(ai_result.get("verdict"))
        self._validate_findings_against_verdict(findings, verdict, overall_score)
        if "requirement_coverage" not in ai_result:
            raise ValueError("AI output must include requirement_coverage")

        assessment = AssessmentResponse(
            is_valid=verdict == AssessmentVerdict.STRONG_ALIGNMENT,
            overall_score=overall_score,
            score_available=True,
            verdict=verdict,
            scores=scores,
            feedback=ai_result.get("feedback", []),
            summary=ai_result.get("summary"),
            findings=findings,
            requirement_coverage=ai_result["requirement_coverage"],
            strengths=ai_result.get("strengths", []),
            improvements=ai_result.get("improvements", []),
            missing_components=ai_result.get("missing_components", []),
            missing_descriptions=ai_result.get("missing_descriptions", []),
            unclear_connections=ai_result.get("unclear_connections", []),
            suggestions=ai_result.get("suggestions", []),
            detailed_analysis=ai_result.get("detailed_analysis"),
            interview_questions=ai_result.get("interview_questions", []),
            rubric_version=self.RUBRIC_VERSION,
            requirement_revision=self._requirement_revision(request) if request else None,
            problem_id=request.problem.id if request and request.problem else None,
            model_version=self._model_version(),
            source=AssessmentSource.AI,
        )
        if request is not None:
            self._validate_grounding(assessment, request)
        return assessment

    def _parse_score_breakdown(
        self, ai_result: JsonObject
    ) -> tuple[ScoreBreakdown, int]:
        raw_scores = ai_result.get("scores")
        if not isinstance(raw_scores, dict) or set(raw_scores) != set(self._SCORE_WEIGHTS):
            raise ValueError("AI response must include exactly all twelve rubric scores")
        if any(type(value) is not int for value in raw_scores.values()):
            raise ValueError("All rubric scores must be integers, not null, booleans or strings")
        scores = ScoreBreakdown.model_validate(raw_scores)
        overall_score = round(
            sum(raw_scores[field] * weight for field, weight in self._SCORE_WEIGHTS.items())
            / sum(self._SCORE_WEIGHTS.values())
        )
        return scores, overall_score

    @staticmethod
    def _parse_review_findings(ai_result: JsonObject) -> list[ReviewFinding]:
        raw_findings = ai_result.get("findings")
        if not isinstance(raw_findings, list):
            raise ValueError("AI response field 'findings' must be a list")
        for item in raw_findings:
            if not isinstance(item, dict) or not {"kind", "evidence_ids", "requirement_ids"} <= set(item):
                raise ValueError("Each AI finding must include kind, evidence_ids and requirement_ids")
        findings = [ReviewFinding.model_validate(item) for item in raw_findings]
        return findings

    def _validate_findings_against_verdict(
        self,
        findings: list[ReviewFinding],
        verdict: AssessmentVerdict,
        overall_score: int,
    ) -> None:
        if verdict == AssessmentVerdict.UNAVAILABLE:
            raise ValueError("Unavailable AI output cannot carry an architecture score")
        for finding in findings:
            self._validate_finding_severity(finding)
        critical = any(finding.severity == FindingSeverity.CRITICAL for finding in findings)
        if critical and verdict != AssessmentVerdict.NEEDS_REVISION:
            raise ValueError("A critical finding requires a needs_revision verdict")
        if verdict == AssessmentVerdict.STRONG_ALIGNMENT and (
            overall_score < 50 or any(finding.kind in {FindingKind.DEFECT, FindingKind.CLARIFICATION} for finding in findings)
        ):
            raise ValueError("Strong alignment conflicts with unresolved defects, clarifications or low scores")

    @staticmethod
    def _validate_finding_severity(finding: ReviewFinding) -> None:
        if (finding.kind == FindingKind.STRENGTH) != (finding.severity == FindingSeverity.POSITIVE):
            raise ValueError("Positive severity and strength kind must agree")
        if finding.kind == FindingKind.EXTENSION and finding.severity != FindingSeverity.IMPROVEMENT:
            raise ValueError("Optional extensions must use improvement severity")
        if finding.kind == FindingKind.CLARIFICATION and finding.severity == FindingSeverity.CRITICAL:
            raise ValueError("Unknown decisions cannot be critical demonstrated defects")

    def _fallback_assessment(
        self,
        request: AssessmentRequest,
        processing_time_ms: int | None = None,
    ) -> AssessmentResponse:
        """Report only observed integrity; zeros are legacy placeholders, not grades."""
        spec = request.problem.requirementSpec if request.problem else None
        requirements = spec.functional + spec.nonFunctional if spec else []
        return AssessmentResponse(
            is_valid=False,
            overall_score=0,
            score_available=False,
            verdict=AssessmentVerdict.UNAVAILABLE,
            scores=ScoreBreakdown(**dict.fromkeys(self._SCORE_WEIGHTS, 0)),
            feedback=[
                ValidationFeedback(
                    type=FeedbackType.WARNING,
                    message="AI review is unavailable. Only basic diagram integrity checks were performed; no architecture score is available.",
                    category=FeedbackCategory.MAINTAINABILITY,
                )
            ],
            summary=(
                "AI review is unavailable. This is a basic structural check of submitted "
                "identifiers and endpoints, not an architecture assessment. Numeric fields "
                "are compatibility placeholders, not design feedback."
            ),
            findings=[
                ReviewFinding(
                    title="Full architecture review unavailable",
                    explanation="The design has not been evaluated against required scope.",
                    recommendation="Retry the AI review when the service is available.",
                    severity=FindingSeverity.IMPORTANT,
                    kind=FindingKind.CLARIFICATION,
                )
            ],
            requirement_coverage=[
                RequirementCoverage(
                    requirement_id=item.id,
                    status="needs_clarification",
                    explanation="Not evaluated because the AI review is unavailable.",
                ) for item in requirements
            ],
            integrity_checks=self._integrity_checks(request),
            strengths=[],
            improvements=[],
            missing_components=[],
            missing_descriptions=[
                component.label for component in request.components
                if not self._has_meaningful_description(
                    (component.properties or {}).get("purpose")
                    or (component.properties or {}).get("description", "")
                )
            ],
            unclear_connections=[],
            suggestions=["Retry the AI review."],
            processing_time_ms=processing_time_ms,
            rubric_version=self.RUBRIC_VERSION,
            requirement_revision=self._requirement_revision(request),
            problem_id=request.problem.id if request.problem else None,
            model_version=self._model_version(),
            source=AssessmentSource.RULE_BASED,
        )
