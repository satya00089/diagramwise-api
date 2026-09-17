"""Main application file for the Diagrammatic API service."""

from contextlib import asynccontextmanager
import asyncio
import logging
import sys

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi import FastAPI

from app.utils.config import get_settings
from app.routers import (
    auth,
    diagrams,
    assessment,
    interview,
    problems,
    collaboration,
    attempts,
    recommendations,
    components,
    share,
    walkthroughs,
    sprites,
    events,
    analytics,
    learning_paths,
    transcriptions,
    feedback,
)
from app.middleware.rate_limiter import RateLimitMiddleware
from app.services.dynamodb_service import dynamodb_service
from app.services.s3_analytics_aggregator import redis_analytics_aggregator
from app.services.llm_client import flush_langfuse

# Load settings
settings = get_settings()
logger = logging.getLogger(__name__)


async def _analytics_flush_loop() -> None:
    """Periodically export Redis analytics snapshots to S3."""
    interval = max(10, settings.analytics_flush_interval_seconds)
    while True:
        await asyncio.sleep(interval)
        try:
            flushed = await asyncio.to_thread(redis_analytics_aggregator.flush_pending)
            if flushed:
                logger.info("Flushed %d analytics snapshot(s) to S3", flushed)
        except Exception:
            logger.exception("Analytics Redis-to-S3 flush failed")


def _configure_error_monitoring() -> None:
    if not settings.sentry_dsn:
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        send_default_pii=False,
        traces_sample_rate=0.0,
        integrations=[FastApiIntegration(), StarletteIntegration()],
    )
    logger.info("Sentry error monitoring enabled environment=%s", settings.sentry_environment)


def _configure_app_logging(debug: bool) -> None:
    """Make application logs visible in the terminal and captured stdout."""
    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.DEBUG if debug else logging.INFO)

    # Uvicorn normally configures its own loggers, but it does not guarantee
    # that application loggers have a handler. Attach one so app.* messages
    # are visible in local development and captured by deployment logs.
    if not app_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s: %(message)s",
                "%Y-%m-%d %H:%M:%S",
            )
        )
        app_logger.addHandler(handler)

    # Prevent duplicate lines when Uvicorn/root logging also has a handler.
    app_logger.propagate = False


_configure_app_logging(settings.debug)
_configure_error_monitoring()

# API version prefix
API_V1_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """
    Application lifespan events.
    """
    # Startup
    logger.info("Diagrammatic API starting up")
    try:
        # Test DynamoDB connection
        dynamodb_service.get_all_problems()
        logger.info("DynamoDB connected successfully during startup")
    except Exception:
        logger.exception("Failed to connect to DynamoDB at startup")

    flush_task = asyncio.create_task(_analytics_flush_loop())
    try:
        yield
    finally:
        flush_task.cancel()
        await asyncio.gather(flush_task, return_exceptions=True)
        flush_langfuse(settings)

    # Shutdown (might not run on some serverless platforms)
    logger.info("Diagrammatic API shutting down")


app = FastAPI(
    title="Diagramwise API",
    description="AI-powered assessment service for system design solutions",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Middleware
app.add_middleware(
    RateLimitMiddleware,
    requests_per_minute=settings.rate_limit_per_minute,
    trusted_proxy_ips=settings.trusted_proxy_ips,
)

app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

# CORS must be the outermost middleware so error responses also receive the
# appropriate CORS headers. Starlette wraps the most recently added middleware
# around the previously configured chain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(assessment.router, prefix=API_V1_PREFIX, tags=["assessment"])
app.include_router(interview.router, prefix=API_V1_PREFIX, tags=["interview"])
app.include_router(problems.router, prefix=API_V1_PREFIX, tags=["problems"])
app.include_router(auth.router, prefix=API_V1_PREFIX, tags=["auth"])
app.include_router(diagrams.router, prefix=API_V1_PREFIX, tags=["diagrams"])
app.include_router(collaboration.router, prefix=API_V1_PREFIX, tags=["collaboration"])
app.include_router(attempts.router, prefix=API_V1_PREFIX, tags=["attempts"])
app.include_router(recommendations.router, prefix=API_V1_PREFIX, tags=["recommendations"])
app.include_router(share.router, prefix=API_V1_PREFIX, tags=["share"])
app.include_router(walkthroughs.router, prefix=API_V1_PREFIX, tags=["walkthroughs"])
app.include_router(events.router, prefix=API_V1_PREFIX, tags=["events"])
app.include_router(analytics.router, prefix=API_V1_PREFIX, tags=["analytics"])
app.include_router(
    components.router, tags=["components"]
)  # No prefix needed, router has /api/components
app.include_router(sprites.router, tags=["sprites"])
app.include_router(learning_paths.router, prefix=API_V1_PREFIX, tags=["learning-paths"])
app.include_router(transcriptions.router, prefix=API_V1_PREFIX, tags=["transcriptions"])
app.include_router(feedback.router, prefix=API_V1_PREFIX, tags=["feedback"])


@app.get("/")
async def root():
    """Root endpoint providing basic info about the API."""
    return {
        "message": "System Design Assessor API",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        # Test DynamoDB connection by fetching problems
        dynamodb_service.get_all_problems()
        healthy = True
    except Exception:
        logger.exception("DynamoDB health check failed")
        healthy = False
    return {"status": "healthy" if healthy else "degraded", "database": "dynamodb"}
