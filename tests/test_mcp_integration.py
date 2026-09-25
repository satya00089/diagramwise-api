import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from app.routers import mcp_integration


def request_payload(**overrides):
    payload = {
        "schemaVersion": "1.0",
        "title": "Redis-backed API",
        "description": "A public MCP-created architecture",
        "document": {
            "schemaVersion": "1.0",
            "title": "Redis-backed API",
            "summary": "A public MCP-created architecture",
            "components": [
                {
                    "ref": "api",
                    "catalogRef": "generic.custom-component",
                    "label": "API",
                }
            ],
            "connections": [],
            "idempotencyKey": "redis-api-v1",
        },
        "nodes": [{"id": "api", "type": "custom", "position": {"x": 0, "y": 0}, "data": {}}],
        "edges": [],
        "reasoningContext": {"source": "diagramwise-mcp"},
        "idempotencyKey": "redis-api-v1",
        "visibility": "public",
    }
    payload.update(overrides)
    return mcp_integration.McpArchitectureCreateRequest(**payload)


def test_service_auth_requires_configured_token(monkeypatch):
    monkeypatch.setattr(
        mcp_integration,
        "get_settings",
        lambda: SimpleNamespace(mcp_integration_token=None, mcp_integration_user_id=None),
    )

    with pytest.raises(HTTPException) as error:
        mcp_integration._require_mcp_service(None)

    assert error.value.status_code == 503


def test_mcp_architecture_creation_publishes_and_returns_public_url(monkeypatch):
    class FakeDynamo:
        def __init__(self):
            self.created = None

        def get_diagram(self, **kwargs):
            return None

        def create_diagram(self, **kwargs):
            self.created = kwargs
            return SimpleNamespace(id=kwargs["diagram_id"])

        def publish_diagram(self, **kwargs):
            return {"diagramId": "public-123"}

    fake = FakeDynamo()
    monkeypatch.setattr(mcp_integration, "dynamodb_service", fake)
    monkeypatch.setattr(
        mcp_integration,
        "get_settings",
        lambda: SimpleNamespace(
            frontend_url="https://diagramwise.com",
            mcp_integration_author_name="Diagramwise MCP",
        ),
    )

    response = asyncio.run(
        mcp_integration.create_mcp_architecture(
            request_payload(),
            service=("mcp-service-user", "Diagramwise MCP"),
        )
    )

    assert response.status == "created"
    assert response.architectureId == "public-123"
    assert response.url == "https://diagramwise.com/public/public-123"
    assert fake.created["diagram_id"]
    assert fake.created["reasoning_context"] == {"source": "diagramwise-mcp"}
    assert fake.created["canonical_document"]["schemaVersion"] == "1.0"


def test_canonical_document_is_validated_at_the_api_seam():
    request = request_payload()

    assert request.document is not None
    assert request.document.title == request.title
    assert request.document.idempotency_key == request.idempotencyKey


def test_legacy_compiled_payload_remains_accepted_during_migration():
    payload = request_payload().model_dump(by_alias=True)
    payload.pop("document")

    request = mcp_integration.McpArchitectureCreateRequest(**payload)

    assert request.document is None


def test_canonical_document_must_match_compatibility_fields():
    with pytest.raises(ValueError, match="document title must match request title"):
        request_payload(
            document={
                "schemaVersion": "1.0",
                "title": "Different title",
                "components": [],
                "connections": [],
                "idempotencyKey": "redis-api-v1",
            }
        )

    with pytest.raises(ValueError, match="document idempotency key must match request"):
        request_payload(
            document={
                "schemaVersion": "1.0",
                "title": "Redis-backed API",
                "components": [],
                "connections": [],
                "idempotencyKey": "different-key",
            }
        )

    with pytest.raises(
        ValueError,
        match="compiled nodes must contain exactly the canonical component refs",
    ):
        request_payload(
            nodes=[
                {
                    "id": "database",
                    "type": "custom",
                    "position": {"x": 0, "y": 0},
                    "data": {},
                }
            ]
        )


def test_mcp_architecture_rejects_idempotency_conflict(monkeypatch):
    existing = SimpleNamespace(
        id="existing",
        publicSnapshotId="public-existing",
        isPublic=True,
        title="Different title",
        description="Different",
        nodes=[],
        edges=[],
    )
    monkeypatch.setattr(mcp_integration.dynamodb_service, "get_diagram", lambda **_: existing)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            mcp_integration.create_mcp_architecture(
                request_payload(),
                service=("mcp-service-user", "Diagramwise MCP"),
            )
        )

    assert error.value.status_code == 409


def test_service_auth_delegates_oauth_user_without_fallback_owner(monkeypatch):
    monkeypatch.setattr(
        mcp_integration,
        "get_settings",
        lambda: SimpleNamespace(
            mcp_integration_token="integration-token",
            mcp_integration_user_id=None,
            mcp_integration_author_name="Diagramwise MCP",
        ),
    )
    monkeypatch.setattr(
        mcp_integration.dynamodb_service,
        "get_user_by_id",
        lambda user_id: SimpleNamespace(id=user_id, name="Satya", email="satya@example.com"),
    )
    request = Request(
        {
            "type": "http",
            "headers": [(b"x-diagramwise-mcp-user-id", b"user-123")],
        }
    )

    result = mcp_integration._require_mcp_service(
        request,
        HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="integration-token"
        ),
    )

    assert result == ("user-123", "Satya", True)
