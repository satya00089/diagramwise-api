"""Optional private history for the browser's event simulator.

Running a simulation does not use this router. Saved replays are user-authored
artifacts and must never be interpreted as verified challenge scores.
"""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from starlette.concurrency import run_in_threadpool

from app.models.event_simulation_models import (
    EventSimulationRunCreate,
    EventSimulationRunResponse,
)
from app.routers.auth import get_current_user
from app.services.dynamodb_service import SimulationRunLimitReached, dynamodb_service
from app.utils.config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)


def _response(item: dict[str, Any]) -> EventSimulationRunResponse:
    return EventSimulationRunResponse(
        runId=item["runId"],
        createdAt=item["createdAt"],
        expiresAt=int(item["expiresAt"]),
        snapshot=item["snapshot"],
    )


@router.post(
    "/simulation/runs",
    response_model=EventSimulationRunResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
)
async def save_event_simulation_run(
    request: EventSimulationRunCreate,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> EventSimulationRunResponse:
    """Save a private replay. The scope is a label, not authorization to a design."""
    if not get_settings().simulation_event_history_enabled:
        raise HTTPException(
            status_code=503,
            detail="Cloud history is temporarily unavailable. Local simulation is still available.",
        )
    try:
        item = await run_in_threadpool(
            dynamodb_service.save_event_simulation_run,
            current_user["user_id"],
            request.snapshot.model_dump(mode="json", by_alias=True, exclude_none=True),
        )
        return _response(item)
    except SimulationRunLimitReached as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception as error:
        # Do not log artifact contents, labels, or traces.
        logger.error("Event history save failed error_type=%s", type(error).__name__)
        raise HTTPException(
            status_code=503,
            detail="Cloud save failed. Your local simulation is unaffected.",
        ) from error


@router.get(
    "/simulation/runs",
    response_model=list[EventSimulationRunResponse],
    response_model_exclude_none=True,
)
async def list_event_simulation_runs(
    design_id: Annotated[str, Query(alias="designId", min_length=1, max_length=200)],
    canvas_id: Annotated[str, Query(alias="canvasId", min_length=1, max_length=200)],
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> list[EventSimulationRunResponse]:
    """History remains readable while new cloud saves are disabled."""
    try:
        items = await run_in_threadpool(
            dynamodb_service.get_event_simulation_runs,
            current_user["user_id"],
            design_id,
            canvas_id,
        )
        return [_response(item) for item in items]
    except Exception as error:
        logger.error("Event history listing failed error_type=%s", type(error).__name__)
        raise HTTPException(status_code=503, detail="Cloud history is temporarily unavailable.") from error


@router.delete("/simulation/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event_simulation_run(
    run_id: str,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> Response:
    if not run_id or len(run_id) > 64:
        raise HTTPException(status_code=404, detail="Saved run not found.")
    try:
        deleted = await run_in_threadpool(
            dynamodb_service.delete_simulation_run,
            current_user["user_id"],
            run_id,
            "event-v1",
        )
    except Exception as error:
        logger.error("Event history deletion failed error_type=%s", type(error).__name__)
        raise HTTPException(status_code=503, detail="The saved run could not be deleted.") from error
    if not deleted:
        raise HTTPException(status_code=404, detail="Saved run not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
