"""Tests for persisted access-token revocation state."""

from typing import Any, Dict

import pytest
from botocore.exceptions import BotoCoreError
from fastapi import HTTPException

from app.services.auth_sessions import AuthSessionService, _legacy_key
from app.services.auth_service import auth_service


class FakeSessionTable:
    def __init__(self) -> None:
        self.items: Dict[str, Dict[str, Any]] = {}

    def put_item(self, *, Item: Dict[str, Any], **_kwargs: Any) -> None:
        self.items[Item["jti"]] = Item

    def get_item(self, *, Key: Dict[str, str], **_kwargs: Any) -> Dict[str, Any]:
        item = self.items.get(Key["jti"])
        return {"Item": item} if item else {}

    def update_item(self, *, Key: Dict[str, str], **kwargs: Any) -> None:
        self.items[Key["jti"]]["revokedAt"] = kwargs["ExpressionAttributeValues"][":revokedAt"]


@pytest.fixture
def token_decoder(monkeypatch: pytest.MonkeyPatch):
    payload = {"user_id": "user-1", "exp": 2_000_000_000, "jti": "session-1"}
    monkeypatch.setattr(auth_service, "decode_token", lambda _token: payload)
    return payload


def test_registered_session_is_valid_until_revoked(
    token_decoder: Dict[str, Any],
) -> None:
    table = FakeSessionTable()
    service = AuthSessionService(table)
    service.register(token_decoder)

    assert service.validate("jwt")["user_id"] == "user-1"
    service.revoke("jwt")
    with pytest.raises(HTTPException) as error:
        service.validate("jwt")
    assert error.value.status_code == 401


def test_new_access_tokens_have_unique_session_ids() -> None:
    first = auth_service.decode_token(
        auth_service.create_access_token({"user_id": "user-1"})
    )
    second = auth_service.decode_token(
        auth_service.create_access_token({"user_id": "user-1"})
    )

    assert first["jti"]
    assert second["jti"]
    assert first["jti"] != second["jti"]


def test_unknown_session_and_user_mismatch_are_rejected(
    token_decoder: Dict[str, Any],
) -> None:
    service = AuthSessionService(FakeSessionTable())
    with pytest.raises(HTTPException):
        service.validate("jwt")

    service.table.items["session-1"] = {"jti": "session-1", "userId": "other-user"}
    with pytest.raises(HTTPException):
        service.validate("jwt")


def test_legacy_token_is_accepted_until_a_revocation_marker_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_payload = {"user_id": "user-1", "exp": 2_000_000_000}
    monkeypatch.setattr(auth_service, "decode_token", lambda _token: legacy_payload)
    service = AuthSessionService(FakeSessionTable())

    assert service.validate("legacy-jwt")["user_id"] == "user-1"
    service.revoke("legacy-jwt")
    assert "expiresAt" in service.table.items[_legacy_key("legacy-jwt")]
    with pytest.raises(HTTPException):
        service.validate("legacy-jwt")


def test_session_store_failure_fails_closed(
    token_decoder: Dict[str, Any],
) -> None:
    class FailingTable:
        def get_item(self, **_kwargs: Any) -> Dict[str, Any]:
            raise BotoCoreError(error_msg="session store unavailable")

    service = AuthSessionService(FailingTable())
    with pytest.raises(HTTPException) as error:
        service.validate("jwt")

    assert error.value.status_code == 503
