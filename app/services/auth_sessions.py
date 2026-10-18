"""Server-side lifecycle and revocation checks for access-token sessions."""

from datetime import datetime, timezone
import hashlib
from typing import Any, Dict

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, status

from app.services.auth_service import auth_service
from app.services.dynamodb_service import dynamodb_service


def _legacy_key(token: str) -> str:
    """Use a non-reversible key for pre-session JWTs during rollout."""
    return f"legacy:{hashlib.sha256(token.encode('utf-8')).hexdigest()}"


class AuthSessionService:
    """Persist and validate the revocation state of signed access tokens."""

    def __init__(self, table: Any):
        self.table = table

    @staticmethod
    def _unavailable() -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is temporarily unavailable",
        )

    def register(self, payload: Dict[str, Any]) -> None:
        """Persist a freshly issued token before it is returned to a client."""
        jti = payload.get("jti")
        exp = payload.get("exp")
        user_id = payload.get("user_id")
        if not isinstance(jti, str) or not jti or not user_id or not exp:
            raise HTTPException(status_code=500, detail="Invalid session token")
        try:
            self.table.put_item(
                Item={
                    "jti": jti,
                    "userId": str(user_id),
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "expiresAt": int(exp),
                },
                ConditionExpression="attribute_not_exists(jti)",
            )
        except (BotoCoreError, ClientError) as exc:
            raise self._unavailable() from exc

    def validate(self, token: str) -> Dict[str, Any]:
        """Decode a JWT and require its corresponding session to be active."""
        payload = auth_service.decode_token(token)
        jti = payload.get("jti")
        user_id = payload.get("user_id")
        if not isinstance(user_id, str) or not user_id:
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
        has_jti = isinstance(jti, str) and bool(jti)
        key = jti if has_jti else _legacy_key(token)
        try:
            result = self.table.get_item(Key={"jti": key}, ConsistentRead=True)
        except (BotoCoreError, ClientError) as exc:
            raise self._unavailable() from exc
        item = result.get("Item")
        if has_jti:
            if not item or item.get("userId") != user_id or item.get("revokedAt"):
                raise HTTPException(status_code=401, detail="Session is invalid or revoked")
        elif item:
            raise HTTPException(status_code=401, detail="Session is invalid or revoked")
        return payload

    def revoke(self, token: str) -> None:
        """Revoke a session; repeated logout calls are harmless."""
        payload = auth_service.decode_token(token)
        jti = payload.get("jti")
        now = datetime.now(timezone.utc).isoformat()
        try:
            if isinstance(jti, str) and jti:
                result = self.table.get_item(Key={"jti": jti}, ConsistentRead=True)
                item = result.get("Item")
                if (
                    item
                    and item.get("userId") == payload.get("user_id")
                    and not item.get("revokedAt")
                ):
                    self.table.update_item(
                        Key={"jti": jti},
                        UpdateExpression="SET revokedAt = :revokedAt",
                        ExpressionAttributeValues={":revokedAt": now},
                    )
            else:
                exp = payload.get("exp")
                if not exp:
                    return
                self.table.put_item(
                    Item={
                        "jti": _legacy_key(token),
                        "userId": str(payload.get("user_id", "")),
                        "createdAt": now,
                        "revokedAt": now,
                        "expiresAt": int(exp),
                    }
                )
        except (BotoCoreError, ClientError) as exc:
            raise self._unavailable() from exc


auth_session_service = AuthSessionService(dynamodb_service.auth_sessions_table)
