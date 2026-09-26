import pytest
from fastapi import HTTPException
from starlette.requests import Request
from urllib.parse import parse_qs, urlparse

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
async def test_google_oauth_start_uses_top_level_redirect_and_pkce(monkeypatch):
    store = FakeHandoffStore()
    monkeypatch.setattr(auth, "google_auth_handoff_store", store)
    monkeypatch.setattr(auth.settings, "google_client_id", "client-id")
    monkeypatch.setattr(auth.settings, "public_api_url", "https://api.example.com")

    response = await auth.google_auth_redirect_start("/playground/free")

    assert response.status_code == 307
    parsed = urlparse(response.headers["location"])
    query = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.google.com"
    assert query["client_id"] == ["client-id"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [
        "https://api.example.com/api/v1/auth/google/redirect"
    ]
    assert store.payload["return_to"] == "/playground/free"
    assert store.payload["code_verifier"]


@pytest.mark.asyncio
async def test_google_oauth_callback_exchanges_code_and_redirects(monkeypatch):
    store = FakeHandoffStore()
    store.payload = {"code_verifier": "verifier", "return_to": "/"}
    monkeypatch.setattr(auth, "google_auth_handoff_store", store)
    monkeypatch.setattr(auth.settings, "google_client_id", "client-id")
    monkeypatch.setattr(auth.settings, "public_api_url", "https://api.example.com")
    monkeypatch.setattr(auth, "_authenticate_google_credential", lambda _: auth_response())

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id_token": "identity-token"}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, data):
            assert data["code"] == "google-code"
            assert data["code_verifier"] == "verifier"
            return FakeResponse()

    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda timeout: FakeClient())

    response = await auth.google_auth_oauth_callback(
        code="google-code",
        state="handoff-code-12345678901234567890",
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith(
        "/auth/callback?code=handoff-code-12345678901234567890"
    )


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
