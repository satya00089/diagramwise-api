"""Service for assessing system design diagrams using AI and rule-based methods."""

from typing import Mapping, TypeAlias, TypedDict, cast
import json
import logging
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
    FeedbackCategory,
    FeedbackType,
    FindingSeverity,
    ReviewFinding,
    ScoreBreakdown,
    ValidationFeedback,
)
from app.utils.prompts import (
    get_assessment_prompt,
    get_interview_prompt,
    get_interview_questions_prompt,
)
from app.utils.config import Settings, get_settings
from app.services.llm_client import create_llm_provider
from app.services.llm_port import LLMPort, LLMRequest, LLMResponse


logger = logging.getLogger(__name__)

JsonObject: TypeAlias = dict[str, object]


class Coverage(TypedDict):
    """Description-coverage values calculated from a request."""

    comp_pct: float
    conn_pct: float
    comp_ok: bool
    conn_ok: bool


class AIAssessorService:
    """Service to assess system design diagrams using AI and rule-based methods."""

    def __init__(
        self,
        llm: LLMPort | None = None,
        settings: Settings | None = None,
    ):
        self.settings = settings or get_settings()
        self.llm = llm or create_llm_provider(self.settings)

    async def _generate_json(
        self,
        *,
        task: str,
        messages: list[dict[str, str]],
        tags: tuple[str, ...] = (),
        metadata: Mapping[str, object] | None = None,
    ) -> LLMResponse:
        """Generate structured content through the provider-neutral port."""

        return await self.llm.generate(
            LLMRequest(
                task=task,
                messages=messages,
                max_tokens=self.settings.llm_assessment_max_tokens,
                response_format={"type": "json_object"},
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

    def _compute_coverage(self, request: AssessmentRequest) -> Coverage:
        """Compute description coverage for components and connections."""
        total_comps = len(request.components)
        comps_with_desc = sum(
            1 for c in request.components
            if self._has_meaningful_description(
                (c.properties or {}).get("description", "")
            )
        )
        total_conns = len(request.connections or [])
        conns_with_desc = sum(
            1 for conn in (request.connections or [])
            if self._has_meaningful_description(conn.description)
        )
        return {
            "comp_pct": (comps_with_desc / total_comps * 100) if total_comps else 100,
            "conn_pct": (conns_with_desc / total_conns * 100) if total_conns else 100,
            "comp_ok": (comps_with_desc / total_comps >= 0.70) if total_comps else True,
            "conn_ok": (conns_with_desc / total_conns >= 0.70) if total_conns else True,
        }

    # ------------------------------------------------------------------
    # Main assessment entry-point
    # ------------------------------------------------------------------

    async def assess_design(self, request: AssessmentRequest) -> AssessmentResponse:
        """Assess the system design using AI and fallback to rule-based if needed."""
        start_time = time.time()

        logger.info(
            "AI assessment started model=%s max_completion_tokens=%s components=%s "
            "connections=%s has_problem=%s",
            self.settings.llm_model,
            self.settings.llm_assessment_max_tokens,
            len(request.components),
            len(request.connections or []),
            request.problem is not None,
        )

        # Pre-compute coverage so we can post-filter AI feedback
        coverage = self._compute_coverage(request)

        try:
            # Generate structured prompt
            prompt = get_assessment_prompt(request)

            messages: list[dict[str, str]] = [
                {
                    "role": "system",
                    "content": (
                        "You are a senior system architect and technical lead with 15+ years of experience "
                        "in distributed systems, microservices, and cloud architecture. "
                        "You provide tough but fair assessments. "
                        "When the design meets the 70% description-coverage threshold stated in the prompt, "
                            "do not penalise missing descriptions — focus on architecture quality instead."
                    ),
                },
                {"role": "user", "content": prompt},
            ]
            response = await self._generate_json(
                task="assessment.evaluate-design",
                messages=messages,
                tags=("assessment", "design"),
                metadata={
                    "component_count": len(request.components),
                    "connection_count": len(request.connections or []),
                    "has_problem": request.problem is not None,
                },
            )

            # Keep the complete provider payload available during local
            # debugging. This is intentionally disabled outside debug mode
            # because the response contains the submitted design context.
            if self.settings.debug and response.raw is not None:
                if hasattr(response.raw, "model_dump_json"):
                    raw_response = response.raw.model_dump_json(indent=2)
                else:
                    raw_response = json.dumps(response.raw, default=str, indent=2)
                logger.debug(
                    "Raw LLM assessment response:\n%s",
                    raw_response,
                )

            content = response.content
            usage = response.usage
            reasoning_tokens = usage.reasoning_tokens
            finish_reason = response.finish_reason
            refusal_present = response.refusal_present

            logger.info(
                "AI assessment provider response model=%s finish_reason=%s "
                "prompt_tokens=%s completion_tokens=%s reasoning_tokens=%s "
                "content_length=%s refusal_present=%s elapsed_ms=%s",
                response.model or self.settings.llm_model,
                finish_reason,
                usage.prompt_tokens,
                usage.completion_tokens,
                reasoning_tokens,
                len(content or ""),
                refusal_present,
                int((time.time() - start_time) * 1000),
            )

            if not content:
                raise ValueError(
                    "AI returned no content "
                    f"(finish_reason={finish_reason}, refusal_present={refusal_present})"
                )

            # Parse AI response
            ai_result = self._parse_json_response(content)

            # Transform to response model
            assessment = self._transform_ai_response(ai_result)
            assessment.trace_id = response.trace_id

            # Post-process: suppress description feedback when coverage threshold is met
            assessment = self._filter_description_feedback(assessment, coverage)

            # Calculate processing time
            processing_time = int((time.time() - start_time) * 1000)
            assessment.processing_time_ms = processing_time

            logger.info(
                "AI assessment succeeded score=%s findings=%s elapsed_ms=%s",
                assessment.overall_score,
                len(assessment.findings),
                processing_time,
            )

            return assessment

        except Exception as e:
            logger.warning(
                "AI assessment failed; using rule-based fallback error_type=%s "
                "error=%s elapsed_ms=%s",
                type(e).__name__,
                str(e)[:500],
                int((time.time() - start_time) * 1000),
            )
            # Fallback to rule-based assessment
            return self._fallback_assessment(
                request,
                processing_time_ms=int((time.time() - start_time) * 1000),
            )

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

    # ------------------------------------------------------------------
    # Post-processing
    # ------------------------------------------------------------------

    _DESC_KEYWORDS = (
        "description", "no description", "missing description", "undefined purpose",
        "unclear purpose", "purpose unclear", "lacks description", "lacks detail",
        "component purpose", "add descriptions", "provide descriptions",
        "component documentation", "component_justification",
    )
    _CONN_KEYWORDS = (
        "connection description", "connection label", "connection reasoning",
        "connection clarity", "unclear connection", "missing connection description",
        "add descriptions to connection", "connection lacks",
    )

    def _filter_description_feedback(
        self, assessment: AssessmentResponse, coverage: Coverage
    ) -> AssessmentResponse:
        """Remove or demote description-related feedback when coverage ≥ 70%."""
        comp_ok: bool = coverage["comp_ok"]
        conn_ok: bool = coverage["conn_ok"]

        if not (comp_ok or conn_ok):
            return assessment  # nothing to suppress

        def _matches_keywords(message: str, keywords: tuple[str, ...]) -> bool:
            lower = message.lower()
            return any(keyword in lower for keyword in keywords)

        def _keep_feedback(fb: ValidationFeedback) -> bool:
            component_feedback = fb.category == "component_description" or (
                _matches_keywords(fb.message, self._DESC_KEYWORDS)
            )
            connection_feedback = fb.category == "connection_reasoning" or (
                _matches_keywords(fb.message, self._CONN_KEYWORDS)
            )
            return not ((comp_ok and component_feedback) or (conn_ok and connection_feedback))

        def _keep_text(msg: str) -> bool:
            return not (
                (comp_ok and _matches_keywords(msg, self._DESC_KEYWORDS))
                or (conn_ok and _matches_keywords(msg, self._CONN_KEYWORDS))
            )

        assessment.feedback = [fb for fb in assessment.feedback if _keep_feedback(fb)]
        assessment.improvements = [i for i in assessment.improvements if _keep_text(i)]
        if comp_ok:
            assessment.missing_descriptions = []
        if conn_ok:
            assessment.unclear_connections = []
        return assessment

    # Scoring weights by dimension importance.
    # Architecture-critical dims carry more weight than documentation dims.
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

    def _transform_ai_response(self, ai_result: JsonObject) -> AssessmentResponse:
        # Transform AI JSON response to Pydantic model
        raw_scores = ai_result.get("scores", {})
        if not isinstance(raw_scores, Mapping):
            raise ValueError("AI response field 'scores' must be an object")
        scores = ScoreBreakdown.model_validate(cast(Mapping[str, object], raw_scores))

        raw_feedback = ai_result.get("feedback", [])
        if not isinstance(raw_feedback, list):
            raise ValueError("AI response field 'feedback' must be a list")
        feedback = [
            ValidationFeedback.model_validate(item)
            for item in cast(list[object], raw_feedback)
        ]

        # Weighted average: architecture-critical dims outweigh documentation dims
        weighted_sum = 0.0
        total_weight = 0.0
        for field, weight in self._SCORE_WEIGHTS.items():
            val = getattr(scores, field, None)
            if val is not None:
                weighted_sum += val * weight
                total_weight += weight

        overall_score = round(weighted_sum / total_weight) if total_weight else 0
        overall_score = max(0, min(100, overall_score))

        def string_list(field: str) -> list[str]:
            value = ai_result.get(field, [])
            if not isinstance(value, list):
                return []
            return [
                item
                for item in cast(list[object], value)
                if isinstance(item, str)
            ]

        detailed_analysis = ai_result.get("detailed_analysis")
        if isinstance(detailed_analysis, dict):
            raw_analysis = cast(dict[object, object], detailed_analysis)
            detailed_analysis = {
                key: value
                for key, value in raw_analysis.items()
                if isinstance(key, str) and isinstance(value, str)
            }
        else:
            detailed_analysis = None

        raw_findings = ai_result.get("findings", [])
        if not isinstance(raw_findings, list):
            raise ValueError("AI response field 'findings' must be a list")
        findings = [
            ReviewFinding.model_validate(item)
            for item in cast(list[object], raw_findings)
        ]

        summary = ai_result.get("summary")
        if summary is not None and not isinstance(summary, str):
            raise ValueError("AI response field 'summary' must be a string")

        return AssessmentResponse(
            is_valid=overall_score >= 50,
            overall_score=overall_score,
            scores=scores,
            feedback=feedback,
            summary=summary,
            findings=findings,
            strengths=string_list("strengths"),
            improvements=string_list("improvements"),
            missing_components=string_list("missing_components"),
            missing_descriptions=string_list("missing_descriptions"),
            unclear_connections=string_list("unclear_connections"),
            suggestions=string_list("suggestions"),
            detailed_analysis=detailed_analysis,
            interview_questions=string_list("interview_questions"),
            source=AssessmentSource.AI,
        )

    def _fallback_assessment(
        self,
        request: AssessmentRequest,
        processing_time_ms: int | None = None,
    ) -> AssessmentResponse:
        # Simple rule-based fallback when AI fails
        component_count = len(request.components)
        has_database = any(c.type == "database" for c in request.components)
        has_load_balancer = any(c.type == "load-balancer" for c in request.components)

        # Check for component descriptions
        components_with_descriptions = sum(
            1
            for c in request.components
            if c.properties and c.properties.get("description", "").strip()
        )
        description_score = min(components_with_descriptions * 20, 80)

        base_score = min(component_count * 15, 60)
        if has_database:
            base_score += 10
        if has_load_balancer:
            base_score += 15

        # Create list of components missing descriptions (strip HTML before checking)
        missing_descriptions = [
            c.label
            for c in request.components
            if not self._has_meaningful_description(
                (c.properties or {}).get("description", "")
            )
        ]

        return AssessmentResponse(
            is_valid=base_score >= 50,
            overall_score=base_score,
            scores=ScoreBreakdown(
                scalability=base_score,
                reliability=base_score,
                security=max(base_score - 20, 20),
                maintainability=base_score,
                component_justification=description_score,
                connection_clarity=50 if request.connections else 20,
            ),
            feedback=[
                ValidationFeedback(
                    type=FeedbackType.WARNING,
                    message="AI assessment is temporarily unavailable; a rule-based assessment was used instead.",
                    category=FeedbackCategory.MAINTAINABILITY,
                )
            ],
            summary=(
                "The AI reviewer was unavailable, so this result is a basic structural check "
                "of the diagram rather than a full architecture review."
            ),
            findings=[
                ReviewFinding(
                    title="Full architecture review unavailable",
                    explanation=(
                        "This assessment could not evaluate the design against the problem context "
                        "and production failure modes with the AI reviewer."
                    ),
                    recommendation=(
                        "Retry the assessment when the review service is available before treating "
                        "this score as design feedback."
                    ),
                    severity=FindingSeverity.IMPORTANT,
                )
            ],
            strengths=["Basic architecture components present"],
            improvements=[
                "Add detailed component documentation and connection reasoning"
            ],
            missing_components=[],
            missing_descriptions=missing_descriptions,
            unclear_connections=(
                [] if request.connections else ["No connections defined"]
            ),
            suggestions=[
                "Consider adding monitoring and caching layers",
                "Provide detailed component descriptions",
            ],
            processing_time_ms=processing_time_ms,
            source=AssessmentSource.RULE_BASED,
        )
