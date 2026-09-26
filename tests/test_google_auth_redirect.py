import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.models.auth_models import AuthResponse, UserResponse
from app.routers import auth


class FakeHandoffStore:
    def __init__(self):
        self.payload = None

    def create(self, payload):
        self.payload = payload
        return "handoff-code-12345678901234567890"

    def consume(self, code):
        if code != "handoff-code-12345678901234567890":
            return None
        return self.payload


def request_with_cookie(value: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/google/redirect",
            "headers": [(b"cookie", f"g_csrf_token={value}".encode())],
        }
    )


def auth_response() -> AuthResponse:
    return AuthResponse(
        user=UserResponse(
            id="user-1",
            email="person@gmail.com",
            name="Person",
            emailVerified=True,
            createdAt="2026-01-01T00:00:00+00:00",
        ),
        token="jwt-token",
    )


@pytest.mark.asyncio
async def test_google_redirect_requires_google_double_submit_cookie():
    with pytest.raises(HTTPException) as error:
        await auth.google_auth_redirect(
            request_with_cookie("cookie-token"),
            credential="credential",
            csrf_token="different-token",
        )

    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_google_redirect_creates_handoff_and_redirects(monkeypatch):
    store = FakeHandoffStore()
    monkeypatch.setattr(auth, "google_auth_handoff_store", store)
    monkeypatch.setattr(auth, "_authenticate_google_credential", lambda _: auth_response())

    response = await auth.google_auth_redirect(
        request_with_cookie("csrf-token"),
        credential="credential",
        csrf_token="csrf-token",
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith(
        "/auth/callback?code=handoff-code-12345678901234567890"
    )
    assert store.payload["token"] == "jwt-token"


@pytest.mark.asyncio
async def test_google_handoff_exchange_returns_auth_response(monkeypatch):
    store = FakeHandoffStore()
    store.payload = auth_response().model_dump(mode="json")
    monkeypatch.setattr(auth, "google_auth_handoff_store", store)

    response = await auth.exchange_google_auth_handoff(
        auth.GoogleAuthHandoffRequest(code="handoff-code-12345678901234567890")
    )

    assert response.token == "jwt-token"
    assert response.user.email == "person@gmail.com"
