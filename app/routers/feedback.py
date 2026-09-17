"""Router for durable product feedback submissions."""

from collections import defaultdict, deque
import time
from typing import Annotated, Any, Deque, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.models.feedback_models import FeedbackCreate, FeedbackResponse
from app.services.auth_service import auth_service
from app.services.dynamodb_service import dynamodb_service
from app.services.llm_client import record_langfuse_feedback

router = APIRouter()
optional_security = HTTPBearer(auto_error=False)

_FEEDBACK_WINDOW_SECONDS = 60 * 60
_FEEDBACK_LIMIT_PER_ACTOR = 5
_submission_history: Dict[str, Deque[float]] = defaultdict(deque)


def get_optional_user(
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(optional_security)
    ],
) -> Optional[Dict[str, Any]]:
    """Read a valid JWT when present without requiring authentication."""
    if not credentials:
        return None

    try:
        payload = auth_service.decode_token(credentials.credentials)
    except Exception:
        # Feedback should remain available when an expired local token is
        # still present in the browser.
        return None

    user_id = payload.get("user_id")
    return {"user_id": user_id} if isinstance(user_id, str) and user_id else None


def _actor_key(request: Request, current_user: Optional[Dict[str, Any]]) -> str:
    if current_user and current_user.get("user_id"):
        return f"user:{current_user['user_id']}"
    client_ip = request.client.host if request.client else "unknown"
    return f"ip:{client_ip}"


def _allow_submission(actor: str) -> bool:
    now = time.time()
    history = _submission_history[actor]
    cutoff = now - _FEEDBACK_WINDOW_SECONDS
    while history and history[0] <= cutoff:
        history.popleft()
    if len(history) >= _FEEDBACK_LIMIT_PER_ACTOR:
        return False
    history.append(now)

    # Keep this process-local guard from growing without bound. The existing
    # API middleware remains the first line of defence for distributed traffic.
    stale_actors = [
        key
        for key, entries in _submission_history.items()
        if not entries or entries[-1] <= cutoff
    ]
    for key in stale_actors:
        _submission_history.pop(key, None)
    return True


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit product feedback",
)
async def submit_feedback(
    feedback: FeedbackCreate,
    request: Request,
    current_user: Optional[Dict[str, Any]] = Depends(get_optional_user),
) -> FeedbackResponse:
    """Persist feedback from an anonymous or authenticated visitor."""
    if not _allow_submission(_actor_key(request, current_user)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You have sent several feedback reports recently. Please try again later.",
        )

    user_id = current_user.get("user_id") if current_user else None
    try:
        saved_feedback = dynamodb_service.create_feedback(
            feedback, user_id=user_id
        )
        record_langfuse_feedback(
            trace_id=feedback.context.traceId,
            helpful=feedback.helpful,
            rating=feedback.rating,
            source=feedback.source.value,
            category=feedback.category.value,
            reasons=[reason.value for reason in feedback.reasons],
            feedback_id=saved_feedback.id,
        )
        return saved_feedback
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Feedback is temporarily unavailable. Please try again shortly.",
        ) from exc
