"""Router for system design assessment endpoints."""

import uuid
import asyncio
import logging

from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool
from app.models.problem_models import RequirementSpec
from app.models.request_models import AssessmentRequest
from app.models.response_models import AssessmentResponse
from app.models.simulation_models import (
    SimulationPreparationRequest,
    SimulationPreparationResponse,
)
from app.services.ai_assessor import AIAssessorService
from app.services.simulation_preparation import (
    SimulationPreparationError,
    SimulationPreparationService,
)

router = APIRouter()
logger = logging.getLogger(__name__)
ProblemLookup = Callable[[str], dict[str, Any] | None]


def get_assessor_service() -> AIAssessorService:
    """Dependency injection for AIAssessorService."""
    return AIAssessorService()


def get_simulation_preparation_service() -> SimulationPreparationService:
    """Inject the provider-neutral AI graph interpreter."""
    return SimulationPreparationService()


def get_problem_lookup() -> ProblemLookup:
    """Inject the existing catalog reader without adding another data service."""
    from app.services.dynamodb_service import dynamodb_service

    return dynamodb_service.get_problem_by_id


async def resolve_problem_context(
    request: AssessmentRequest, lookup: ProblemLookup
) -> AssessmentRequest:
    """Use approved catalog scope while preserving all learner-authored evidence."""
    problem = request.problem
    if not problem or not problem.id or problem.id.startswith("custom-"):
        return request
    try:
        record = await asyncio.wait_for(
            run_in_threadpool(lookup, problem.id), timeout=10.0
        )
    except Exception as error:
        logger.warning("Assessment catalog lookup unavailable error_type=%s", type(error).__name__)
        raise HTTPException(
            status_code=503, detail="The approved problem brief is temporarily unavailable; retry assessment."
        ) from error
    # Local/custom IDs need not be catalog IDs. Retain their declared context.
    if record is None:
        return request

    spec = RequirementSpec.model_validate(record["requirementSpec"]) if record.get("requirementSpec") is not None else None
    revision = spec.revision if spec else None
    requested_revision = problem.requirementRevision or (
        problem.requirementSpec.revision if problem.requirementSpec else None
    )
    if requested_revision is not None and requested_revision != revision:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "The requested requirement revision is not available in the current catalog. Review the updated brief before reassessing.",
                "requested_revision": requested_revision,
                "current_revision": revision,
            },
        )

    def legacy_text(field: str) -> str:
        value = record.get(field, [])
        return "\n".join(value) if isinstance(value, list) else str(value or "")

    approved_problem = problem.model_copy(update={
        "title": record.get("title", problem.title),
        "description": record.get("description", problem.description),
        "difficulty": record.get("difficulty"),
        "category": record.get("category"),
        "estimatedTime": record.get("estimated_time", record.get("estimatedTime")),
        "requirements": legacy_text("requirements"),
        "constraints": legacy_text("constraints"),
        "requirementSpec": spec,
        "requirementRevision": revision,
    })
    return request.model_copy(update={"problem": approved_problem})


@router.post(
    "/assess",
    responses={
        400: {"description": "The assessment request contains no components."},
        409: {"description": "The requested problem requirement revision is unavailable."},
        503: {"description": "The approved catalog brief could not be resolved."},
        500: {"description": "The assessment service failed."},
    },
)
async def assess_system_design(
    request: AssessmentRequest,
    assessor: Annotated[AIAssessorService, Depends(get_assessor_service)],
    problem_lookup: Annotated[ProblemLookup, Depends(get_problem_lookup)],
) -> AssessmentResponse:
    """
    Assess a system design solution using AI-powered analysis.

    Returns detailed feedback on scalability, reliability, security, and maintainability.
    """
    try:
        # Validate input
        if not request.components:
            raise HTTPException(
                status_code=400,
                detail="At least one component is required for assessment",
            )

        # Generate assessment ID
        assessment_id = str(uuid.uuid4())

        # Resolve catalog scope off the event loop, keeping learner evidence intact.
        resolved_request = await resolve_problem_context(request, problem_lookup)
        result = await assessor.assess_design(resolved_request)
        result.assessment_id = assessment_id

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Assessment failed: {str(e)}"
        ) from e


@router.post(
    "/simulation/prepare",
    response_model=SimulationPreparationResponse,
    responses={
        422: {"description": "The diagram could not be safely prepared."},
        503: {"description": "AI preparation is temporarily unavailable."},
    },
)
async def prepare_simulation(
    request: SimulationPreparationRequest,
    preparer: Annotated[
        SimulationPreparationService,
        Depends(get_simulation_preparation_service),
    ],
) -> SimulationPreparationResponse:
    """Interpret a diagram for the supported educational simulation model."""
    try:
        return await preparer.prepare(request)
    except SimulationPreparationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        logger.exception("Unexpected simulation preparation failure")
        raise HTTPException(
            status_code=503,
            detail="AI preparation is temporarily unavailable. No simulation metrics were produced.",
        ) from error


@router.get("/health")
async def assessment_health():
    """Health check endpoint for the assessment router."""
    return {"status": "healthy", "service": "assessment"}
