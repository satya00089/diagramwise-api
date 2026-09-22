"""Application configuration settings using Pydantic."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings
from pydantic import AliasChoices, Field, ValidationError


class Settings(BaseSettings):
    """Application configuration settings."""

    # LLM provider configuration. Existing OPENAI_* names remain supported so
    # switching providers does not require changing the current deployment at
    # the same time as the application code.
    llm_provider: Literal["openai", "azure_openai"] = Field(
        "openai", validation_alias="LLM_PROVIDER"
    )
    openai_api_key: str | None = Field(None, validation_alias="OPENAI_API_KEY")
    llm_model: str = Field(
        "gpt-4o-mini",
        validation_alias=AliasChoices("LLM_MODEL", "OPENAI_MODEL"),
    )
    llm_max_tokens: int = Field(
        2000, validation_alias=AliasChoices("LLM_MAX_TOKENS", "OPENAI_MAX_TOKENS")
    )
    llm_assessment_max_tokens: int = Field(
        6000,
        validation_alias=AliasChoices(
            "LLM_ASSESSMENT_MAX_TOKENS", "OPENAI_ASSESSMENT_MAX_TOKENS"
        ),
    )
    llm_assessment_reasoning_effort: Literal[
        "none", "low", "medium", "high", "xhigh", "max"
    ] = Field(
        "low",
        validation_alias=AliasChoices(
            "LLM_ASSESSMENT_REASONING_EFFORT",
            "OPENAI_ASSESSMENT_REASONING_EFFORT",
        ),
    )
    llm_temperature: float = Field(
        0.3, validation_alias=AliasChoices("LLM_TEMPERATURE", "OPENAI_TEMPERATURE")
    )
    # Azure deployment names are user-defined and may not reveal whether the
    # deployed model supports reasoning controls. Leave unset to infer from a
    # recognizable model name, or set explicitly for custom deployment names.
    llm_supports_reasoning: bool | None = Field(
        None, validation_alias="LLM_SUPPORTS_REASONING"
    )

    # Azure OpenAI uses a resource endpoint, API version, and deployment name.
    # The key is optional at startup so OpenAI mode remains the default and
    # managed configuration can validate only the selected provider.
    azure_openai_api_key: str | None = Field(
        None, validation_alias="AZURE_OPENAI_API_KEY"
    )
    azure_openai_endpoint: str | None = Field(
        None, validation_alias="AZURE_OPENAI_ENDPOINT"
    )
    azure_openai_api_version: str = Field(
        "2024-10-21", validation_alias="AZURE_OPENAI_API_VERSION"
    )
    azure_openai_deployment: str | None = Field(
        None, validation_alias="AZURE_OPENAI_DEPLOYMENT"
    )

    # Optional Langfuse observability. Both keys are required before tracing
    # is activated; the base URL supports Cloud and self-hosted deployments.
    langfuse_enabled: bool = Field(True, validation_alias="LANGFUSE_ENABLED")
    langfuse_public_key: str | None = Field(
        None, validation_alias="LANGFUSE_PUBLIC_KEY"
    )
    langfuse_secret_key: str | None = Field(
        None, validation_alias="LANGFUSE_SECRET_KEY"
    )
    langfuse_base_url: str = Field(
        "https://cloud.langfuse.com", validation_alias="LANGFUSE_BASE_URL"
    )
    langfuse_environment: str = Field(
        "production", validation_alias="LANGFUSE_TRACING_ENVIRONMENT"
    )
    langfuse_release: str | None = Field(
        None, validation_alias="LANGFUSE_TRACING_RELEASE"
    )
    langfuse_sample_rate: float = Field(
        1.0, ge=0.0, le=1.0, validation_alias="LANGFUSE_SAMPLE_RATE"
    )
    langfuse_capture_content: bool = Field(
        False, validation_alias="LANGFUSE_CAPTURE_CONTENT"
    )

    # API Configuration
    api_host: str = Field("0.0.0.0", validation_alias="API_HOST")
    api_port: int = Field(8000, validation_alias="API_PORT")
    debug: bool = Field(False, validation_alias="DEBUG")
    sentry_dsn: str | None = Field(None, validation_alias="SENTRY_DSN")
    sentry_environment: str = Field(
        "production", validation_alias="SENTRY_ENVIRONMENT"
    )

    # CORS Configuration
    allowed_origins: list[str] = Field(
        [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://localhost:5174",
            "https://diagramwise.com",
            "https://www.diagramwise.com",
            "https://diagrammatic.next-zen.dev",
        ],
        validation_alias="ALLOWED_ORIGINS",
    )

    # Trusted Hosts Configuration
    trusted_hosts: list[str] = Field(["*"], validation_alias="TRUSTED_HOSTS")

    # Server-to-server MCP integration. The endpoint remains disabled unless
    # both values are configured; user-facing MCP writes must use OAuth at the
    # MCP boundary rather than exposing this service credential.
    mcp_integration_token: str | None = Field(
        None, validation_alias="MCP_INTEGRATION_TOKEN"
    )
    mcp_integration_user_id: str | None = Field(
        None, validation_alias="MCP_INTEGRATION_USER_ID"
    )
    mcp_integration_author_name: str = Field(
        "Diagramwise MCP", validation_alias="MCP_INTEGRATION_AUTHOR_NAME"
    )

    # Rate Limiting
    rate_limit_per_minute: int = Field(30, validation_alias="RATE_LIMIT_PER_MINUTE")
    # Only these direct peer IPs may supply X-Forwarded-For / X-Real-IP.
    # Leave empty when the API is directly internet-facing.
    trusted_proxy_ips: list[str] = Field(
        [], validation_alias="TRUSTED_PROXY_IPS"
    )

    # JWT Configuration
    jwt_secret_key: str = Field(..., validation_alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field("HS256", validation_alias="JWT_ALGORITHM")
    jwt_access_token_expire_hours: int = Field(
        24, validation_alias="JWT_ACCESS_TOKEN_EXPIRE_HOURS"
    )

    # Google OAuth Configuration
    google_client_id: str = Field(..., validation_alias="GOOGLE_CLIENT_ID")

    # AWS DynamoDB Configuration
    aws_region: str = Field("us-east-1", validation_alias="AWS_REGION")
    aws_access_key_id: str = Field(..., validation_alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str = Field(..., validation_alias="AWS_SECRET_ACCESS_KEY")
    dynamodb_users_table: str = Field(
        "diagrammatic_users", validation_alias="DYNAMODB_USERS_TABLE"
    )
    dynamodb_diagrams_table: str = Field(
        "diagrammatic_diagrams", validation_alias="DYNAMODB_DIAGRAMS_TABLE"
    )
    dynamodb_problems_table: str = Field(
        "diagrammatic_problems", validation_alias="DYNAMODB_PROBLEMS_TABLE"
    )
    dynamodb_attempts_table: str = Field(
        "diagrammatic_problem_attempts", validation_alias="DYNAMODB_ATTEMPTS_TABLE"
    )
    dynamodb_feedback_table: str = Field(
        "diagrammatic_feedback", validation_alias="DYNAMODB_FEEDBACK_TABLE"
    )
    # Frontend URL (used to build public solution links)
    frontend_url: str = Field(
        "https://diagramwise.com",
        validation_alias="FRONTEND_URL",
    )
    public_api_url: str = Field(
        "https://api.diagramwise.com",
        validation_alias="PUBLIC_API_URL",
    )

    # Transactional email / email verification.  Keep the API key optional so
    # local development can start without Resend; signup will return a clear
    # service-unavailable response until it is configured.
    resend_api_key: str | None = Field(None, validation_alias="RESEND_API_KEY")
    resend_from_email: str = Field(
        "Diagramwise <no-reply@diagrammatic.next-zen.dev>",
        validation_alias="RESEND_FROM_EMAIL",
    )
    brand_logo_url: str | None = Field(None, validation_alias="BRAND_LOGO_URL")
    email_verification_secret: str | None = Field(
        None, validation_alias="EMAIL_VERIFICATION_SECRET"
    )
    email_verification_expire_minutes: int = Field(
        20, validation_alias="EMAIL_VERIFICATION_EXPIRE_MINUTES"
    )
    email_verification_resend_cooldown_seconds: int = Field(
        60, validation_alias="EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS"
    )

    components_table_name: str = Field(
        "diagrammatic_components", validation_alias="DYNAMODB_COMPONENTS_TABLE"
    )
    dynamodb_walkthroughs_table: str = Field(
        "diagrammatic_guided_walkthroughs", validation_alias="DYNAMODB_WALKTHROUGHS_TABLE"
    )

    # Spritesheet key prefix (sheets are stored under the analytics bucket)
    sprites_key_prefix: str = Field(
        "spritesheet", validation_alias="SPRITES_KEY_PREFIX"
    )

    # Primary S3 bucket used by the application for all S3 writes.
    # This single env var replaces prior `TRAINING_S3_BUCKET` / `S3_BUCKET`.
    analytics_s3_bucket: str = Field(..., validation_alias="ANALYTICS_S3_BUCKET")

    # HMAC secret used to pseudonymize user IDs for analytics storage.
    analytics_hmac_secret: str | None = Field(
        None, validation_alias="ANALYTICS_HMAC_SECRET"
    )

    # Redis is the hot aggregation store; S3 receives periodic snapshots.
    redis_uri: str | None = Field(None, validation_alias="REDIS_URI")
    analytics_flush_interval_seconds: int = Field(
        60, validation_alias="ANALYTICS_FLUSH_INTERVAL_SECONDS"
    )

    # Whisper transcription service (proxied so the browser never calls it directly)
    whisper_service_url: str = Field(..., validation_alias="WHISPER_SERVICE_URL")

    class Config:
        """Pydantic configuration to load from .env file."""

        env_file = ".env"
        case_sensitive = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached settings instance."""
    try:
        s = Settings()  # type: ignore[call-arg]
    except ValidationError as e:
        # Raise a helpful message in logs for missing required envs
        raise RuntimeError(f"Configuration error: {e}") from e
    return s
