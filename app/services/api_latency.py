"""Helpers for privacy-safe, mergeable API latency histograms."""

from __future__ import annotations

import math
from typing import Iterable


# Upper bounds (milliseconds) for a fixed-size histogram. Fixed buckets make
# daily Redis/S3 aggregates mergeable without retaining individual requests.
LATENCY_BUCKETS_MS = (
    5,
    10,
    25,
    50,
    75,
    100,
    150,
    200,
    300,
    500,
    750,
    1_000,
    1_500,
    2_000,
    3_000,
    5_000,
    10_000,
    30_000,
    60_000,
    120_000,
    300_000,
    600_000,
)
API_LATENCY_SCHEMA_VERSION = 1


def bucket_for_duration(duration_ms: float) -> int:
    """Return the first histogram bucket whose upper bound contains duration."""
    duration = max(0, math.ceil(duration_ms))
    for index, upper_bound in enumerate(LATENCY_BUCKETS_MS):
        if duration <= upper_bound:
            return index
    return len(LATENCY_BUCKETS_MS) - 1


def percentile_upper_bound(
    bucket_counts: Iterable[int], percentile: float
) -> int | None:
    """Estimate a percentile using the selected bucket's conservative bound."""
    counts = [max(0, int(count)) for count in bucket_counts]
    if len(counts) != len(LATENCY_BUCKETS_MS):
        return None

    sample_count = sum(counts)
    if percentile >= 99:
        minimum_samples = 100
    elif percentile >= 95:
        minimum_samples = 20
    else:
        minimum_samples = 1
    if sample_count < minimum_samples:
        return None

    target_rank = math.ceil(sample_count * percentile / 100)
    cumulative = 0
    for index, count in enumerate(counts):
        cumulative += count
        if cumulative >= target_rank:
            return LATENCY_BUCKETS_MS[index]
    return LATENCY_BUCKETS_MS[-1]


def summarize_buckets(bucket_counts: Iterable[int]) -> dict[str, int | None]:
    counts = [max(0, int(count)) for count in bucket_counts]
    sample_count = sum(counts)
    return {
        "sampleCount": sample_count,
        "p50Ms": percentile_upper_bound(counts, 50),
        "p95Ms": percentile_upper_bound(counts, 95),
        "p99Ms": percentile_upper_bound(counts, 99),
    }
