"""Pydantic models for user-submitted product feedback."""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class FeedbackSource(str, Enum):
    """Where the feedback was requested."""

    GLOBAL = "global"
    ASSESSMENT = "assessment"


class FeedbackCategory(str, Enum):
    """User-facing categories used to triage feedback."""

    BUG = "bug"
    FEATURE_REQUEST = "feature_request"
    USABILITY = "usability"
    CONTENT = "content"
    ASSESSMENT = "assessment"
    OTHER = "other"


class FeedbackReason(str, Enum):
    """Optional reasons for negative assessment-review feedback."""

    INACCURATE = "inaccurate"
    TOO_GENERIC = "too_generic"
    NOT_ACTIONABLE = "not_actionable"
    MISSING_CONTEXT = "missing_context"
    HARD_TO_UNDERSTAND = "hard_to_understand"
    OTHER = "other"


class FeedbackContext(BaseModel):
    """Whitelisted product identifiers attached to contextual feedback."""

    problemId: Optional[str] = Field(default=None, max_length=128)
    assessmentId: Optional[str] = Field(default=None, max_length=128)
    traceId: Optional[str] = Field(
        default=None,
        pattern=r"^[0-9a-f]{32}$",
        description="Langfuse trace ID associated with the reviewed output",
    )
    diagramId: Optional[str] = Field(default=None, max_length=128)
    lessonId: Optional[str] = Field(default=None, max_length=128)


class FeedbackCreate(BaseModel):
    """Validated payload accepted from the browser."""

    source: FeedbackSource = FeedbackSource.GLOBAL
    category: FeedbackCategory = FeedbackCategory.OTHER
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    helpful: Optional[bool] = None
    reasons: List[FeedbackReason] = Field(default_factory=list, max_length=5)
    message: str = Field(default="", max_length=4000)
    contactEmail: Optional[EmailStr] = None
    route: Optional[str] = Field(default=None, max_length=200)
    appVersion: Optional[str] = Field(default=None, max_length=64)
    context: FeedbackContext = Field(default_factory=FeedbackContext)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        return value.strip()

    @field_validator("route", "appVersion")
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value else None

    @model_validator(mode="after")
    def require_feedback_signal(self) -> "FeedbackCreate":
        if not self.message and self.rating is None and self.helpful is None:
            raise ValueError(
                "Feedback must include a rating, helpfulness signal, or message"
            )
        return self


class FeedbackResponse(BaseModel):
    """Minimal response returned after a feedback item is persisted."""

    id: str
    createdAt: str
    message: str = "Thanks for helping us improve Diagramwise."
