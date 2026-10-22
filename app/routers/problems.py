"""API router for problem-related endpoints."""

import base64
import json
import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from app.models.problem_models import ProblemPage, ProblemSummary, ProblemDetail
from app.services.dynamodb_service import dynamodb_service
from app.services.problem_catalog_cache import problem_catalog_count_cache
from app.routers.auth import get_current_user


logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/all-problems")
async def get_all_problems(
    category: Annotated[
        Optional[str], Query(description="Filter by category")
    ] = None,
    difficulty: Annotated[
        Optional[str],
        Query(description="Filter by difficulty (easy/medium/hard/very hard)"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
    cursor: Annotated[Optional[str], Query()] = None,
) -> ProblemPage:
    """
    Get all problems with summary information, sorted from easy to very hard.

    Query Parameters:
        category: Optional filter by category (e.g., 'graphs', 'trees', 'arrays')
        difficulty: Optional filter by difficulty ('easy', 'medium', 'hard', 'very hard')

    Returns:
        One page of problems and an opaque cursor for the next page.
    """
    try:
        # Pagination is currently based on the base table scan. The existing
        # category/difficulty filters are applied to the returned page so the
        # public response remains backward-compatible while the catalog moves
        # away from loading the full table at once.
        start_key = None
        if cursor:
            try:
                start_key = json.loads(
                    base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
                )
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid problems cursor",
                ) from exc

        def load_page() -> Dict[str, Any]:
            problems, next_key = dynamodb_service.get_problems_page(
                limit,
                start_key,
                category=category,
                difficulty=difficulty,
            )

            # Convert DynamoDB items to ProblemSummary models
            problem_list = [ProblemSummary(**problem) for problem in problems]

            # Sort by difficulty: easy -> medium -> hard -> very hard
            difficulty_order = {"easy": 1, "medium": 2, "hard": 3, "very hard": 4}
            problem_list.sort(key=lambda p: difficulty_order.get(p.difficulty.lower(), 5))

            total_count = problem_catalog_count_cache.get_or_load(
                category,
                difficulty,
                dynamodb_service.count_problems,
            )

            next_cursor = None
            if next_key:
                next_cursor = base64.urlsafe_b64encode(
                    json.dumps(next_key, separators=(",", ":")).encode("utf-8")
                ).decode("ascii")

            return ProblemPage(
                items=problem_list,
                next_cursor=next_cursor,
                has_more=next_cursor is not None,
                total_count=total_count,
            ).model_dump(mode="json")

        page_payload = problem_catalog_count_cache.get_page_or_load(
            category,
            difficulty,
            limit,
            cursor,
            load_page,
        )
        if page_payload is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Problem catalog is temporarily unavailable",
            )
        return ProblemPage.model_validate(page_payload)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error in get_all_problems")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch problems from database",
        ) from exc


@router.get("/problem/{problem_id}")
async def get_problem_by_id(problem_id: str) -> ProblemDetail:
    """
    Get a specific problem by ID with full details.

    Args:
        problem_id: The unique identifier of the problem

    Returns:
        Complete problem details including requirements, constraints, and hints.
    """
    try:
        problem = dynamodb_service.get_problem_by_id(problem_id)

        if not problem:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Problem with ID '{problem_id}' not found",
            )

        return ProblemDetail(**problem)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error in get_problem_by_id")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch problem from database",
        ) from exc


@router.get("/problem/slug/{slug}")
async def get_problem_by_slug(slug: str) -> ProblemDetail:
    """Get a specific problem by its public slug."""
    try:
        problem = dynamodb_service.get_problem_by_slug(slug)
        if not problem:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Problem with slug '{slug}' not found",
            )
        return ProblemDetail(**problem)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error in get_problem_by_slug")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch problem from database",
        ) from exc


@router.get("/problems/attempted")
async def get_attempted_problems(
    current_user: Annotated[Dict[str, Any], Depends(get_current_user)],
) -> List[str]:
    """
    Get list of problem IDs that the user has attempted.

    Returns:
        List of problem IDs (strings) that the user has attempted.
    """
    try:
        user_id = current_user["user_id"]
        attempts = dynamodb_service.get_user_attempts(user_id)

        # Extract just the problem IDs
        problem_ids = [attempt.problemId for attempt in attempts]

        return problem_ids
    except Exception as exc:
        logger.exception("Error in get_attempted_problems")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch attempted problems",
        ) from exc


@router.get("/problems/health")
async def problems_health_check() -> Dict[str, str | int]:
    """Health check for problems service and database connection."""
    try:
        dynamodb_service.check_problems_table()
        result: Dict[str, str | int] = {
            "status": "healthy",
            "service": "problems",
            "database": "dynamodb",
            "connection": "connected",
        }
        count = problem_catalog_count_cache.get_cached_count()
        if count is not None:
            result["problem_count"] = count
        return result
    except Exception as exc:
        logger.exception("Error in problems health check")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Problems service is unavailable",
        ) from exc
