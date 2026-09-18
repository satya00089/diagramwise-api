"""Diagrams router for CRUD operations on diagrams."""

import base64
import binascii
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models.diagram_models import (
    DiagramCreate,
    Diagram,
    DiagramUpdate,
    DiagramResponse,
    DiagramSummaryResponse,
    DiagramPage,
    ShareRequest,
    ShareResponse,
    Collaborator,
    Permission,
)
from app.services.dynamodb_service import dynamodb_service
from app.services.validation import validate_diagram_access, validate_collaborator_limit
from app.routers.auth import get_current_user

router = APIRouter()

# Constants
DIAGRAM_NOT_FOUND = "Diagram not found"
DIAGRAM_PAGE_SIZE = 24
DIAGRAM_PAGE_MAX_SIZE = 100


def _encode_diagram_cursor(state: Dict[str, Any]) -> str:
    """Encode DynamoDB continuation keys as an opaque URL-safe cursor."""
    payload = json.dumps(state, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_diagram_cursor(cursor: Optional[str]) -> Dict[str, Any]:
    """Decode and validate a diagram page cursor."""
    if not cursor:
        return {"source": "owned", "owned_cursor": None, "shared_cursor": None}

    try:
        padding = "=" * (-len(cursor) % 4)
        state = json.loads(base64.urlsafe_b64decode(cursor + padding).decode())
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid diagrams cursor",
        ) from exc

    if (
        not isinstance(state, dict)
        or state.get("source") not in {"owned", "shared"}
        or ("owned_cursor" not in state and state.get("source") == "owned")
        or ("shared_cursor" not in state and state.get("source") == "shared")
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid diagrams cursor",
        )
    return state


def enrich_diagram_response(diagram: Diagram, current_user_id: str) -> DiagramResponse:
    """Enrich diagram with ownership and permission information."""
    is_owner = diagram.userId == current_user_id

    # Determine user's permission
    if is_owner:
        permission = "owner"
    else:
        # Find user's permission from collaborators list
        permission = None
        for collab in diagram.collaborators or []:
            if collab.userId == current_user_id:
                permission = collab.permission.value
                break
        if not permission:
            permission = "read"  # Default fallback

    # Get owner information
    owner_info = None
    if diagram.userId:
        owner = dynamodb_service.get_user_by_id(diagram.userId)
        if owner:
            owner_info = {
                "id": owner.id,
                "name": owner.name or "Anonymous",
                "email": owner.email,
                "pictureUrl": owner.picture or None,
            }

    return DiagramResponse(
        id=diagram.id,
        userId=diagram.userId,
        title=diagram.title,
        description=diagram.description,
        nodes=diagram.nodes,
        edges=diagram.edges,
        nodeCount=diagram.nodeCount,
        edgeCount=diagram.edgeCount,
        reasoningContext=diagram.reasoningContext,
        createdAt=diagram.createdAt,
        updatedAt=diagram.updatedAt,
        isPublic=diagram.isPublic,
        publishedAt=diagram.publishedAt,
        viewCount=diagram.viewCount,
        collaborators=diagram.collaborators,
        isOwner=is_owner,
        permission=permission,
        owner=owner_info,
    )


