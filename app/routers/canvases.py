"""Canvas (tab) endpoints for multi-canvas workspaces.

A workspace is a diagram. Its canvases are served under
/diagrams/{diagram_id}/canvases. Pre-multi-canvas diagrams appear as one
canvas whose ID equals the diagram ID.
"""

from datetime import datetime, timezone
import logging
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
from app.models.diagram_models import Diagram, DiagramSummaryResponse
from app.routers.auth import get_current_user
from app.services.canvas_repository import CanvasRepository, CanvasVersionConflict
from app.services.canvas_service import CanvasNotFound, CanvasService
from app.services.dynamodb_service import dynamodb_service
from app.services.validation import validate_diagram_access

router = APIRouter()
logger = logging.getLogger(__name__)

WORKSPACE_NOT_FOUND = "Diagram not found"
CANVAS_NOT_FOUND = "Canvas not found"


class CanvasReorderRequest(BaseModel):
    orderedIds: List[str] = Field(..., min_length=1, max_length=MAX_CANVASES_PER_WORKSPACE)


class CanvasListResponse(BaseModel):
    workspaceId: str
    primaryCanvasId: Optional[str] = None
    maxCanvases: int = MAX_CANVASES_PER_WORKSPACE
    canvases: List[Dict[str, Any]]


class CanvasWorkspaceBootstrapResponse(BaseModel):
    """Design metadata and canvas summaries, deliberately excluding graph data."""

    design: DiagramSummaryResponse
    workspaceId: str
    primaryCanvasId: Optional[str] = None
    maxCanvases: int = MAX_CANVASES_PER_WORKSPACE
    canvases: List[Dict[str, Any]]


def _canvas_service(
    owner_id: str, design_title: str = "Untitled Design"
) -> CanvasService:
    """Built per request. Canvases live under the design owner's partition of the diagrams table."""
    return CanvasService(
        CanvasRepository(dynamodb_service.diagrams_table, owner_id, design_title),
        design_title,
    )


def _load_workspace(user_id: str, diagram_id: str, action: str):
    """Return (diagram, legacy_fallback) after checking the caller's permission."""
    # Owner reads are authorized by the owner-scoped lookup. Validate only shared access.
    diagram = dynamodb_service.get_diagram(user_id, diagram_id)
    if not diagram:
        has_access, error_msg = validate_diagram_access(user_id, diagram_id, action)
        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=error_msg
            )
        shared = dynamodb_service.get_shared_diagrams_for_user(user_id)
        diagram = next((d for d in shared if d.id == diagram_id), None)
    if not diagram:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=WORKSPACE_NOT_FOUND)

    legacy = legacy_canvas_from_diagram(
        diagram.id,
        diagram.nodes,
        diagram.edges,
        diagram.createdAt,
        diagram.updatedAt,
        diagram.title,
    )
    return diagram, legacy


def _map_validation(error: CanvasValidationError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))


def _design_summary(diagram: Diagram, user_id: str) -> DiagramSummaryResponse:
    is_owner = diagram.userId == user_id
    permission = "owner" if is_owner else "read"
    if not is_owner:
        permission = next(
            (
                collaborator.permission.value
                for collaborator in diagram.collaborators or []
                if collaborator.userId == user_id
            ),
            "read",
        )
    owner = dynamodb_service.get_user_by_id(diagram.userId)
    owner_info = (
        {
            "id": owner.id,
            "name": owner.name or "Anonymous",
            "email": owner.email,
            "pictureUrl": owner.picture or None,
        }
        if owner
        else None
    )
    return DiagramSummaryResponse(
        id=diagram.id,
        userId=diagram.userId,
        title=diagram.title,
        description=diagram.description,
        createdAt=diagram.createdAt,
        updatedAt=diagram.updatedAt,
        isPublic=diagram.isPublic,
        publishedAt=diagram.publishedAt,
        viewCount=diagram.viewCount,
        recordType=diagram.recordType,
        familyId=diagram.familyId,
        sourceDiagramId=diagram.sourceDiagramId,
        publicSnapshotId=diagram.publicSnapshotId,
        nodeCount=diagram.nodeCount or len(diagram.nodes),
        edgeCount=diagram.edgeCount or len(diagram.edges),
        isOwner=is_owner,
        permission=permission,
        owner=owner_info,
    )


