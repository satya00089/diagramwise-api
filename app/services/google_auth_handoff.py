"""Short-lived, single-use handoffs for browser redirect authentication."""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any, Protocol

from redis import Redis
from redis.exceptions import RedisError

from app.utils.config import get_settings


HANDOFF_TTL_SECONDS = 60
HANDOFF_PREFIX = "diagramwise:auth:google-handoff:"


class GoogleAuthHandoffStore(Protocol):
    """The small interface needed by the Google redirect adapter."""

    def create(self, payload: dict[str, Any]) -> str | None:
        """Create a short-lived handoff code."""

    def consume(self, code: str) -> dict[str, Any] | None:
        """Atomically consume a handoff code once."""


class RedisGoogleAuthHandoffStore:
    """Redis-backed, one-time storage for redirect authentication results."""

    def __init__(self, redis_client: Redis[str] | None = None) -> None:
        settings = get_settings()
        self._redis = redis_client or (
            Redis.from_url(settings.redis_uri, decode_responses=True)
            if settings.redis_uri
            else None
        )

    @staticmethod
    def _key(code: str) -> str:
        digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
        return f"{HANDOFF_PREFIX}{digest}"

    def create(self, payload: dict[str, Any]) -> str | None:
        if self._redis is None:
            return None

        code = secrets.token_urlsafe(32)
        try:
            stored = self._redis.set(
                self._key(code),
                json.dumps(payload, separators=(",", ":")),
                ex=HANDOFF_TTL_SECONDS,
                nx=True,
            )
            return code if stored else None
        except (RedisError, TypeError, ValueError):
            return None

    def consume(self, code: str) -> dict[str, Any] | None:
        if self._redis is None or not code:
            return None

        # GETDEL is atomic and prevents a redirect code from being replayed.
        try:
            raw = self._redis.getdel(self._key(code))
        except (RedisError, TypeError, ValueError):
            return None
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return value if isinstance(value, dict) else None


google_auth_handoff_store: GoogleAuthHandoffStore = RedisGoogleAuthHandoffStore()
