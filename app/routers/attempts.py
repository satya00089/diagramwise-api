"""Router for problem attempt tracking."""

from typing import Annotated, Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status

from app.models.attempt_models import (
    AttemptCreate,
    AttemptResponse,
)
from app.services.dynamodb_service import dynamodb_service
from app.routers.auth import get_current_user

router = APIRouter()


@router.post("/attempts", status_code=status.HTTP_201_CREATED)
async def create_or_update_attempt(
    request: AttemptCreate,
    current_user: Annotated[Dict[str, Any], Depends(get_current_user)],
) -> AttemptResponse:
    """Create or update a problem attempt (requires authentication)."""
    user_id = current_user["user_id"]

    try:
        attempt = dynamodb_service.create_or_update_attempt(
            user_id=user_id,
            request=request,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return attempt


@router.get("/attempts")
async def get_attempts(
    current_user: Annotated[Dict[str, Any], Depends(get_current_user)],
) -> List[AttemptResponse]:
    """Get all problem attempts for the authenticated user."""
    user_id = current_user["user_id"]
    attempts = dynamodb_service.get_user_attempts(user_id)
    return attempts


@router.get("/attempts/problem/{problem_id}")
async def get_attempt_by_problem(
    problem_id: str,
    current_user: Annotated[Dict[str, Any], Depends(get_current_user)],
) -> AttemptResponse:
    """Get user's attempt for a specific problem."""
    user_id = current_user["user_id"]
    attempt = dynamodb_service.get_attempt_by_problem(user_id, problem_id)

    if not attempt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No attempt found for this problem",
        )

    return attempt


@router.delete("/attempts/problem/{problem_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attempt(
    problem_id: str,
    current_user: Annotated[Dict[str, Any], Depends(get_current_user)],
) -> None:
    """Delete a problem attempt."""
    user_id = current_user["user_id"]

    success = dynamodb_service.delete_attempt(user_id, problem_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete attempt",
        )

    return None