def _owner_info(
    owner_id: str,
    owner_cache: Dict[str, Optional[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    if owner_id not in owner_cache:
        owner = dynamodb_service.get_user_by_id(owner_id)
        owner_cache[owner_id] = (
            {
                "id": owner.id,
                "name": owner.name or "Anonymous",
                "email": owner.email,
                "pictureUrl": owner.picture or None,
            }
            if owner
            else None
        )
    return owner_cache[owner_id]


def enrich_diagram_summary_response(
    diagram: Diagram,
    current_user_id: str,
    owner_cache: Dict[str, Optional[Dict[str, Any]]],
) -> DiagramSummaryResponse:
    """Enrich list metadata without including canvas contents."""
    is_owner = diagram.userId == current_user_id
    permission = "owner"
    if not is_owner:
        permission = next(
            (
                collab.permission.value
                for collab in diagram.collaborators or []
                if collab.userId == current_user_id
            ),
            "read",
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
        nodeCount=diagram.nodeCount,
        edgeCount=diagram.edgeCount,
        isOwner=is_owner,
        permission=permission,
        owner=_owner_info(diagram.userId, owner_cache),
    )


@router.post(
    "/diagrams", response_model=DiagramResponse, status_code=status.HTTP_201_CREATED
)
async def create_diagram(
    request: DiagramCreate, current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Save a new diagram (requires authentication)."""
    user_id = current_user["user_id"]

    diagram = dynamodb_service.create_diagram(
        user_id=user_id,
        title=request.title,
        description=request.description,
        nodes=request.nodes,
        edges=request.edges,
        reasoning_context=(
            request.reasoningContext.model_dump(exclude_none=True)
            if request.reasoningContext
            else None
        ),
    )

    return enrich_diagram_response(diagram, user_id)


@router.get("/diagrams", response_model=DiagramPage)
async def get_diagrams(
    limit: int = Query(
        default=DIAGRAM_PAGE_SIZE,
        ge=1,
        le=DIAGRAM_PAGE_MAX_SIZE,
        description="Maximum number of diagram summaries to return",
    ),
    cursor: Optional[str] = Query(default=None),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> DiagramPage:
    """Get one cursor-paginated page of diagram metadata and counts."""
    user_id = current_user["user_id"]
    page_state = _decode_diagram_cursor(cursor)
    owner_cache: Dict[str, Optional[Dict[str, Any]]] = {}
    page_items: List[Diagram] = []
    next_state: Optional[Dict[str, Any]] = None

    if page_state["source"] == "owned":
        owned_diagrams, owned_cursor = dynamodb_service.get_diagram_summary_page_by_user(
            user_id=user_id,
            limit=limit,
            exclusive_start_key=page_state.get("owned_cursor"),
        )
        page_items.extend(owned_diagrams)

        if owned_cursor:
            next_state = {
                "source": "owned",
                "owned_cursor": owned_cursor,
                "shared_cursor": None,
            }
        elif len(page_items) < limit:
            shared_diagrams, shared_cursor = (
                dynamodb_service.get_shared_diagram_summary_page_for_user(
                    user_id=user_id,
                    limit=limit - len(page_items),
                    exclusive_start_key=page_state.get("shared_cursor"),
                )
            )
            page_items.extend(shared_diagrams)
            if shared_cursor:
                next_state = {
                    "source": "shared",
                    "owned_cursor": None,
                    "shared_cursor": shared_cursor,
                }
    else:
        shared_diagrams, shared_cursor = (
            dynamodb_service.get_shared_diagram_summary_page_for_user(
                user_id=user_id,
                limit=limit,
                exclusive_start_key=page_state.get("shared_cursor"),
            )
        )
        page_items.extend(shared_diagrams)
        if shared_cursor:
            next_state = {
                "source": "shared",
                "owned_cursor": None,
                "shared_cursor": shared_cursor,
            }

    return DiagramPage(
        items=[
            enrich_diagram_summary_response(diagram, user_id, owner_cache)
            for diagram in page_items
        ],
        next_cursor=_encode_diagram_cursor(next_state) if next_state else None,
        has_more=next_state is not None,
    )


@router.get("/diagrams/{diagram_id}", response_model=DiagramResponse)
async def get_diagram(
    diagram_id: str, current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Get a specific diagram (requires authentication and access permission)."""
    user_id = current_user["user_id"]

    # First check if user owns the diagram
    diagram = dynamodb_service.get_diagram(user_id, diagram_id)

    if not diagram:
        # Check if user has collaborator access
        has_access, error_msg = validate_diagram_access(user_id, diagram_id, "read")
        if not has_access:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=error_msg)

        # Find the diagram in shared diagrams
        shared_diagrams = dynamodb_service.get_shared_diagrams_for_user(user_id)
        diagram = next((d for d in shared_diagrams if d.id == diagram_id), None)

        if not diagram:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=DIAGRAM_NOT_FOUND
            )

    return enrich_diagram_response(diagram, user_id)


@router.put("/diagrams/{diagram_id}", response_model=DiagramResponse)
async def update_diagram(
    diagram_id: str,
    request: DiagramUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Update an existing diagram (requires authentication and edit permission)."""
    user_id = current_user["user_id"]

    # Check if user has edit permission
    has_access, error_msg = validate_diagram_access(user_id, diagram_id, "update")
    if not has_access:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=error_msg)

    # Get the diagram (could be owned or shared)
    diagram = dynamodb_service.get_diagram(user_id, diagram_id)
    if not diagram:
        # Find in shared diagrams
        shared_diagrams = dynamodb_service.get_shared_diagrams_for_user(user_id)
        diagram = next((d for d in shared_diagrams if d.id == diagram_id), None)

        if not diagram:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=DIAGRAM_NOT_FOUND
            )

    # Update diagram (only owner can update in DynamoDB)
    updated_diagram = dynamodb_service.update_diagram(
        user_id=diagram.userId,  # Use the actual owner ID
        diagram_id=diagram_id,
        title=request.title,
        description=request.description,
        nodes=request.nodes,
        edges=request.edges,
        reasoning_context=(
            request.reasoningContext.model_dump(exclude_none=True)
            if request.reasoningContext
            else None
        ),
    )

    if not updated_diagram:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update diagram",
        )

    return enrich_diagram_response(updated_diagram, user_id)


@router.delete("/diagrams/{diagram_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_diagram(
    diagram_id: str, current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Delete a diagram (requires authentication and ownership)."""
    # Check if diagram exists and belongs to user
    existing = dynamodb_service.get_diagram(current_user["user_id"], diagram_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=DIAGRAM_NOT_FOUND
        )

    # Delete diagram
    success = dynamodb_service.delete_diagram(current_user["user_id"], diagram_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete diagram",
        )

    return None


# Sharing endpoints
def _validate_share_request(
    diagram_id: str, user_id: str, request: ShareRequest
) -> tuple[Any, Optional[Collaborator]]:
    has_access, error_msg = validate_diagram_access(user_id, diagram_id, "share")
    if not has_access:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=error_msg)

    is_valid, limit_msg = validate_collaborator_limit(diagram_id, user_id)
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=limit_msg)

    if not dynamodb_service.get_diagram(user_id, diagram_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=DIAGRAM_NOT_FOUND)

    share_user = dynamodb_service.get_user_by_email(request.email)
    if not share_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if share_user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot share with yourself"
        )

    collaborators = dynamodb_service.get_diagram_collaborators(diagram_id, user_id)
    existing = next((item for item in collaborators if item.userId == share_user.id), None)
    return share_user, existing


