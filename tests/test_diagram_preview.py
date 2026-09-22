from types import SimpleNamespace

from app.services.diagram_preview import render_architecture_svg


def test_render_architecture_svg_contains_nodes_edges_and_escapes_text():
    svg = render_architecture_svg(
        title="URL shortener <draft>",
        nodes=[
            {
                "id": "api",
                "position": {"x": 0, "y": 0},
                "data": {"label": "API Service", "subtitle": "Reads & writes"},
            },
            {
                "id": "db",
                "position": {"x": 440, "y": 0},
                "data": {"label": "PostgreSQL"},
            },
        ],
        edges=[
            {
                "source": "api",
                "target": "db",
                "data": {"label": "Reads and writes"},
            }
        ],
    )

    assert svg.startswith("<svg ")
    assert "URL shortener &lt;draft&gt;" in svg
    assert "API Service" in svg
    assert "PostgreSQL" in svg
    assert "Reads and writes" in svg
    assert "marker-end=\"url(#arrow)\"" in svg


def test_mcp_response_includes_editor_and_preview_links_for_delegated_user(monkeypatch):
    import asyncio
    from app.routers import mcp_integration

    class FakeDynamo:
        def get_diagram(self, **kwargs):
            return None

        def create_diagram(self, **kwargs):
            return SimpleNamespace(id=kwargs["diagram_id"])

        def publish_diagram(self, **kwargs):
            return {"diagramId": "public-123"}

    monkeypatch.setattr(mcp_integration, "dynamodb_service", FakeDynamo())
    monkeypatch.setattr(
        mcp_integration,
        "get_settings",
        lambda: SimpleNamespace(
            frontend_url="https://diagramwise.com",
            public_api_url="https://api.diagramwise.com",
            mcp_integration_author_name="Diagramwise MCP",
        ),
    )

    payload = mcp_integration.McpArchitectureCreateRequest(
        title="API with cache",
        idempotencyKey="delegated-user-v1",
        nodes=[],
        edges=[],
    )
    result = asyncio.run(
        mcp_integration.create_mcp_architecture(
            payload,
            service=("user-123", "Satya", True),
        )
    )

    assert result.editorUrl.startswith(
        "https://diagramwise.com/playground/free?diagramId="
    )
    assert result.previewUrl == (
        "https://api.diagramwise.com/api/v1/public/diagrams/public-123/preview.svg"
    )


def test_public_preview_route_returns_svg(monkeypatch):
    import asyncio
    from app.routers import share

    monkeypatch.setattr(
        share.dynamodb_service,
        "get_public_diagram",
        lambda **_: SimpleNamespace(
            title="Preview",
            nodes=[
                {
                    "id": "api",
                    "position": {"x": 0, "y": 0},
                    "data": {"label": "API"},
                }
            ],
            edges=[],
        ),
    )

    response = asyncio.run(share.get_public_diagram_preview("public-123"))

    assert response.media_type == "image/svg+xml"
    assert response.headers["cache-control"] == "public, max-age=300"
    assert response.body.startswith(b"<svg ")
