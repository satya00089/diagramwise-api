"""Canvas (tab) endpoints for multi-canvas workspaces.

A workspace is a diagram. Its canvases are served under
/diagrams/{diagram_id}/canvases. Pre-multi-canvas diagrams appear as one
canvas whose ID equals the diagram ID.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.models.canvas_models import (
    MAX_CANVASES_PER_WORKSPACE,
    CanvasContentUpdate,
    CanvasCreate,
    CanvasRecord,
    CanvasUpdate,
    CanvasValidationError,
    canvas_summary,
    legacy_canvas_from_diagram,
    primary_canvas,
)
from app.routers.auth import get_current_user
from app.services.canvas_repository import CanvasRepository, CanvasVersionConflict
from app.services.canvas_service import CanvasNotFound, CanvasService
from app.services.dynamodb_service import dynamodb_service
from app.services.validation import validate_diagram_access

router = APIRouter()

WORKSPACE_NOT_FOUND = "Diagram not found"
CANVAS_NOT_FOUND = "Canvas not found"


class CanvasReorderRequest(BaseModel):
    orderedIds: List[str] = Field(..., min_length=1, max_length=MAX_CANVASES_PER_WORKSPACE)


class CanvasListResponse(BaseModel):
    workspaceId: str
    primaryCanvasId: Optional[str]
    maxCanvases: int = MAX_CANVASES_PER_WORKSPACE
    canvases: List[Dict[str, Any]]


def _canvas_service(owner_id: str) -> CanvasService:
    """Built per request. Canvases live under the design owner's partition of the diagrams table."""
    return CanvasService(CanvasRepository(dynamodb_service.diagrams_table, owner_id))


def _load_workspace(user_id: str, diagram_id: str, action: str):
    """Return (diagram, legacy_fallback) after checking the caller's permission."""
    has_access, error_msg = validate_diagram_access(user_id, diagram_id, action)
    if not has_access:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=error_msg)

    diagram = dynamodb_service.get_diagram(user_id, diagram_id)
    if not diagram:
        shared = dynamodb_service.get_shared_diagrams_for_user(user_id)
        diagram = next((d for d in shared if d.id == diagram_id), None)
    if not diagram:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=WORKSPACE_NOT_FOUND)

    legacy = legacy_canvas_from_diagram(
        diagram.id, diagram.nodes, diagram.edges, diagram.createdAt, diagram.updatedAt
    )
    return diagram, legacy


def _map_validation(error: CanvasValidationError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))


@router.get("/diagrams/{diagram_id}/canvases", response_model=CanvasListResponse)
async def list_canvases(
    diagram_id: str, current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = current_user["user_id"]
    diagram, legacy = _load_workspace(user_id, diagram_id, "read")
    canvases = _canvas_service(diagram.userId).list_canvases(diagram_id, legacy)
    primary = primary_canvas(canvases)
    return CanvasListResponse(
        workspaceId=diagram_id,
        primaryCanvasId=primary.id if primary else None,
        canvases=[canvas_summary(c) for c in canvases],
    )


@router.post(
    "/diagrams/{diagram_id}/canvases",
    response_model=CanvasRecord,
    status_code=status.HTTP_201_CREATED,
)
async def create_canvas(
    diagram_id: str,
    request: CanvasCreate,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    user_id = current_user["user_id"]
    diagram, legacy = _load_workspace(user_id, diagram_id, "update")
    try:
        return _canvas_service(diagram.userId).create_canvas(
            diagram_id, request.name, request.kind, legacy
        )
    except CanvasValidationError as error:
        raise _map_validation(error) from error


@router.get("/diagrams/{diagram_id}/canvases/{canvas_id}", response_model=CanvasRecord)
async def get_canvas(
    diagram_id: str,
    canvas_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    user_id = current_user["user_id"]
    diagram, legacy = _load_workspace(user_id, diagram_id, "read")
    try:
        return _canvas_service(diagram.userId).get_canvas(diagram_id, canvas_id, legacy)
    except CanvasNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CANVAS_NOT_FOUND) from error


@router.put("/diagrams/{diagram_id}/canvases/{canvas_id}", response_model=CanvasRecord)
async def save_canvas_content(
    diagram_id: str,
    canvas_id: str,
    request: CanvasContentUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    user_id = current_user["user_id"]
    diagram, legacy = _load_workspace(user_id, diagram_id, "update")
    try:
        service = _canvas_service(diagram.userId)
        saved = service.save_content(
            diagram_id,
            canvas_id,
            request.nodes,
            request.edges,
            request.version,
            legacy if legacy.id == canvas_id else None,
        )
        primary = primary_canvas(service.repository.list_canvases(diagram_id))
        if primary is not None and primary.id == canvas_id:
            # Keep the diagram's own nodes/edges in step so pre-multi-canvas clients read current content.
            dynamodb_service.update_diagram(
                user_id=diagram.userId,
                diagram_id=diagram_id,
                nodes=request.nodes,
                edges=request.edges,
            )
        return saved
    except CanvasValidationError as error:
        raise _map_validation(error) from error
    except CanvasVersionConflict as conflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Canvas was modified elsewhere. Reload before saving again.",
                "currentVersion": conflict.current_version,
            },
        ) from conflict


@router.patch("/diagrams/{diagram_id}/canvases/{canvas_id}", response_model=CanvasRecord)
async def update_canvas(
    diagram_id: str,
    canvas_id: str,
    request: CanvasUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    user_id = current_user["user_id"]
    diagram, legacy = _load_workspace(user_id, diagram_id, "update")
    if request.order is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use the reorder endpoint to change tab order",
        )
    try:
        return _canvas_service(diagram.userId).update_canvas(
            diagram_id,
            canvas_id,
            legacy,
            name=request.name,
            kind=request.kind,
        )
    except CanvasValidationError as error:
        raise _map_validation(error) from error
    except CanvasNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CANVAS_NOT_FOUND) from error


@router.post("/diagrams/{diagram_id}/canvases/reorder", response_model=CanvasListResponse)
async def reorder_canvases(
    diagram_id: str,
    request: CanvasReorderRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    user_id = current_user["user_id"]
    diagram, legacy = _load_workspace(user_id, diagram_id, "update")
    try:
        canvases = _canvas_service(diagram.userId).reorder_canvases(diagram_id, request.orderedIds, legacy)
    except CanvasValidationError as error:
        raise _map_validation(error) from error
    primary = primary_canvas(canvases)
    return CanvasListResponse(
        workspaceId=diagram_id,
        primaryCanvasId=primary.id if primary else None,
        canvases=[canvas_summary(c) for c in canvases],
    )


@router.post(
    "/diagrams/{diagram_id}/canvases/{canvas_id}/duplicate",
    response_model=CanvasRecord,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_canvas(
    diagram_id: str,
    canvas_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    user_id = current_user["user_id"]
    diagram, legacy = _load_workspace(user_id, diagram_id, "update")
    try:
        return _canvas_service(diagram.userId).duplicate_canvas(diagram_id, canvas_id, legacy)
    except CanvasNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CANVAS_NOT_FOUND) from error
    except CanvasValidationError as error:
        raise _map_validation(error) from error


@router.delete(
    "/diagrams/{diagram_id}/canvases/{canvas_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_canvas(
    diagram_id: str,
    canvas_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    user_id = current_user["user_id"]
    diagram, legacy = _load_workspace(user_id, diagram_id, "update")
    try:
        _canvas_service(diagram.userId).delete_canvas(diagram_id, canvas_id, legacy)
    except CanvasNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CANVAS_NOT_FOUND) from error
    except CanvasValidationError as error:
        raise _map_validation(error) from error
