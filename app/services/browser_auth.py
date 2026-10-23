"""Browser session cookie and request-origin helpers."""

from fastapi import HTTPException, Response, status

from app.utils.config import Settings


AUTH_SESSION_COOKIE = "diagramwise_session"


def _cookie_same_site(settings: Settings) -> str:
    """Allow approved cross-site frontends only on Secure deployments."""
    return "none" if settings.auth_cookie_secure else "lax"


def set_auth_session_cookie(response: Response, token: str, settings: Settings) -> None:
    """Set a host-only cookie for the browser session."""
    response.set_cookie(
        key=AUTH_SESSION_COOKIE,
        value=token,
        max_age=settings.jwt_access_token_expire_hours * 60 * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=_cookie_same_site(settings),
        path="/",
    )


def clear_auth_session_cookie(response: Response, settings: Settings) -> None:
    """Expire the browser session cookie using the same attributes as issuance."""
    response.delete_cookie(
        key=AUTH_SESSION_COOKIE,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=_cookie_same_site(settings),
        path="/",
    )


def require_allowed_origin(origin: str | None, settings: Settings) -> None:
    """Reject browser requests outside the explicitly configured CORS origins."""
    if not origin or origin not in settings.allowed_origins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This browser origin is not allowed",
        )
