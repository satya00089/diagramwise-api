"""Authentication router for signup, login, and Google OAuth."""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import secrets
from typing import Annotated, Any, Dict
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.responses import RedirectResponse

from app.models.auth_models import (
    SignupRequest,
    LoginRequest,
    GoogleAuthRequest,
    GoogleAuthHandoffRequest,
    AuthResponse,
    SignupPendingResponse,
    VerifyEmailRequest,
    ResendVerificationRequest,
    UserResponse,
    UserPreferences,
)
from app.services.auth_service import auth_service
from app.services.dynamodb_service import dynamodb_service
from app.services.email_service import email_service, EmailDeliveryError
from app.services.google_auth_handoff import google_auth_handoff_store
from app.utils.config import get_settings

router = APIRouter()
security = HTTPBearer()
settings = get_settings()


def _is_email_verified(user: Any) -> bool:
    """Google identity tokens assert a verified mailbox, including legacy users."""
    return bool(getattr(user, "emailVerified", False) or getattr(user, "googleId", None))


def _hash_verification_token(token: str) -> str:
    secret = settings.email_verification_secret or settings.jwt_secret_key
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def _verification_resend_available(user: Any) -> bool:
    sent_at = getattr(user, "verificationSentAt", None)
    if not sent_at:
        return True
    try:
        last_sent = datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    return datetime.now(timezone.utc) >= last_sent + timedelta(
        seconds=settings.email_verification_resend_cooldown_seconds
    )


def _safe_verification_return_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    allowed_issuer = os.getenv("MCP_OAUTH_ISSUER", "https://mcp.diagramwise.com").rstrip("/")
    issuer = urlparse(allowed_issuer)
    if parsed.scheme != issuer.scheme or parsed.netloc != issuer.netloc or parsed.path != "/oauth/continue":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification continuation")
    if not parsed.query or parsed.fragment:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification continuation")
    return value


