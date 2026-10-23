"""Router for system design assessment endpoints."""

import uuid
import asyncio
import ipaddress
import logging

from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from starlette.concurrency import run_in_threadpool
from app.models.problem_models import RequirementSpec, problem_slug
from app.models.request_models import AssessmentRequest
from app.models.response_models import AssessmentResponse
from app.models.simulation_models import (
    SimulationAvailabilityResponse,
    SimulationPreparationRequest,
    SimulationPreparationResponse,
    SimulationRunCreate,
    SimulationSavedRunResponse,
)
from app.services.ai_assessor import AIAssessorService
from app.services.dynamodb_service import SimulationRunLimitReached, dynamodb_service
from app.routers.auth import get_current_user
from app.services.simulation_preparation import (
    SimulationPreparationError,
    SimulationPreparationService,
)
from app.services.simulation_protection import (
    SimulationProtectionUnavailable,
    SimulationRateLimitError,
)
from app.utils.config import get_settings

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


async def resolve_simulation_problem(
    request: SimulationPreparationRequest, lookup: ProblemLookup
) -> SimulationPreparationRequest:
    """Bind the simulator to the current, approved URL-shortener brief."""
    record, revision = await resolve_simulation_catalog_record(
        request.problem.id, request.problem.requirement_revision, lookup
    )
    def catalog_text(field: str, limit: int) -> str:
        value = record.get(field) or ""
        return ("\n".join(map(str, value)) if isinstance(value, list) else str(value))[:limit]

    approved_problem = request.problem.model_copy(update={
        "title": catalog_text("title", 240),
        "description": catalog_text("description", 8000),
        "requirements": catalog_text("requirements", 12000),
        "constraints": catalog_text("constraints", 12000),
    })
    return request.model_copy(update={"problem": approved_problem})


async def resolve_simulation_catalog_record(
    problem_id: str, requested_revision: str | None, lookup: ProblemLookup
) -> tuple[dict[str, Any], str | None]:
    """Resolve the approved exercise and reject stale revision snapshots."""
    try:
        record = await asyncio.wait_for(
            run_in_threadpool(lookup, problem_id), timeout=10.0
        )
    except Exception as error:
        logger.warning("Simulation catalog lookup failed error_type=%s", type(error).__name__)
        raise HTTPException(status_code=503, detail="The exercise brief is temporarily unavailable.") from error
    if record is None:
        raise HTTPException(status_code=404, detail="The exercise was not found in the catalog.")
    slug = record.get("slug") or problem_slug(str(record.get("title", "")))
    if slug != "url-shortener-like-bit-ly":
        raise HTTPException(status_code=422, detail="This exercise does not support the URL-shortener simulator.")
    spec_data = record.get("requirementSpec")
    spec = RequirementSpec.model_validate(spec_data) if spec_data is not None else None
    revision = spec.revision if spec else None
    if requested_revision != revision:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "The exercise requirements changed. Reload the brief before continuing.",
                "current_revision": revision,
            },
        )
    return record, revision


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
        429: {"description": "The actor exceeded the AI preparation quota."},
        422: {"description": "The diagram could not be safely prepared."},
        503: {"description": "AI preparation is temporarily unavailable."},
    },
)
async def prepare_simulation(
    request: SimulationPreparationRequest,
    http_request: Request,
    preparer: Annotated[
        SimulationPreparationService,
        Depends(get_simulation_preparation_service),
    ],
    problem_lookup: Annotated[ProblemLookup, Depends(get_problem_lookup)],
) -> SimulationPreparationResponse:
    """Interpret a diagram for the supported educational simulation model."""
    try:
        settings = get_settings()
        if not settings.simulation_capacity_enabled:
            raise HTTPException(
                status_code=503,
                detail="Capacity simulation is temporarily unavailable.",
            )
        resolved = await resolve_simulation_problem(request, problem_lookup)
        prepared = await preparer.prepare(resolved, _simulation_actor(http_request, settings.trusted_proxy_ips))
        return prepared.model_copy(update={
            "exercise_id": resolved.problem.id,
            "requirement_revision": resolved.problem.requirement_revision,
        })
    except HTTPException:
        raise
    except SimulationRateLimitError as error:
        raise HTTPException(
            status_code=429,
            detail=str(error),
            headers={"Retry-After": str(error.retry_after)},
        ) from error
    except SimulationProtectionUnavailable as error:
        raise HTTPException(
            status_code=503,
            detail="AI-assisted path preparation is temporarily unavailable. Try again later.",
        ) from error
    except SimulationPreparationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        logger.exception("Unexpected simulation preparation failure")
        raise HTTPException(
            status_code=503,
            detail="AI preparation is temporarily unavailable. No simulation metrics were produced.",
        ) from error