def _load_attempt_workspace(user_id: str, problem_id: str):
    """Build a user-scoped workspace, using saved attempt content as its first canvas."""
    workspace_id = f"attempt:{problem_id}"
    attempt = dynamodb_service.get_attempt_by_problem(user_id, problem_id)
    now = datetime.now(timezone.utc).isoformat()
    legacy = legacy_canvas_from_diagram(
        workspace_id,
        attempt.nodes if attempt else [],
        attempt.edges if attempt else [],
        attempt.createdAt if attempt else now,
        attempt.updatedAt if attempt else now,
        getattr(attempt, "title", None) or "Problem Attempt",
    )
    return workspace_id, legacy


@router.get(
    "/diagrams/{diagram_id}/workspace",
    response_model=CanvasWorkspaceBootstrapResponse,
)
async def get_diagram_workspace(
    diagram_id: str, current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Load workspace metadata and ordered canvas summaries without graph JSON."""
    user_id = current_user["user_id"]
    diagram, legacy = _load_workspace(user_id, diagram_id, "read")
    canvases = _canvas_service(diagram.userId, legacy.title).list_canvas_summaries(
        diagram_id, legacy
    )
    design_summary = _design_summary(diagram, user_id)
    if canvases:
        design_summary = design_summary.model_copy(
            update={
                "nodeCount": canvases[0]["nodeCount"],
                "edgeCount": canvases[0]["edgeCount"],
            }
        )
    return CanvasWorkspaceBootstrapResponse(
        design=design_summary,
        workspaceId=diagram_id,
        primaryCanvasId=canvases[0]["id"] if canvases else None,
        canvases=canvases,
    )


@router.get("/diagrams/{diagram_id}/canvases", response_model=CanvasListResponse)
async def list_canvases(
    diagram_id: str, current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = current_user["user_id"]
    diagram, legacy = _load_workspace(user_id, diagram_id, "read")
    canvases = _canvas_service(diagram.userId, legacy.title).list_canvas_summaries(
        diagram_id, legacy
    )
    return CanvasListResponse(
        workspaceId=diagram_id,
        primaryCanvasId=canvases[0]["id"] if canvases else None,
        canvases=canvases,
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
        return _canvas_service(diagram.userId, legacy.title).create_canvas(
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
        return _canvas_service(diagram.userId, legacy.title).get_canvas(diagram_id, canvas_id, legacy)
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
        service = _canvas_service(diagram.userId, legacy.title)
        saved = service.save_content(
            diagram_id,
            canvas_id,
            request.nodes,
            request.edges,
            request.version,
            legacy if legacy.id == canvas_id else None,
        )
        primary = primary_canvas(service.repository.list_canvases(diagram_id))
        if primary is not None:
            # Canvas content is canonical; keep only summary counts on the parent.
            if not dynamodb_service.clear_diagram_graph(
                diagram.userId,
                diagram_id,
                len(primary.nodes),
                len(primary.edges),
            ):
                logger.warning(
                    "Canvas was saved, but legacy graph cleanup failed"
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
        return _canvas_service(diagram.userId, legacy.title).update_canvas(
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
        canvases = _canvas_service(diagram.userId, legacy.title).reorder_canvases(diagram_id, request.orderedIds, legacy)
    except CanvasValidationError as error:
        raise _map_validation(error) from error
    primary = primary_canvas(canvases)
    if primary is not None:
        dynamodb_service.clear_diagram_graph(
            diagram.userId, diagram_id, len(primary.nodes), len(primary.edges)
        )
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
        return _canvas_service(diagram.userId, legacy.title).duplicate_canvas(diagram_id, canvas_id, legacy)
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
        service = _canvas_service(diagram.userId, legacy.title)
        service.delete_canvas(diagram_id, canvas_id, legacy)
        primary = primary_canvas(service.repository.list_canvases(diagram_id))
        if primary is not None:
            dynamodb_service.clear_diagram_graph(
                diagram.userId, diagram_id, len(primary.nodes), len(primary.edges)
            )
    except CanvasNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CANVAS_NOT_FOUND) from error
    except CanvasValidationError as error:
        raise _map_validation(error) from error


@router.get("/attempts/problem/{problem_id}/canvases", response_model=CanvasListResponse)
async def list_attempt_canvases(
    problem_id: str, current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = current_user["user_id"]
    workspace_id, legacy = _load_attempt_workspace(user_id, problem_id)
    canvases = _canvas_service(user_id, legacy.title).list_canvases(workspace_id, legacy)
    primary = primary_canvas(canvases)
    return CanvasListResponse(
        workspaceId=workspace_id,
        primaryCanvasId=primary.id if primary else None,
        canvases=[canvas_summary(canvas) for canvas in canvases],
    )


@router.post(
    "/attempts/problem/{problem_id}/canvases",
    response_model=CanvasRecord,
    status_code=status.HTTP_201_CREATED,
)
async def create_attempt_canvas(
    problem_id: str,
    request: CanvasCreate,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    user_id = current_user["user_id"]
    workspace_id, legacy = _load_attempt_workspace(user_id, problem_id)
    try:
        return _canvas_service(user_id, legacy.title).create_canvas(
            workspace_id, request.name, request.kind, legacy
        )
    except CanvasValidationError as error:
        raise _map_validation(error) from error


@router.get(
    "/attempts/problem/{problem_id}/canvases/{canvas_id}",
    response_model=CanvasRecord,
)
async def get_attempt_canvas(
    problem_id: str,
    canvas_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    user_id = current_user["user_id"]
    workspace_id, legacy = _load_attempt_workspace(user_id, problem_id)
    try:
        return _canvas_service(user_id, legacy.title).get_canvas(
            workspace_id, canvas_id, legacy
        )
    except CanvasNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CANVAS_NOT_FOUND
        ) from error


@router.put(
    "/attempts/problem/{problem_id}/canvases/{canvas_id}",
    response_model=CanvasRecord,
)
async def save_attempt_canvas_content(
    problem_id: str,
    canvas_id: str,
    request: CanvasContentUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    user_id = current_user["user_id"]
    workspace_id, legacy = _load_attempt_workspace(user_id, problem_id)
    try:
        return _canvas_service(user_id, legacy.title).save_content(
            workspace_id,
            canvas_id,
            request.nodes,
            request.edges,
            request.version,
            legacy if legacy.id == canvas_id else None,
        )
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


@router.patch(
    "/attempts/problem/{problem_id}/canvases/{canvas_id}",
    response_model=CanvasRecord,
)
async def update_attempt_canvas(
    problem_id: str,
    canvas_id: str,
    request: CanvasUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    user_id = current_user["user_id"]
    workspace_id, legacy = _load_attempt_workspace(user_id, problem_id)
    if request.order is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use the reorder endpoint to change tab order",
        )
    try:
        return _canvas_service(user_id, legacy.title).update_canvas(
            workspace_id,
            canvas_id,
            legacy,
            name=request.name,
            kind=request.kind,
        )
    except CanvasValidationError as error:
        raise _map_validation(error) from error
    except CanvasNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CANVAS_NOT_FOUND
        ) from error


@router.post(
    "/attempts/problem/{problem_id}/canvases/reorder",
    response_model=CanvasListResponse,
)
async def reorder_attempt_canvases(
    problem_id: str,
    request: CanvasReorderRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    user_id = current_user["user_id"]
    workspace_id, legacy = _load_attempt_workspace(user_id, problem_id)
    try:
        canvases = _canvas_service(user_id, legacy.title).reorder_canvases(
            workspace_id, request.orderedIds, legacy
        )
    except CanvasValidationError as error:
        raise _map_validation(error) from error
    primary = primary_canvas(canvases)
    return CanvasListResponse(
        workspaceId=workspace_id,
        primaryCanvasId=primary.id if primary else None,
        canvases=[canvas_summary(canvas) for canvas in canvases],
    )


@router.post(
    "/attempts/problem/{problem_id}/canvases/{canvas_id}/duplicate",
    response_model=CanvasRecord,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_attempt_canvas(
    problem_id: str,
    canvas_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    user_id = current_user["user_id"]
    workspace_id, legacy = _load_attempt_workspace(user_id, problem_id)
    try:
        return _canvas_service(user_id, legacy.title).duplicate_canvas(
            workspace_id, canvas_id, legacy
        )
    except CanvasNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CANVAS_NOT_FOUND
        ) from error
    except CanvasValidationError as error:
        raise _map_validation(error) from error


@router.delete(
    "/attempts/problem/{problem_id}/canvases/{canvas_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_attempt_canvas(
    problem_id: str,
    canvas_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    user_id = current_user["user_id"]
    workspace_id, legacy = _load_attempt_workspace(user_id, problem_id)
    try:
        _canvas_service(user_id, legacy.title).delete_canvas(
            workspace_id, canvas_id, legacy
        )
    except CanvasNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CANVAS_NOT_FOUND
        ) from error
    except CanvasValidationError as error:
        raise _map_validation(error) from error
