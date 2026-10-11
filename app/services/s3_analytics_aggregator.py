"""Aggregate analytics in Redis and periodically snapshot the counters to S3."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import boto3
from botocore.exceptions import ClientError
from mypy_boto3_s3 import S3Client
from redis import Redis

from app.models.analytics_models import AnalyticsEvent
from app.services.api_latency import API_LATENCY_SCHEMA_VERSION, LATENCY_BUCKETS_MS
from app.utils.config import get_settings

logger = logging.getLogger(__name__)


class RedisAnalyticsAggregator:
    """Collect counters atomically in Redis and export them to S3 in batches."""

    _redis: Redis[str] | None
    _client: S3Client

    def __init__(self) -> None:
        settings = get_settings()
        self._bucket = settings.analytics_s3_bucket
        self._redis = (
            Redis.from_url(settings.redis_uri, decode_responses=True)
            if settings.redis_uri
            else None
        )
        self._client = boto3.client(
            "s3",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
        self._prefix = "analytics:aggregate"
        self._latency_prefix = f"analytics:api-latency:v{API_LATENCY_SCHEMA_VERSION}"

    @staticmethod
    def _encode(value: str) -> str:
        return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")

    @staticmethod
    def _decode(value: str) -> str:
        return base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8")

    def _date(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _redis_key(self, date: str) -> str:
        return f"{self._prefix}:{date}"

    def _latency_redis_key(self, date: str) -> str:
        return f"{self._latency_prefix}:{date}"

    def _session_hash(self, session_id: str) -> str | None:
        secret = get_settings().analytics_hmac_secret
        if not secret or not session_id:
            return None
        return hmac.new(
            secret.encode("utf-8"), session_id.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def aggregate_events(
        self, events: List[AnalyticsEvent], session_id: str | None = None
    ) -> None:
        """Atomically add an accepted batch to today's Redis aggregate."""
        if not events:
            return
        if self._redis is None:
            logger.error("REDIS_URI is not configured; analytics batch was not stored")
            return

        key = self._redis_key(self._date())
        session_hash = self._session_hash(session_id or "")
        pipe = self._redis.pipeline(transaction=True)
        pipe.hincrby(key, "total_events", len(events))
        for event in events:
            name = event.event_name or "unknown"
            route = event.route or event.page_url or "unknown"
            name_key = self._encode(name)
            route_key = self._encode(route)
            pipe.hincrby(key, f"count|{name_key}|{route_key}", 1)
            if session_hash:
                pipe.hset(key, f"session|{name_key}|{route_key}|{session_hash}", 1)
        pipe.expire(key, 60 * 60 * 24 * 8)
        pipe.execute()

    def record_api_latency(
        self, route: str, status_code: int, duration_ms: float
    ) -> None:
        """Increment a bounded histogram bucket without storing request data."""
        if self._redis is None:
            return
        if not route.startswith("/api/") or len(route) > 200:
            return

        from app.services.api_latency import bucket_for_duration

        status_group = f"{status_code // 100}xx"
        if status_group not in {"2xx", "3xx", "4xx", "5xx"}:
            status_group = "5xx"
        encoded_route = self._encode(route)
        bucket = bucket_for_duration(duration_ms)
        key = self._latency_redis_key(self._date())
        pipe = self._redis.pipeline(transaction=True)
        pipe.hincrby(key, f"latency|{encoded_route}|{status_group}|{bucket}", 1)
        # Preserve enough hot history for the 90-day dashboard range, even if
        # a serverless instance does not live long enough to run its S3 flusher.
        pipe.expire(key, 60 * 60 * 24 * 95)
        pipe.execute()

    def _s3_key(self, date: str) -> str:
        year, month, day = date.split("-")
        return f"analytics/aggregates/{year}/{month}/{day}.json"

    def _get_existing(self, key: str) -> tuple[Dict[str, Any], str | None]:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            body = response["Body"].read().decode("utf-8")
            return (json.loads(body) if body else {}, response.get("ETag"))
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in ("NoSuchKey", "404"):
                return {}, None
            raise

    def _merge_snapshot(
        self, existing: Dict[str, Any], fields: Dict[str, str]
    ) -> Dict[str, Any]:
        events_map = existing.setdefault("events", {})
        session_keys = existing.setdefault("_session_keys", {})
        latency_map = existing.setdefault("api_latency", {})
        stored_latency_version = existing.get("api_latency_schema_version")
        if stored_latency_version not in (None, API_LATENCY_SCHEMA_VERSION):
            raise ValueError(
                "Cannot merge an unsupported API latency histogram schema"
            )
        existing["api_latency_schema_version"] = API_LATENCY_SCHEMA_VERSION
        total = int(existing.get("total_events", 0)) + int(
            fields.get("total_events", 0)
        )

        for field, value in fields.items():
            parts = field.split("|")
            if len(parts) < 3 or parts[0] not in ("count", "session"):
                if len(parts) != 4 or parts[0] != "latency":
                    continue
                route = self._decode(parts[1])
                status_group = parts[2]
                try:
                    bucket = int(parts[3])
                except ValueError:
                    continue
                if (
                    status_group not in {"2xx", "3xx", "4xx", "5xx"}
                    or not 0 <= bucket < len(LATENCY_BUCKETS_MS)
                ):
                    continue
                counts = (
                    latency_map.setdefault(route, {})
                    .setdefault(status_group, {})
                )
                bucket_key = str(bucket)
                counts[bucket_key] = counts.get(bucket_key, 0) + int(value)
                continue
            name = self._decode(parts[1])
            route = self._decode(parts[2])
            events_map.setdefault(name, {})
            if parts[0] == "count":
                events_map[name][route] = events_map[name].get(route, 0) + int(value)
            elif len(parts) == 4:
                session_keys.setdefault(name, {}).setdefault(route, [])
                if parts[3] not in session_keys[name][route]:
                    session_keys[name][route].append(parts[3])

        existing["unique_sessions"] = {
            name: {route: len(hashes) for route, hashes in routes.items()}
            for name, routes in session_keys.items()
        }
        existing["total_events"] = total
        existing["updated_at"] = datetime.now(timezone.utc).isoformat()
        return existing

    def summarize_api_latency(self, from_date: str, to_date: str) -> Dict[str, Any]:
        """Merge daily histogram counts, then derive estimates for the range."""
        from app.services.api_latency import summarize_buckets

        start = datetime.fromisoformat(from_date).date()
        end = datetime.fromisoformat(to_date).date()
        route_counts: Dict[str, List[int]] = {}
        overall_counts = [0] * len(LATENCY_BUCKETS_MS)

        def add_snapshot(snapshot: Dict[str, Any]) -> None:
            schema_version = snapshot.get("api_latency_schema_version", 1)
            if schema_version != API_LATENCY_SCHEMA_VERSION:
                return
            for route, status_groups in snapshot.get("api_latency", {}).items():
                if not isinstance(status_groups, dict):
                    continue
                counts = route_counts.setdefault(
                    route, [0] * len(LATENCY_BUCKETS_MS)
                )
                for bucket_map in status_groups.values():
                    if not isinstance(bucket_map, dict):
                        continue
                    for bucket_text, count in bucket_map.items():
                        try:
                            bucket = int(bucket_text)
                            value = max(0, int(count))
                        except (TypeError, ValueError):
                            continue
                        if 0 <= bucket < len(LATENCY_BUCKETS_MS):
                            counts[bucket] += value

        cursor = start
        while cursor <= end:
            date_key = cursor.isoformat()
            snapshot, _etag = self._get_existing(self._s3_key(date_key))
            add_snapshot(snapshot)

            # Include observations that have not yet been exported to S3.
            if self._redis is not None:
                for field, value in self._redis.hgetall(
                    self._latency_redis_key(date_key)
                ).items():
                    parts = field.split("|")
                    if len(parts) != 4 or parts[0] != "latency":
                        continue
                    try:
                        route = self._decode(parts[1])
                        bucket = int(parts[3])
                        increment = max(0, int(value))
                    except (ValueError, TypeError):
                        continue
                    if (
                        parts[2] not in {"2xx", "3xx", "4xx", "5xx"}
                        or not 0 <= bucket < len(LATENCY_BUCKETS_MS)
                    ):
                        continue
                    route_counts.setdefault(
                        route, [0] * len(LATENCY_BUCKETS_MS)
                    )[bucket] += increment
            cursor += timedelta(days=1)

        for counts in route_counts.values():
            for index, count in enumerate(counts):
                overall_counts[index] += count

        routes = []
        for route, counts in route_counts.items():
            routes.append({"route": route, **summarize_buckets(counts)})
        routes.sort(
            key=lambda item: (
                item["p95Ms"] is not None,
                item["p95Ms"] or 0,
                item["sampleCount"],
            ),
            reverse=True,
        )
        return {
            "fromDate": from_date,
            "toDate": to_date,
            "collectionEnabled": self._redis is not None,
            **summarize_buckets(overall_counts),
            "routes": routes[:10],
        }

    def _flush_snapshot(self, snapshot_key: str, date: str) -> bool:
        if self._redis is None:
            return False
        fields = self._redis.hgetall(snapshot_key)
        if not fields:
            self._redis.delete(snapshot_key)
            return True

        s3_key = self._s3_key(date)
        for attempt in range(4):
            existing, etag = self._get_existing(s3_key)
            payload = self._merge_snapshot(existing, fields)
            kwargs: Dict[str, Any] = {
                "Bucket": self._bucket,
                "Key": s3_key,
                "Body": json.dumps(payload, default=str).encode("utf-8"),
                "ContentType": "application/json",
            }
            kwargs["IfMatch" if etag else "IfNoneMatch"] = etag or "*"
            try:
                self._client.put_object(**kwargs)
                self._redis.delete(snapshot_key)
                return True
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code not in (
                    "PreconditionFailed",
                    "ConditionalRequestConflict",
                    "412",
                    "409",
                ):
                    raise
                time.sleep(0.05 * (2**attempt))
        return False

    def flush_pending(self) -> int:
        """Rotate Redis hashes and export pending counters to S3."""
        if self._redis is None:
            return 0
        lock_key = f"{self._prefix}:flush-lock"
        lock_value = str(uuid.uuid4())
        if not self._redis.set(lock_key, lock_value, nx=True, ex=55):
            return 0
        flushed = 0
        try:
            current_keys = list(
                self._redis.scan_iter(match=f"{self._prefix}:20??-??-??")
            )
            current_keys.extend(
                self._redis.scan_iter(
                    match=f"{self._latency_prefix}:20??-??-??"
                )
            )
            for current_key in current_keys:
                date = current_key.rsplit(":", 1)[-1]
                snapshot_key = f"{current_key}:processing:{uuid.uuid4()}"
                self._redis.rename(current_key, snapshot_key)
                if self._flush_snapshot(snapshot_key, date):
                    flushed += 1

            # Retry snapshots left behind by a process crash or a failed S3 put.
            processing_keys = list(
                self._redis.scan_iter(
                    match=f"{self._prefix}:20??-??-??:processing:*"
                )
            )
            processing_keys.extend(
                self._redis.scan_iter(
                    match=f"{self._latency_prefix}:20??-??-??:processing:*"
                )
            )
            for snapshot_key in processing_keys:
                date = snapshot_key.rsplit(":processing:", 1)[0].rsplit(":", 1)[-1]
                if self._flush_snapshot(snapshot_key, date):
                    flushed += 1
            return flushed
        finally:
            self._redis.delete(lock_key)

    def summarize_date_range(self, from_date: str, to_date: str) -> Dict[str, Any]:
        """Read daily snapshots without exposing pseudonymous session keys."""
        start = datetime.fromisoformat(from_date).date()
        end = datetime.fromisoformat(to_date).date()
        daily: List[Dict[str, Any]] = []
        event_totals: Dict[str, int] = {}
        route_totals: Dict[str, int] = {}
        total_events = 0
        cursor = start
        while cursor <= end:
            date_key = cursor.isoformat()
            snapshot, _etag = self._get_existing(self._s3_key(date_key))
            day_events = int(snapshot.get("total_events", 0))
            total_events += day_events
            for event_name, routes in snapshot.get("events", {}).items():
                event_total = sum(int(value) for value in routes.values())
                event_totals[event_name] = event_totals.get(event_name, 0) + event_total
                for route, value in routes.items():
                    route_totals[route] = route_totals.get(route, 0) + int(value)
            daily.append({"date": date_key, "events": day_events})
            cursor += timedelta(days=1)
        return {
            "totalEvents": total_events,
            "pageViews": event_totals.get("page_view", 0),
            "daily": daily,
            "topEvents": [
                {"name": name, "count": count}
                for name, count in sorted(event_totals.items(), key=lambda pair: pair[1], reverse=True)[:8]
            ],
            "topRoutes": [
                {"route": route, "count": count}
                for route, count in sorted(route_totals.items(), key=lambda pair: pair[1], reverse=True)[:8]
            ],
        }


redis_analytics_aggregator = RedisAnalyticsAggregator()
# Legacy class name retained for callers importing the old service directly.
S3AnalyticsAggregator = RedisAnalyticsAggregator
# Compatibility name for the router and existing imports.
s3_analytics_aggregator = redis_analytics_aggregator
