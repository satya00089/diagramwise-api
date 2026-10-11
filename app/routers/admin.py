"""Protected super-admin dashboard endpoints."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any, Dict, List, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from starlette.concurrency import run_in_threadpool

from app.models.admin_models import (
    AdminAccessUser,
    AdminApiLatencyReport,
    AdminGoogleAnalyticsReport,
    AdminFeedbackItem,
    AdminOverviewResponse,
    GrantAdminRequest,
    UpdateFeedbackStatusRequest,
)
from app.routers.auth import get_current_user
from app.services.admin_access import (
    SUPER_ADMIN_ROLE,
    is_super_admin_user,
)
from app.services.dynamodb_service import dynamodb_service
from app.services.google_analytics_service import get_google_analytics_report
from app.services.s3_analytics_aggregator import s3_analytics_aggregator

router = APIRouter()


def require_super_admin(
    current_user: Annotated[Dict[str, Any], Depends(get_current_user)],
):
    user = dynamodb_service.get_user_by_id(current_user["user_id"])
    if not user or not is_super_admin_user(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super-admin access is required",
        )
    return user


def _feedback_item(
    item: Dict[str, Any], user_cache: Dict[str, Any] | None = None
) -> AdminFeedbackItem:
    """Add submitter identity only to this super-admin response."""
    response_item = dict(item)
    user_id = item.get("userId")
    if user_id:
        cache = user_cache if user_cache is not None else {}
        if user_id not in cache:
            try:
                cache[user_id] = dynamodb_service.get_user_by_id(user_id)
            except Exception:
                # Identity is helpful but must not make feedback triage unavailable.
                cache[user_id] = None
        author = cache[user_id]
        if author:
            response_item.update(
                authorName=author.name,
                authorEmail=author.email,
                authorPicture=author.picture,
            )
    return AdminFeedbackItem.model_validate(response_item)


@router.get("/admin/overview", response_model=AdminOverviewResponse)
async def get_admin_overview(
    _admin_user=Depends(require_super_admin),
    days: int = Query(30, ge=7, le=90),
    period: Literal["today", "yesterday"] | None = Query(None),
) -> AdminOverviewResponse:
    to_date = date.today()
    if period == "yesterday":
        to_date -= timedelta(days=1)
    from_date = (
        to_date
        if period is not None
        else to_date - timedelta(days=days - 1)
    )
    feedback = dynamodb_service.list_feedback(limit=250)
    feedback_summary = dynamodb_service.summarize_feedback(feedback)
    user_cache: Dict[str, Any] = {}
    analytics = s3_analytics_aggregator.summarize_date_range(
        from_date.isoformat(), to_date.isoformat()
    )
    return AdminOverviewResponse(
        fromDate=from_date.isoformat(),
        toDate=to_date.isoformat(),
        analytics=analytics,
        feedback=feedback_summary,
        recentFeedback=[_feedback_item(item, user_cache) for item in feedback[:12]],
    )


@router.get(
    "/admin/google-analytics", response_model=AdminGoogleAnalyticsReport
)
async def get_admin_google_analytics(
    _admin_user=Depends(require_super_admin),
    days: int = Query(30, ge=7, le=90),
    period: Literal["today", "yesterday"] | None = Query(None),
) -> AdminGoogleAnalyticsReport:
    report = await run_in_threadpool(
        get_google_analytics_report, days, period=period
    )
    return AdminGoogleAnalyticsReport.model_validate(report)


@router.get("/admin/api-latency", response_model=AdminApiLatencyReport)
async def get_admin_api_latency(
    _admin_user=Depends(require_super_admin),
    days: int = Query(30, ge=7, le=90),
    period: Literal["today", "yesterday"] | None = Query(None),
) -> AdminApiLatencyReport:
    to_date = datetime.now(timezone.utc).date()
    if period == "yesterday":
        to_date -= timedelta(days=1)
    from_date = to_date if period is not None else to_date - timedelta(days=days - 1)
    report = await run_in_threadpool(
        s3_analytics_aggregator.summarize_api_latency,
        from_date.isoformat(),
        to_date.isoformat(),
    )
    return AdminApiLatencyReport.model_validate(report)


@router.get("/admin/access", response_model=List[AdminAccessUser])
async def list_admin_access(admin_user=Depends(require_super_admin)):
    users = dynamodb_service.list_users_with_role(SUPER_ADMIN_ROLE)
    if all(user.id != admin_user.id for user in users):
        users.append(admin_user)
    return [
        AdminAccessUser(
            id=user.id,
            email=user.email,
            name=user.name,
            roles=user.roles,
        )
        for user in users
    ]


@router.post("/admin/access", response_model=AdminAccessUser)
async def grant_admin_access(
    request: GrantAdminRequest,
    _admin_user=Depends(require_super_admin),
):
    user = dynamodb_service.get_user_by_email(request.email.strip().lower())
    if not user or not user.emailVerified and not user.googleId:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No verified Diagramwise account exists for that email",
        )
    roles = sorted(set(user.roles + [SUPER_ADMIN_ROLE]))
    updated = dynamodb_service.update_user_roles(user.id, roles)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update admin access",
        )
    return AdminAccessUser(
        id=updated.id,
        email=updated.email,
        name=updated.name,
        roles=updated.roles,
    )


@router.delete("/admin/access/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_admin_access(
    user_id: str,
    admin_user=Depends(require_super_admin),
):
    if user_id == admin_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot revoke your own super-admin access",
        )
    user = dynamodb_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if len(dynamodb_service.list_users_with_role(SUPER_ADMIN_ROLE)) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one super-admin must remain",
        )
    roles = [role for role in user.roles if role != SUPER_ADMIN_ROLE]
    if not dynamodb_service.update_user_roles(user_id, roles):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update admin access",
        )


@router.patch("/admin/feedback/{feedback_id}", response_model=AdminFeedbackItem)
async def update_feedback_status(
    feedback_id: str,
    request: UpdateFeedbackStatusRequest,
    _admin_user=Depends(require_super_admin),
):
    item = dynamodb_service.update_feedback_status(feedback_id, request.status)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")
    return _feedback_item(item)
