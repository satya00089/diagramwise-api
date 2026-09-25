"""Narrow server-to-server persistence boundary for the authenticated MCP service."""

from __future__ import annotations

import hmac
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, model_validator

from app.models.architecture_models import ArchitectureDocument
from app.services.dynamodb_service import dynamodb_service
from app.utils.config import get_settings


router = APIRouter(prefix="/integrations/mcp", tags=["mcp-integrations"])
bearer = HTTPBearer(auto_error=False)


class McpArchitectureCreateRequest(BaseModel):
    """Canonical document plus compiled compatibility payload from MCP."""

    schemaVersion: Literal["1.0"] = "1.0"
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    document: ArchitectureDocument | None = None
    nodes: list[Any] = Field(default_factory=list, max_length=100)
    edges: list[Any] = Field(default_factory=list, max_length=200)
    reasoningContext: dict[str, Any] = Field(default_factory=dict)
    idempotencyKey: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    visibility: Literal["public"] = "public"

    @model_validator(mode="after")
    def validate_canonical_document_alignment(self) -> "McpArchitectureCreateRequest":
        """Keep canonical and legacy representations aligned during migration."""

        if self.document is None:
            return self
        if self.document.schema_version != self.schemaVersion:
            raise ValueError("document schema version must match request schema version")
        if self.document.title != self.title:
            raise ValueError("document title must match request title")
        if (
            self.document.idempotency_key is not None
            and self.document.idempotency_key != self.idempotencyKey
        ):
            raise ValueError("document idempotency key must match request")

        expected_node_refs = {component.ref for component in self.document.components}
        actual_node_refs = {
            node.get("id")
            for node in self.nodes
            if isinstance(node, dict) and isinstance(node.get("id"), str)
        }
        if (
            actual_node_refs != expected_node_refs
            or len(actual_node_refs) != len(self.nodes)
        ):
            raise ValueError(
                "compiled nodes must contain exactly the canonical component refs"
            )

        expected_edges = {
            (
                connection.ref or f"connection-{index + 1}",
                connection.source,
                connection.target,
            )
            for index, connection in enumerate(self.document.connections)
        }
        actual_edges = {
            (edge.get("id"), edge.get("source"), edge.get("target"))
            for edge in self.edges
            if isinstance(edge, dict)
        }
        if actual_edges != expected_edges or len(actual_edges) != len(self.edges):
            raise ValueError(
                "compiled edges must contain exactly the canonical connections"
            )
        return self


class McpArchitectureCreateResponse(BaseModel):
    status: Literal["created", "existing"]
    architectureId: str
    url: str
    editorUrl: str | None = None
    previewUrl: str | None = None
    public: bool = True


def _require_mcp_service(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> tuple[str, str, bool]:
    """Authenticate the private MCP-to-API hop and resolve its service owner."""

    settings = get_settings()
    expected_token = settings.mcp_integration_token
    service_user_id = settings.mcp_integration_user_id
    supplied_token = getattr(credentials, "credentials", "")
    delegated_user_id = (
        request.headers.get("X-Diagramwise-MCP-User-ID", "").strip()
        if request
        else ""
    )

    if not expected_token or (not service_user_id and not delegated_user_id):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "MCP_INTEGRATION_NOT_CONFIGURED",
                "message": "MCP architecture persistence is not configured",
            },
        )
    if not hmac.compare_digest(supplied_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "A valid integration token is required"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    if delegated_user_id:
        if len(delegated_user_id) > 128:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "INVALID_DELEGATED_USER", "message": "The delegated user is invalid"},
            )
        delegated_user = dynamodb_service.get_user_by_id(delegated_user_id)
        if not delegated_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "INVALID_DELEGATED_USER", "message": "The delegated user is not available"},
            )
        author_name = (
            getattr(delegated_user, "name", None)
            or getattr(delegated_user, "email", None)
            or settings.mcp_integration_author_name
        )
        return delegated_user.id, author_name, True

    return service_user_id, settings.mcp_integration_author_name, False


def _stable_diagram_id(user_id: str, idempotency_key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"diagramwise:mcp:{user_id}:{idempotency_key}"))


@router.post(
    "/architectures",
    response_model=McpArchitectureCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_mcp_architecture(
    request: McpArchitectureCreateRequest,
    service: tuple[str, str, bool] | tuple[str, str] = Depends(_require_mcp_service),
) -> McpArchitectureCreateResponse:
    """Persist and publish one explicitly public MCP-created architecture.

    This route is intentionally separate from the user JWT diagram routes. It
    is not a browser endpoint and is disabled unless the integration token and
    fallback service owner is configured. OAuth-scoped requests use the
    authenticated Diagramwise user instead.
    """

    user_id, author_name = service[:2]
    delegated_user = len(service) > 2 and bool(service[2])
    diagram_id = _stable_diagram_id(user_id, request.idempotencyKey)
    existing = dynamodb_service.get_diagram(user_id=user_id, diagram_id=diagram_id)
    reasoning_context = dict(request.reasoningContext)

    def response_links(public_id: str, canonical_id: str) -> dict[str, str]:
        settings = get_settings()
        links = {
            "previewUrl": (
                f"{getattr(settings, 'public_api_url', 'https://api.diagramwise.com').rstrip('/')}/api/v1/public/diagrams/"
                f"{public_id}/preview.png"
            )
        }
        if delegated_user:
            links["editorUrl"] = (
                f"{settings.frontend_url.rstrip('/')}/playground/free?diagramId={canonical_id}"
            )
        return links

    if existing:
        existing_document = getattr(existing, "canonicalDocument", None)
        if (
            existing.title != request.title
            or existing.description != request.description
            or existing.nodes != request.nodes
            or existing.edges != request.edges
            or (
                existing_document is not None
                and request.document is not None
                and existing_document != request.document
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "IDEMPOTENCY_CONFLICT",
                    "message": "The idempotency key was already used for a different architecture",
                },
            )
        published = {
            "diagramId": existing.publicSnapshotId or existing.id,
        }
        if not existing.isPublic:
            published = dynamodb_service.publish_diagram(
                user_id=user_id,
                diagram_id=existing.id,
                author_name=author_name,
            ) or {}
        public_id = published.get("diagramId")
        if not public_id:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "PUBLISH_FAILED",
                    "message": "Diagramwise could not publish the existing architecture",
                },
            )
        return McpArchitectureCreateResponse(
            status="existing",
            architectureId=public_id,
            url=f"{get_settings().frontend_url.rstrip('/')}/public/{public_id}",
            **response_links(public_id, existing.id),
        )

    diagram = dynamodb_service.create_diagram(
        user_id=user_id,
        title=request.title,
        description=request.description,
        nodes=request.nodes,
        edges=request.edges,
        reasoning_context=reasoning_context,
        diagram_id=diagram_id,
        canonical_document=(
            request.document.model_dump(by_alias=True, exclude_none=True)
            if request.document is not None
            else None
        ),
    )
    published = dynamodb_service.publish_diagram(
        user_id=user_id,
        diagram_id=diagram.id,
        author_name=author_name,
    )
    if not published:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "PUBLISH_FAILED",
                "message": "Diagramwise created the architecture but could not publish it",
            },
        )

    public_id = published["diagramId"]
    return McpArchitectureCreateResponse(
        status="created",
        architectureId=public_id,
        url=f"{get_settings().frontend_url.rstrip('/')}/public/{public_id}",
        **response_links(public_id, diagram.id),
    )