def _simulation_actor(request: Request, trusted_proxy_ips: list[str]) -> str:
    peer = request.client.host if request.client else "unknown"
    try:
        peer_address = ipaddress.ip_address(peer)
    except ValueError:
        return "ip:unknown"
    trusted = set()
    for address in trusted_proxy_ips:
        try:
            trusted.add(str(ipaddress.ip_address(address)))
        except ValueError:
            continue
    if str(peer_address) not in trusted:
        return f"ip:{peer_address}"

    forwarded = request.headers.get("x-forwarded-for", "")
    try:
        forwarded_addresses = [
            ipaddress.ip_address(address.strip())
            for address in forwarded.split(",")
            if address.strip()
        ]
    except ValueError:
        forwarded_addresses = []
    for address in reversed(forwarded_addresses):
        if str(address) not in trusted:
            return f"ip:{address}"
    return f"ip:{peer_address}"


@router.get("/simulation/status", response_model=SimulationAvailabilityResponse)
async def get_simulation_status() -> SimulationAvailabilityResponse:
    """Report whether the capacity explorer is enabled by its server-side kill switch."""
    settings = get_settings()
    return SimulationAvailabilityResponse(enabled=settings.simulation_capacity_enabled)


@router.post(
    "/simulation/runs",
    response_model=SimulationSavedRunResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"description": "The account has reached its saved-run limit or the exercise revision changed."},
        503: {"description": "Saved-run storage is temporarily unavailable."},
    },
)
async def save_simulation_run(
    request: SimulationRunCreate,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    problem_lookup: Annotated[ProblemLookup, Depends(get_problem_lookup)],
) -> SimulationSavedRunResponse:
    """Save one private, bounded educational estimate for its owner."""
    if not get_settings().simulation_capacity_enabled:
        raise HTTPException(status_code=503, detail="Capacity simulation is temporarily unavailable.")
    await resolve_simulation_catalog_record(
        request.problem_id, request.requirement_revision, problem_lookup
    )
    try:
        saved = await run_in_threadpool(
            dynamodb_service.save_simulation_run,
            current_user["user_id"],
            request.problem_id,
            request.snapshot.model_dump(mode="json", by_alias=True),
        )
    except SimulationRunLimitReached as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception as error:
        logger.exception("Simulation run save failed error_type=%s", type(error).__name__)
        raise HTTPException(status_code=503, detail="The run could not be saved. Try again shortly.") from error
    return SimulationSavedRunResponse(
        runId=saved["runId"],
        createdAt=saved["createdAt"],
        expiresAt=saved["expiresAt"],
        snapshot=request.snapshot,
    )


@router.get("/simulation/runs", response_model=list[SimulationSavedRunResponse])
async def list_simulation_runs(
    problem_id: Annotated[str, Query(alias="problemId", min_length=1, max_length=160)],
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> list[SimulationSavedRunResponse]:
    """List private saved runs, including runs from older exercise revisions."""
    try:
        items = await run_in_threadpool(
            dynamodb_service.get_simulation_runs, current_user["user_id"], problem_id
        )
    except Exception as error:
        logger.exception("Simulation run listing failed error_type=%s", type(error).__name__)
        raise HTTPException(status_code=503, detail="Saved runs are temporarily unavailable.") from error
    return [
        SimulationSavedRunResponse(
            runId=item["runId"],
            createdAt=item["createdAt"],
            expiresAt=int(item["expiresAt"]),
            snapshot=item["snapshot"],
        )
        for item in items
    ]


@router.delete("/simulation/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_simulation_run(
    run_id: str,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> Response:
    """Delete a saved run only from the authenticated user's private partition."""
    if len(run_id) > 64:
        raise HTTPException(status_code=404, detail="Saved run not found.")
    try:
        deleted = await run_in_threadpool(
            dynamodb_service.delete_simulation_run,
            current_user["user_id"],
            run_id,
        )
    except Exception as error:
        logger.exception("Simulation run deletion failed error_type=%s", type(error).__name__)
        raise HTTPException(status_code=503, detail="The saved run could not be deleted. Try again shortly.") from error
    if not deleted:
        raise HTTPException(status_code=404, detail="Saved run not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/health")
async def assessment_health():
    """Health check endpoint for the assessment router."""
    return {"status": "healthy", "service": "assessment"}