def _create_collaborator(share_user: Any, request: ShareRequest) -> Collaborator:
    return Collaborator(
        userId=share_user.id,
        email=share_user.email,
        name=share_user.name,
        picture=share_user.picture,
        permission=request.permission,
        addedAt=datetime.now(timezone.utc).isoformat(),
    )


def _update_or_create_share(
    diagram_id: str,
    owner_id: str,
    share_user: Any,
    existing: Optional[Collaborator],
    request: ShareRequest,
) -> tuple[str, Optional[Collaborator]]:
    if existing:
        if existing.permission == request.permission:
            return "Diagram already shared with this user", None
        success = dynamodb_service.update_collaborator_permission(
            diagram_id, owner_id, share_user.id, request.permission
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update collaborator permission",
            )
        return "Collaborator permission updated", None

    collaborator = _create_collaborator(share_user, request)
    if not dynamodb_service.share_diagram(diagram_id, owner_id, collaborator):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to share diagram",
        )
    return "Diagram shared successfully", collaborator


@router.post("/diagrams/{diagram_id}/share", response_model=ShareResponse)
async def share_diagram(
    diagram_id: str,
    request: ShareRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Share a diagram with another user."""
    owner_id = current_user["user_id"]
    share_user, existing = _validate_share_request(diagram_id, owner_id, request)
    message, collaborator = _update_or_create_share(
        diagram_id, owner_id, share_user, existing, request
    )

    return ShareResponse(
        success=True,
        message=message,
        collaborator=collaborator,
    )


@router.get("/diagrams/{diagram_id}/collaborators", response_model=List[Collaborator])
async def get_diagram_collaborators(
    diagram_id: str, current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Get all collaborators for a diagram."""
    # Check if diagram exists and belongs to user
    existing = dynamodb_service.get_diagram(current_user["user_id"], diagram_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=DIAGRAM_NOT_FOUND
        )

    collaborators = dynamodb_service.get_diagram_collaborators(
        diagram_id, current_user["user_id"]
    )
    return collaborators


@router.put("/diagrams/{diagram_id}/collaborators/{collaborator_user_id}")
async def update_collaborator_permission(
    diagram_id: str,
    collaborator_user_id: str,
    permission: Permission,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Update a collaborator's permission level."""
    # Check if diagram exists and belongs to user
    existing = dynamodb_service.get_diagram(current_user["user_id"], diagram_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=DIAGRAM_NOT_FOUND
        )

    success = dynamodb_service.update_collaborator_permission(
        diagram_id, current_user["user_id"], collaborator_user_id, permission
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update collaborator permission",
        )

    return {"success": True, "message": "Collaborator permission updated"}


@router.delete("/diagrams/{diagram_id}/collaborators/{collaborator_user_id}")
async def remove_collaborator(
    diagram_id: str,
    collaborator_user_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Remove a collaborator from a diagram."""
    # Check if diagram exists and belongs to user
    existing = dynamodb_service.get_diagram(current_user["user_id"], diagram_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=DIAGRAM_NOT_FOUND
        )

    success = dynamodb_service.remove_collaborator(
        diagram_id, current_user["user_id"], collaborator_user_id
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove collaborator",
        )

    return {"success": True, "message": "Collaborator removed"}


@router.get("/shared-diagrams", response_model=List[DiagramResponse])
async def get_shared_diagrams(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Get all diagrams shared with the current user."""
    user_id = current_user["user_id"]
    diagrams = dynamodb_service.get_shared_diagrams_for_user(user_id)

    return [enrich_diagram_response(diagram, user_id) for diagram in diagrams]
