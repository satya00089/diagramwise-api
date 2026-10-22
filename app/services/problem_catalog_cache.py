"""Redis cache-aside storage for the public problem catalog count."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Callable, Optional, TypeVar
from urllib.parse import quote

from redis import Redis
from redis.exceptions import RedisError

from app.utils.config import get_settings

logger = logging.getLogger(__name__)

ProblemCountLoader = Callable[[Optional[str], Optional[str]], Optional[int]]
CacheValue = TypeVar("CacheValue")
CacheReader = Callable[[], CacheValue | None]
CacheLoader = Callable[[], CacheValue | None]
CacheWriter = Callable[[CacheValue], None]


class ProblemCatalogCountCache:
    """Cache public catalog pages and counts while keeping DynamoDB authoritative."""

    _key_prefix = "diagrammatic:problem-catalog:count:v1"
    _page_key_prefix = "diagrammatic:problem-catalog:page:v1"
    _ttl_seconds = 24 * 60 * 60
    _lock_ttl_seconds = 60
    _lock_wait_seconds = 5
    _lock_wait_interval_seconds = 0.05

    def __init__(self, redis_client: Redis[str] | None = None) -> None:
        if redis_client is not None:
            self._redis = redis_client
            return

        redis_uri = get_settings().redis_uri
        self._redis = (
            Redis.from_url(redis_uri, decode_responses=True)
            if redis_uri
            else None
        )

    @staticmethod
    def _filter_key(value: Optional[str]) -> str:
        normalized = value.strip() if value else ""
        return quote(normalized, safe="") if normalized else "__any__"

    @classmethod
    def _lock_key(cls, cache_key: str) -> str:
        return f"{cache_key}:lock"

    def _try_acquire_lock(self, cache_key: str, owner: str) -> bool | None:
        if self._redis is None:
            return None
        try:
            return bool(
                self._redis.set(
                    self._lock_key(cache_key),
                    owner,
                    nx=True,
                    ex=self._lock_ttl_seconds,
                )
            )
        except (RedisError, TypeError, ValueError):
            logger.warning("Problem catalog cache lock failed", exc_info=True)
            return None

    def _release_lock(self, cache_key: str, owner: str) -> None:
        if self._redis is None:
            return
        try:
            # Only the process that owns the lock may release it. This avoids
            # deleting a newer lock if the original lock expires mid-load.
            self._redis.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] "
                "then return redis.call('del', KEYS[1]) else return 0 end",
                1,
                self._lock_key(cache_key),
                owner,
            )
        except (RedisError, TypeError, ValueError):
            logger.warning("Problem catalog cache lock release failed", exc_info=True)

    def _cache_aside(
        self,
        cache_key: str,
        reader: CacheReader[CacheValue],
        loader: CacheLoader[CacheValue],
        writer: CacheWriter[CacheValue],
    ) -> CacheValue | None:
        """Load once per key under a Redis lock, with fail-open behavior."""
        if self._redis is None:
            return loader()

        cached = reader()
        if cached is not None:
            return cached

        owner = uuid.uuid4().hex
        acquired = self._try_acquire_lock(cache_key, owner)
        if acquired is None:
            return loader()
        if acquired:
            try:
                # Another worker may have filled the key between the first
                # read and lock acquisition.
                cached = reader()
                if cached is not None:
                    return cached
                value = loader()
                if value is not None:
                    writer(value)
                return value
            finally:
                self._release_lock(cache_key, owner)

        deadline = time.monotonic() + self._lock_wait_seconds
        while time.monotonic() < deadline:
            time.sleep(self._lock_wait_interval_seconds)
            cached = reader()
            if cached is not None:
                return cached

            acquired = self._try_acquire_lock(cache_key, owner)
            if acquired is None:
                return loader()
            if acquired:
                try:
                    cached = reader()
                    if cached is not None:
                        return cached
                    value = loader()
                    if value is not None:
                        writer(value)
                    return value
                finally:
                    self._release_lock(cache_key, owner)

        # Preserve availability if the first loader is slow or failed to
        # populate the cache after the bounded wait.
        return loader()

    @classmethod
    def _key(cls, category: Optional[str], difficulty: Optional[str]) -> str:
        category_key = cls._filter_key(category)
        difficulty_key = cls._filter_key(difficulty)
        return f"{cls._key_prefix}:{category_key}:{difficulty_key}"

    def get_or_load(
        self,
        category: Optional[str],
        difficulty: Optional[str],
        loader: ProblemCountLoader,
    ) -> Optional[int]:
        """Return a cached count or load and cache the authoritative value."""
        key = self._key(category, difficulty)

        def read_count() -> int | None:
            if self._redis is None:
                return None
            try:
                cached = self._redis.get(key)
                if cached is None:
                    return None
                value = int(cached)
                return value if value >= 0 else None
            except (RedisError, TypeError, ValueError):
                logger.warning("Problem catalog count cache read failed", exc_info=True)
                return None

        def load_count() -> int | None:
            count = loader(category, difficulty)
            return count if count is None or count >= 0 else None

        def write_count(count: int) -> None:
            if self._redis is None:
                return
            try:
                self._redis.set(key, str(count), ex=self._ttl_seconds)
            except (RedisError, TypeError, ValueError):
                logger.warning("Problem catalog count cache write failed", exc_info=True)

        return self._cache_aside(key, read_count, load_count, write_count)

    def get_cached_count(
        self, category: Optional[str] = None, difficulty: Optional[str] = None
    ) -> Optional[int]:
        """Read a cached count without triggering a DynamoDB load on a miss."""
        if self._redis is None:
            return None
        try:
            cached = self._redis.get(self._key(category, difficulty))
            value = int(cached) if cached is not None else None
            return value if value is not None and value >= 0 else None
        except (RedisError, TypeError, ValueError):
            logger.warning("Problem catalog count cache read failed", exc_info=True)
            return None

    @classmethod
    def _page_key(
        cls,
        category: Optional[str],
        difficulty: Optional[str],
        limit: int,
        cursor: Optional[str],
    ) -> str:
        category_key = cls._filter_key(category)
        difficulty_key = cls._filter_key(difficulty)
        cursor_key = quote(cursor.strip(), safe="") if cursor else "__first__"
        return (
            f"{cls._page_key_prefix}:{limit}:{category_key}:"
            f"{difficulty_key}:{cursor_key}"
        )

    def get_page(
        self,
        category: Optional[str],
        difficulty: Optional[str],
        limit: int,
        cursor: Optional[str],
    ) -> dict[str, Any] | None:
        """Return a cached serialized ProblemPage, if one is available."""
        if self._redis is None:
            return None

        try:
            cached = self._redis.get(self._page_key(category, difficulty, limit, cursor))
            if cached is None:
                return None
            payload = json.loads(cached)
            if isinstance(payload, dict) and isinstance(payload.get("items"), list):
                return payload
            return None
        except (RedisError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning("Problem catalog page cache read failed", exc_info=True)
            return None

    def get_page_or_load(
        self,
        category: Optional[str],
        difficulty: Optional[str],
        limit: int,
        cursor: Optional[str],
        loader: Callable[[], dict[str, Any] | None],
    ) -> dict[str, Any] | None:
        """Return a page or fill its Redis entry under a per-page lock."""
        key = self._page_key(category, difficulty, limit, cursor)
        return self._cache_aside(
            key,
            lambda: self.get_page(category, difficulty, limit, cursor),
            loader,
            lambda payload: self.set_page(
                category,
                difficulty,
                limit,
                cursor,
                payload,
            ),
        )

    def set_page(
        self,
        category: Optional[str],
        difficulty: Optional[str],
        limit: int,
        cursor: Optional[str],
        payload: dict[str, Any],
    ) -> None:
        """Store a public ProblemPage for the configured cache lifetime."""
        if self._redis is None or payload.get("total_count") is None:
            return

        try:
            self._redis.set(
                self._page_key(category, difficulty, limit, cursor),
                json.dumps(payload, separators=(",", ":")),
                ex=self._ttl_seconds,
            )
        except (RedisError, TypeError, ValueError):
            logger.warning("Problem catalog page cache write failed", exc_info=True)


problem_catalog_count_cache = ProblemCatalogCountCache()
