"""Collect privacy-safe API latency histograms after response bodies are sent."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.services.s3_analytics_aggregator import redis_analytics_aggregator

logger = logging.getLogger(__name__)


class ApiLatencyMiddleware:
    """Record matched API route durations without retaining request data."""

    def __init__(
        self,
        app: ASGIApp,
        metrics: Any = redis_analytics_aggregator,
        write_timeout_seconds: float = 0.5,
    ) -> None:
        self.app = app
        self.metrics = metrics
        self.write_timeout_seconds = write_timeout_seconds

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") == "OPTIONS"
            or not str(scope.get("path", "")).startswith("/api/")
            or str(scope.get("path", "")).endswith("/admin/api-latency")
        ):
            await self.app(scope, receive, send)
            return

        started_at = time.perf_counter()
        status_code = 500
        observation_started = False

        async def observe_once() -> None:
            nonlocal observation_started
            if observation_started:
                return
            observation_started = True
            route = scope.get("route")
            route_template = getattr(route, "path", None)
            if not isinstance(route_template, str) or not route_template.startswith(
                "/api/"
            ):
                return

            elapsed_ms = (time.perf_counter() - started_at) * 1000
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(
                        self.metrics.record_api_latency,
                        route_template,
                        status_code,
                        elapsed_ms,
                    ),
                    timeout=self.write_timeout_seconds,
                )
            except Exception:
                # Telemetry must never turn an otherwise successful API request
                # into an error. Redis writes have a strict per-request budget.
                logger.warning("Could not record API latency observation")

        async def send_with_observation(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)
            if message["type"] == "http.response.body" and not message.get(
                "more_body", False
            ):
                await observe_once()

        try:
            await self.app(scope, receive, send_with_observation)
        except Exception:
            status_code = 500
            await observe_once()
            raise
