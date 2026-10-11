from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from app.services.api_latency import (
    LATENCY_BUCKETS_MS,
    bucket_for_duration,
    summarize_buckets,
)
from app.services.s3_analytics_aggregator import RedisAnalyticsAggregator


def test_bucket_for_duration_uses_a_conservative_upper_bound() -> None:
    assert bucket_for_duration(0) == 0
    assert LATENCY_BUCKETS_MS[bucket_for_duration(50)] == 50
    assert LATENCY_BUCKETS_MS[bucket_for_duration(51)] == 75
    assert LATENCY_BUCKETS_MS[bucket_for_duration(90_000)] == 120_000


def test_percentiles_are_merged_from_buckets_and_guard_low_sample_counts() -> None:
    counts = [0] * len(LATENCY_BUCKETS_MS)
    counts[2] = 50
    counts[5] = 30
    counts[10] = 20

    assert summarize_buckets(counts) == {
        "sampleCount": 100,
        "p50Ms": 25,
        "p95Ms": 750,
        "p99Ms": 750,
    }

    low_sample_counts = [0] * len(LATENCY_BUCKETS_MS)
    low_sample_counts[3] = 19
    summary = summarize_buckets(low_sample_counts)
    assert summary["sampleCount"] == 19
    assert summary["p50Ms"] == 50
    assert summary["p95Ms"] is None
    assert summary["p99Ms"] is None


class FakeRedis:
    def __init__(self, fields: dict[str, str] | None = None) -> None:
        self.fields = fields or {}
        self.pipeline_calls: list[tuple[str, tuple]] = []

    def pipeline(self, transaction=True):
        return FakePipeline(self, transaction)

    def hgetall(self, _key):
        return self.fields


class FakePipeline:
    def __init__(self, client: FakeRedis, transaction: bool) -> None:
        self.client = client
        self.client.pipeline_calls.append(("pipeline", (transaction,)))

    def hincrby(self, key, field, increment):
        self.client.pipeline_calls.append(("hincrby", (key, field, increment)))
        return self

    def expire(self, key, seconds):
        self.client.pipeline_calls.append(("expire", (key, seconds)))
        return self

    def execute(self):
        return None


def test_record_api_latency_stores_only_route_template_bucket_and_status() -> None:
    aggregator = object.__new__(RedisAnalyticsAggregator)
    aggregator._redis = FakeRedis()
    aggregator._prefix = "analytics:aggregate"
    aggregator._latency_prefix = "analytics:api-latency:v1"
    aggregator._date = lambda: "2026-10-11"

    aggregator.record_api_latency("/api/v1/problems/{problem_id}", 200, 76)

    operations = aggregator._redis.pipeline_calls
    increment = next(args for name, args in operations if name == "hincrby")
    assert increment[0] == "analytics:api-latency:v1:2026-10-11"
    assert increment[1].startswith("latency|")
    assert increment[1].endswith("|2xx|5")
    assert increment[2] == 1
    assert any(
        name == "expire" and args[1] == 60 * 60 * 24 * 95
        for name, args in operations
    )


def test_daily_snapshot_merges_latency_into_separate_schema_section() -> None:
    aggregator = object.__new__(RedisAnalyticsAggregator)
    aggregator._decode = RedisAnalyticsAggregator._decode
    encoded_route = aggregator._encode("/api/v1/problems/{problem_id}")

    snapshot = aggregator._merge_snapshot(
        {"api_latency": {"/api/v1/problems/{problem_id}": {"2xx": {"6": 2}}}},
        {f"latency|{encoded_route}|2xx|6": "3"},
    )

    assert snapshot["api_latency"]["/api/v1/problems/{problem_id}"]["2xx"]["6"] == 5


def test_range_summary_combines_s3_snapshots_with_unflushed_redis_counts() -> None:
    aggregator = object.__new__(RedisAnalyticsAggregator)
    aggregator._redis = FakeRedis()
    aggregator._prefix = "analytics:aggregate"
    aggregator._latency_prefix = "analytics:api-latency:v1"
    encoded_route = aggregator._encode("/api/v1/problems/{problem_id}")
    aggregator._redis.fields = {
        f"latency|{encoded_route}|5xx|10": "1",
    }
    aggregator._get_existing = lambda _key: (
        {
            "api_latency": {
                "/api/v1/problems/{problem_id}": {"2xx": {"8": 99}}
            }
        },
        None,
    )
    aggregator._s3_key = lambda date: f"analytics/aggregates/{date}.json"

    report = aggregator.summarize_api_latency("2026-10-11", "2026-10-11")

    assert report["sampleCount"] == 100
    assert report["p50Ms"] == 300
    assert report["p95Ms"] == 300
    assert report["p99Ms"] == 300
    assert report["routes"][0]["sampleCount"] == 100
    assert report["collectionEnabled"] is True


def test_latency_middleware_uses_matched_route_not_raw_url() -> None:
    from app.middleware.api_latency import ApiLatencyMiddleware

    observations = []

    class Metrics:
        def record_api_latency(self, route, status_code, duration_ms):
            observations.append((route, status_code, duration_ms))

    async def app(scope, _receive, send):
        scope["route"] = SimpleNamespace(path="/api/v1/problems/{problem_id}")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        return None

    async def run_without_worker_thread(function, *args):
        return function(*args)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/problems/private-id?token=secret",
    }
    with patch("asyncio.to_thread", run_without_worker_thread):
        asyncio.run(ApiLatencyMiddleware(app, Metrics())(scope, receive, send))

    assert len(observations) == 1
    assert observations[0][0] == "/api/v1/problems/{problem_id}"
    assert observations[0][1] == 200
    assert observations[0][2] >= 0
