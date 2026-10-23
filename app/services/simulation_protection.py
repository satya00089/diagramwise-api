"""Shared Redis quotas and concurrency controls for simulator AI calls."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from uuid import uuid4

from redis import Redis
from redis.exceptions import RedisError

from app.utils.config import Settings, get_settings

logger = logging.getLogger(__name__)


class SimulationRateLimitError(RuntimeError):
    """The actor exceeded the hourly simulator AI quota."""

    def __init__(self, message: str, retry_after: int = 3600):
        super().__init__(message)
        self.retry_after = max(1, retry_after)


class SimulationProtectionUnavailable(RuntimeError):
    """Shared protection is unavailable, so an AI call cannot safely run."""


_RESERVE_SCRIPT = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    local wait = math.ceil((tonumber(oldest[2]) + 3600000 - tonumber(ARGV[4])) / 1000)
    return -math.max(wait, 1)
end
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', ARGV[1])
if redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[3]) then
    local oldest = redis.call('ZRANGE', KEYS[2], 0, 0, 'WITHSCORES')
    local wait = math.ceil((tonumber(oldest[2]) + 3600000 - tonumber(ARGV[4])) / 1000)
    return -math.max(wait, 1)
end
redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', ARGV[4])
if redis.call('ZCARD', KEYS[3]) >= tonumber(ARGV[5]) then return 0 end
redis.call('ZADD', KEYS[1], ARGV[4], ARGV[7])
redis.call('PEXPIRE', KEYS[1], ARGV[8])
redis.call('ZADD', KEYS[2], ARGV[4], ARGV[7])
redis.call('PEXPIRE', KEYS[2], ARGV[8])
redis.call('ZADD', KEYS[3], ARGV[6], ARGV[7])
redis.call('PEXPIRE', KEYS[3], ARGV[9])
return 1
"""

_RELEASE_SCRIPT = "redis.call('ZREM', KEYS[1], ARGV[1]); return 1"


class SimulationProtection:
    """Fail closed for costly AI preparation unless shared Redis controls work."""

    _prefix = "diagramwise:simulation:{capacity-v1}"
    _lease_milliseconds = 60_000

    def __init__(self, settings: Settings | None = None, redis_client: Redis | None = None):
        self.settings = settings
        self._redis = redis_client
        self._settings_loaded = settings is not None
        self._redis_initialized = redis_client is not None

    def _ensure_configured(self) -> None:
        if not self._settings_loaded:
            self.settings = get_settings()
            self._settings_loaded = True
        assert self.settings is not None
        if self._redis_initialized:
            return
        self._redis_initialized = True
        if not self.settings.redis_uri:
            return
        try:
            self._redis = Redis.from_url(
                self.settings.redis_uri,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
        except (TypeError, ValueError) as error:
            logger.warning(
                "Simulator protection configuration is invalid error_type=%s",
                type(error).__name__,
            )

    async def reserve_ai_call(self, actor: str) -> str:
        self._ensure_configured()
        if self._redis is None:
            raise SimulationProtectionUnavailable("Shared simulator protection is not configured")
        now = int(time.time())
        actor_hash = hashlib.sha256(actor.encode("utf-8")).hexdigest()[:32]
        rate_key = f"{self._prefix}:ai-rate:{actor_hash}"
        global_rate_key = f"{self._prefix}:ai-rate:global"
        concurrency_key = f"{self._prefix}:ai-active"
        token = uuid4().hex
        now_milliseconds = int(time.time() * 1000)
        lease_expiry = now_milliseconds + self._lease_milliseconds
        try:
            result = await asyncio.to_thread(
                self._redis.eval,
                _RESERVE_SCRIPT,
                3,
                rate_key,
                global_rate_key,
                concurrency_key,
                now_milliseconds - 3_600_000,
                self.settings.simulation_ai_requests_per_hour,
                self.settings.simulation_ai_global_requests_per_hour,
                now_milliseconds,
                self.settings.simulation_ai_concurrency,
                lease_expiry,
                token,
                3_600_000,
                self._lease_milliseconds * 2,
            )
        except (RedisError, OSError, TimeoutError) as error:
            logger.warning("Simulator AI protection request failed error_type=%s", type(error).__name__)
            raise SimulationProtectionUnavailable("Shared simulator protection is unavailable") from error
        if int(result) < 0:
            raise SimulationRateLimitError(
                "The hourly AI preparation limit was reached. Try again later.",
                retry_after=-int(result),
            )
        if int(result) == 0:
            raise SimulationProtectionUnavailable("AI preparation is busy. Try again shortly.")
        return token

    async def release_ai_call(self, token: str) -> None:
        if self._redis is None:
            return
        try:
            await asyncio.to_thread(
                self._redis.eval,
                _RELEASE_SCRIPT,
                1,
                f"{self._prefix}:ai-active",
                token,
            )
        except (RedisError, OSError, TimeoutError) as error:
            logger.warning("Simulator AI reservation release failed error_type=%s", type(error).__name__)


simulation_protection = SimulationProtection()


def get_simulation_protection() -> SimulationProtection:
    return simulation_protection
