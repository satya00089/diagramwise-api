"""API router for learning paths endpoints."""

import json
import logging
from pathlib import Path
from typing import Annotated, Any, Dict, List, cast

from fastapi import APIRouter, Depends, HTTPException, status

from app.routers.auth import get_current_user
from app.services.dynamodb_service import dynamodb_service

logger = logging.getLogger(__name__)
router = APIRouter()

# Determine data directory relative to repo root
# file structure: <repo>/diagrammatic-api/app/routers/learning_paths.py
# repo root is parents[3]
BASE_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = BASE_DIR / "diagrammatic-data" / "learning-paths"
SAMPLE_FILE = DATA_DIR / "learning-paths.json"


def _read_sample() -> Dict[str, Any] | None:
    if not SAMPLE_FILE.exists():
        logger.warning("Learning path sample file not found: %s", SAMPLE_FILE)
        return None
    with SAMPLE_FILE.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return cast(Dict[str, Any], data) if isinstance(data, dict) else None


@router.get(
    "/learning-paths",
    summary="List available learning paths",
    responses={500: {"description": "Learning paths could not be loaded"}},
)
async def list_learning_paths() -> List[Dict[str, Any]]:
    try:
        data = _read_sample()
        if not data:
            return []
        return [data]
    except Exception:
        logger.exception("Error reading learning paths")
        raise HTTPException(status_code=500, detail="Failed to load learning paths")


@router.get(
    "/learning-paths/{slug}",
    summary="Get learning path by slug",
    responses={
        404: {"description": "Learning path not found"},
        500: {"description": "Learning path could not be loaded"},
    },
)
async def get_learning_path(slug: str) -> Dict[str, Any]:
    try:
        data = _read_sample()
        if not data or data.get("slug") != slug:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Learning path not found"
            )
        return data
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error fetching learning path")
        raise HTTPException(status_code=500, detail="Failed to fetch learning path")


@router.get("/learning-paths/{path_id}/progress", summary="Get user progress for a path")
async def get_progress(
    path_id: str,
    current_user: Annotated[Dict[str, Any], Depends(get_current_user)],
):
    """Return the authenticated user's progress for the given learning path.

    Requires a Bearer token in the `Authorization` header. Returns a JSON object
    with `completed` as an array of lesson IDs. If the user has no saved
    progress, an empty array is returned.
    """
    user_id = current_user["user_id"]

    prefs: Dict[str, Any] = dynamodb_service.get_user_preferences(user_id) or {}
    learning_progress = cast(
        Dict[str, List[str]], prefs.get("learningProgress") or {}
    )
    completed = learning_progress.get(path_id, [])
    return {"completed": completed}


@router.post("/learning-paths/{path_id}/progress", summary="Record user progress")
async def post_progress(
    path_id: str,
    payload: Dict[str, Any],
    current_user: Annotated[Dict[str, Any], Depends(get_current_user)],
) -> Dict[str, Any]:
    """Persist the authenticated user's progress for the given learning path.

    Payload should be a JSON object with a `completed` field containing an
    array of lesson IDs. The progress is stored in the user's `preferences`
    under the `learningProgress` key using DynamoDB.
    """
    user_id = current_user["user_id"]

    raw_completed_value = payload.get("completed")
    if not isinstance(raw_completed_value, list):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload: expected { completed: string[] }")
    raw_completed = cast(List[Any], raw_completed_value)
    if not all(isinstance(item, str) for item in raw_completed):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload: expected { completed: string[] }")

    completed: List[str] = cast(List[str], raw_completed)

    # Merge into existing preferences
    prefs: Dict[str, Any] = dynamodb_service.get_user_preferences(user_id) or {}
    learning_progress = cast(
        Dict[str, List[str]], prefs.get("learningProgress", {})
    )
    learning_progress[path_id] = completed

    # Persist preferences back to DynamoDB
    updated = dynamodb_service.update_user_preferences(user_id, {**prefs, "learningProgress": learning_progress})
    if not updated:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to save learning progress")

    return {"status": "ok", "learningProgress": learning_progress}