async def _issue_verification_email(user: Any, verification_return_url: str | None = None) -> None:
    """Persist a new token before delivery, so any older link is immediately invalid."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.email_verification_expire_minutes)
    token_hash = _hash_verification_token(token)
    saved = dynamodb_service.save_email_verification_token(
        user.id, token_hash, expires_at.isoformat(), now.isoformat()
    )
    if not saved:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to create activation link")
    try:
        if verification_return_url:
            await email_service.send_verification_email(
                user.email,
                user.id,
                token,
                verification_return_url=verification_return_url,
            )
        else:
            await email_service.send_verification_email(user.email, user.id, token)
    except EmailDeliveryError as exc:
        dynamodb_service.restore_email_verification_state(user, token_hash)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="We could not send the activation email. Please try again shortly.",
        ) from exc


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> Dict[str, Any]:
    """Dependency to get current authenticated user from JWT token."""
    token = credentials.credentials
    payload = auth_service.decode_token(token)
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )
    user = dynamodb_service.get_user_by_id(user_id)
    if not user or not _is_email_verified(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email address before continuing",
        )
    return payload


@router.post("/auth/signup", response_model=SignupPendingResponse)
async def signup(request: SignupRequest):
    """Register a new user with email and password."""
    verification_return_url = _safe_verification_return_url(request.verificationReturnUrl)
    # bcrypt only accepts up to 72 bytes; reject longer passwords early so we
    # return a clean client-facing error instead of a 500 from the hash layer.
    if len(request.password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is too long. Please use 72 bytes or fewer.",
        )

    # Check if user already exists
    existing_user = dynamodb_service.get_user_by_email(request.email)
    if existing_user:
        if not _is_email_verified(existing_user):
            if not _verification_resend_available(existing_user):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Please wait a minute before requesting another activation email.",
                )
            await _issue_verification_email(existing_user, verification_return_url)
            return SignupPendingResponse(
                message="Check your inbox to activate your account.", email=existing_user.email
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Hash password
    password_hash = auth_service.hash_password(request.password)

    # Create user
    user = dynamodb_service.create_user(
        email=request.email, password_hash=password_hash, name=request.name
    )
    await _issue_verification_email(user, verification_return_url)
    return SignupPendingResponse(
        message="Check your inbox to activate your account.", email=user.email
    )


@router.post("/auth/verify-email", response_model=SignupPendingResponse)
async def verify_email(request: VerifyEmailRequest):
    """Activate a password account using its single-use, expiring token."""
    user = dynamodb_service.get_user_by_id(request.userId)
    if not user or not user.verificationTokenHash or not user.verificationExpiresAt:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This activation link is invalid or has already been used.")
    try:
        expires_at = datetime.fromisoformat(user.verificationExpiresAt.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This activation link is invalid.")
    if expires_at <= datetime.now(timezone.utc) or not hmac.compare_digest(
        user.verificationTokenHash, _hash_verification_token(request.token)
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This activation link is invalid or has expired.")
    verified = dynamodb_service.mark_email_verified(
        user.id, expected_token_hash=user.verificationTokenHash
    )
    if not verified:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to activate account")
    return SignupPendingResponse(message="Your email has been verified. You can now sign in.", email=verified.email)


@router.post("/auth/resend-verification", response_model=SignupPendingResponse)
async def resend_verification(request: ResendVerificationRequest):
    """Send a replacement link without revealing whether an account exists."""
    generic = SignupPendingResponse(
        message="If an unverified account exists, an activation email has been sent.", email=request.email
    )
    user = dynamodb_service.get_user_by_email(request.email)
    if user and not _is_email_verified(user):
        if not _verification_resend_available(user):
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Please wait a minute before requesting another activation email.")
        await _issue_verification_email(user)
    return generic


@router.post("/auth/login", response_model=AuthResponse)
async def login(request: LoginRequest):
    """Authenticate user and get JWT token."""
    # Keep login aligned with signup and prevent bcrypt from receiving a
    # password it cannot process.  This must run before verification so an
    # invalid oversized password returns a client error rather than a 500.
    if len(request.password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is too long. Please use 72 bytes or fewer.",
        )

    # Get user by email
    user = dynamodb_service.get_user_by_email(request.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Verify password
    if not user.passwordHash or not auth_service.verify_password(
        request.password, user.passwordHash
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not _is_email_verified(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please activate your account using the link sent to your email.",
        )

    # Create JWT token
    token = auth_service.create_access_token(
        data={"user_id": user.id, "email": user.email}
    )

    return AuthResponse(
        user=UserResponse(
            id=user.id,
            email=user.email,
            name=user.name,
            picture=user.picture,
            emailVerified=_is_email_verified(user),
            createdAt=user.createdAt,
        ),
        token=token,
    )


def _authenticate_google_credential(credential: str) -> AuthResponse:
    """Resolve one verified Google credential into a Diagramwise session."""
    # Verify Google credential
    google_info = auth_service.verify_google_token(credential)

    # Check if user exists by Google ID
    user = dynamodb_service.get_user_by_google_id(google_info["google_id"])

    if not user:
        # Check if user exists by email
        user = dynamodb_service.get_user_by_email(google_info["email"])

        if user and not user.googleId:
            if not auth_service.is_google_email_authoritative(google_info):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This email is already registered. Sign in with email and password instead.",
                )
            # User exists by email but no Google ID - update the existing user
            updated_user = dynamodb_service.update_user_google_id(
                user.id, google_info["google_id"], google_info.get("picture")
            )
            if updated_user:
                user = updated_user
        elif not user:
            # Create new user (create_user now handles duplicate prevention)
            user = dynamodb_service.create_user(
                email=google_info["email"],
                name=google_info["name"],
                picture=google_info.get("picture"),
                google_id=google_info["google_id"],
                email_verified=True,
            )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create or retrieve user",
        )

    if not _is_email_verified(user):
        # A valid Google identity token proves control of the Google mailbox.
        user = dynamodb_service.mark_email_verified(user.id) or user

    # Create JWT token
    token = auth_service.create_access_token(
        data={"user_id": user.id, "email": user.email}
    )

    return AuthResponse(
        user=UserResponse(
            id=user.id,
            email=user.email,
            name=user.name,
            picture=user.picture,
            emailVerified=_is_email_verified(user),
            createdAt=user.createdAt,
        ),
        token=token,
    )


@router.post("/auth/google", response_model=AuthResponse)
async def google_auth(request: GoogleAuthRequest):
    """Authenticate user with Google Sign-In credential."""
    return _authenticate_google_credential(request.credential)


@router.post("/auth/google/redirect")
async def google_auth_redirect(
    request: Request,
    credential: Annotated[str, Form(...)],
    csrf_token: Annotated[str | None, Form(alias="g_csrf_token")] = None,
):
    """Receive Google's redirect credential and return a one-time handoff."""
    # Google Identity Services uses a double-submit cookie for its redirect
    # POST. Rejecting a missing/mismatched pair keeps this endpoint from being
    # a credential injection surface.
    cookie_token = request.cookies.get("g_csrf_token")
    if not csrf_token or not cookie_token or not hmac.compare_digest(
        csrf_token, cookie_token
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Google authentication request",
        )

    auth_response = _authenticate_google_credential(credential)
    handoff_code = google_auth_handoff_store.create(
        auth_response.model_dump(mode="json")
    )
    if not handoff_code:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google authentication handoff is temporarily unavailable",
        )

    frontend_url = settings.frontend_url.rstrip("/")
    callback_url = f"{frontend_url}/auth/callback?code={quote(handoff_code)}"
    return RedirectResponse(url=callback_url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/auth/google/redirect/exchange", response_model=AuthResponse)
async def exchange_google_auth_handoff(request: GoogleAuthHandoffRequest):
    """Consume a redirect handoff and return the normal Diagramwise session."""
    payload = google_auth_handoff_store.consume(request.code)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google authentication link is invalid or expired",
        )
    try:
        return AuthResponse.model_validate(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invalid Google authentication handoff",
        ) from exc


@router.get("/auth/me")
async def get_me(
    current_user: Annotated[Dict[str, Any], Depends(get_current_user)],
) -> UserResponse:
    """Get current user info (requires authentication)."""
    user = dynamodb_service.get_user_by_id(current_user["user_id"])
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        picture=user.picture,
        emailVerified=_is_email_verified(user),
        preferences=getattr(user, "preferences", None),
        createdAt=user.createdAt,
    )


@router.get("/auth/me/preferences")
async def get_my_preferences(
    current_user: Annotated[Dict[str, Any], Depends(get_current_user)],
) -> UserPreferences:
    """Get current authenticated user's preferences."""
    user = dynamodb_service.get_user_by_id(current_user["user_id"])
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    prefs: Dict[str, Any] = getattr(user, "preferences", None) or {}
    return UserPreferences.model_validate(prefs)


@router.patch("/auth/me/preferences")
async def update_my_preferences(
    prefs: UserPreferences,
    current_user: Annotated[Dict[str, Any], Depends(get_current_user)],
) -> UserPreferences:
    """Update preferences for the current authenticated user."""
    updated = dynamodb_service.update_user_preferences(
        current_user["user_id"], prefs.model_dump(exclude_none=True)
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update preferences")
    updated_preferences: Dict[str, Any] = getattr(updated, "preferences", None) or {}
    return UserPreferences.model_validate(updated_preferences)
