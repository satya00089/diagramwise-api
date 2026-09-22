"""Authentication related Pydantic models."""

from typing import Any, Dict, List, Optional, cast
from pydantic import BaseModel, EmailStr, Field, field_validator


class SignupRequest(BaseModel):
    """Request model for user signup."""

    email: EmailStr
    password: str = Field(..., min_length=6)
    name: Optional[str] = None
    verificationReturnUrl: Optional[str] = None


class LoginRequest(BaseModel):
    """Request model for user login."""

    email: EmailStr
    password: str


class GoogleAuthRequest(BaseModel):
    """Request model for Google OAuth authentication."""

    credential: str


class VerifyEmailRequest(BaseModel):
    """A token received from an email activation link."""

    userId: str
    token: str = Field(..., min_length=20, max_length=512)


class ResendVerificationRequest(BaseModel):
    """Request a replacement activation email."""

    email: EmailStr


class UserResponse(BaseModel):
    """Response model for user data."""

    id: str
    email: str
    name: Optional[str] = None
    picture: Optional[str] = None
    preferences: Optional[Dict[str, Any]] = None
    emailVerified: bool = False
    createdAt: str

    class Config:
        """Pydantic config."""

        from_attributes = True


class AuthResponse(BaseModel):
    """Response model for authentication (login/signup)."""

    user: UserResponse
    token: str


class SignupPendingResponse(BaseModel):
    """Response returned after a password signup awaits email activation."""

    message: str
    email: str


class User(BaseModel):
    """Internal user model."""

    id: str
    email: str
    passwordHash: Optional[str] = None  # Optional for Google users
    name: Optional[str] = None
    picture: Optional[str] = None
    googleId: Optional[str] = None
    preferences: Optional[Dict[str, Any]] = None
    emailVerified: bool = False
    verificationTokenHash: Optional[str] = None
    verificationExpiresAt: Optional[str] = None
    verificationSentAt: Optional[str] = None
    verificationVersion: int = 0
    createdAt: str
    updatedAt: str


class UserPreferences(BaseModel):
    """User preference fields used for personalization (optional)."""

    role: Optional[str] = None
    experience_level: Optional[str] = None
    primary_interest: Optional[List[str]] = None
    preferred_cloud: Optional[str] = None
    learning_goals: Optional[str] = None
    preferred_content_type: Optional[str] = None
    timezone: Optional[str] = None

    @field_validator("primary_interest", mode="before")
    def _coerce_primary_interest(cls, v: Any):
        """Accept a string, comma-separated string, dict or list and coerce to list[str].

        - None or empty string -> None (field omitted on update)
        - list -> convert all items to str
        - string -> split on commas if present, otherwise wrap in single-item list
        - dict -> try common keys (`value`, `label`, `id`, `name`) then stringify
        """
        if v is None:
            return None
        if isinstance(v, list):
            return [str(item) for item in cast(List[Any], v) if item is not None]
        if isinstance(v, str):
            return cls._coerce_interest_string(v)
        if isinstance(v, dict):
            return cls._coerce_interest_mapping(cast(Dict[str, Any], v))
        return [str(v)]

    @staticmethod
    def _coerce_interest_string(value: str) -> Optional[List[str]]:
        stripped = value.strip()
        if not stripped:
            return None
        if "," in stripped:
            return [part.strip() for part in stripped.split(",") if part.strip()]
        return [stripped]

    @staticmethod
    def _coerce_interest_mapping(values: Dict[str, Any]) -> List[str]:
        for key in ("value", "label", "id", "name"):
            value = values.get(key)
            if isinstance(value, str) and value.strip():
                return [value.strip()]
        return [str(values)]
