import itertools
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.diagram_models import Diagram
from app.routers import canvases as canvases_router
from app.routers.auth import get_current_user
from app.services.canvas_service import CanvasService
from tests.test_canvas_service import InMemoryCanvasRepository

OWNER = "user-owner"
OTHER = "user-other"
DIAGRAM_ID = "diagram-legacy"
NOW = datetime(2026, 10, 14, tzinfo=timezone.utc).isoformat()


_client_counter = itertools.count(1)


@pytest.fixture
def client(monkeypatch):
    repository = InMemoryCanvasRepository()
    monkeypatch.setattr(
        canvases_router, "_canvas_service", lambda owner_id: CanvasService(repository)
    )
    monkeypatch.setattr(
        canvases_router,
        "validate_diagram_access",
        lambda user_id, diagram_id, action: (user_id == OWNER, "Access denied"),
    )
    diagram = Diagram(
        id=DIAGRAM_ID,
        userId=OWNER,
        title="Legacy design",
        nodes=[{"id": "n1"}],
        edges=[],
        createdAt=NOW,
        updatedAt=NOW,
    )
    monkeypatch.setattr(
        canvases_router.dynamodb_service,
        "get_diagram",
        lambda user_id, diagram_id: diagram if user_id == OWNER and diagram_id == DIAGRAM_ID else None,
    )
    monkeypatch.setattr(
        canvases_router.dynamodb_service, "get_shared_diagrams_for_user", lambda user_id: []
    )

    current = {"user_id": OWNER}
    app.dependency_overrides[get_current_user] = lambda: current
    # Each test gets its own client IP so the per-IP rate limiter starts empty.
    n = next(_client_counter)
    yield TestClient(app, client=(f"10.77.{n // 250}.{n % 250 + 1}", 50000)), current
    app.dependency_overrides.pop(get_current_user, None)


def _base(diagram_id: str = DIAGRAM_ID) -> str:
    return f"/api/v1/diagrams/{diagram_id}/canvases"


def test_legacy_diagram_lists_as_one_canvas(client):
    api, _ = client
    body = api.get(_base()).json()
    assert body["primaryCanvasId"] == DIAGRAM_ID
    assert [c["name"] for c in body["canvases"]] == ["Main"]
    assert body["canvases"][0]["nodeCount"] == 1


def test_create_then_list_shows_new_tab_after_legacy(client):
    api, _ = client
    created = api.post(_base(), json={"name": "Flow", "kind": "flow"})
    assert created.status_code == 201
    body = api.get(_base()).json()
    assert [c["name"] for c in body["canvases"]] == ["Main", "Flow"]


def test_stale_save_returns_409_with_current_version(client):
    api, _ = client
    created = api.post(_base(), json={"name": "Flow", "kind": "flow"}).json()
    ok = api.put(
        f"{_base()}/{created['id']}",
        json={"nodes": [{"id": "a"}], "edges": [], "version": 1},
    )
    assert ok.status_code == 200 and ok.json()["version"] == 2

    stale = api.put(
        f"{_base()}/{created['id']}",
        json={"nodes": [{"id": "b"}], "edges": [], "version": 1},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["currentVersion"] == 2


def test_invalid_graph_is_rejected_with_400(client):
    api, _ = client
    created = api.post(_base(), json={"name": "Flow", "kind": "flow"}).json()
    response = api.put(
        f"{_base()}/{created['id']}",
        json={
            "nodes": [{"id": "a"}],
            "edges": [{"id": "e", "source": "a", "target": "missing"}],
            "version": 1,
        },
    )
    assert response.status_code == 400
    assert "not on this canvas" in response.json()["detail"]


def test_cannot_delete_last_canvas_over_http(client):
    api, _ = client
    response = api.delete(f"{_base()}/{DIAGRAM_ID}")
    assert response.status_code == 400


def test_create_over_limit_returns_400(client):
    api, _ = client
    for i in range(9):
        assert api.post(_base(), json={"name": f"Tab {i}", "kind": "other"}).status_code == 201
    response = api.post(_base(), json={"name": "Eleventh", "kind": "other"})
    assert response.status_code == 400
    assert "at most" in response.json()["detail"]


def test_patch_rejects_order_field_and_points_to_reorder(client):
    api, _ = client
    response = api.patch(f"{_base()}/{DIAGRAM_ID}", json={"order": 3})
    assert response.status_code == 400
    assert "reorder" in response.json()["detail"]


def test_reorder_and_duplicate_flow(client):
    api, _ = client
    flow = api.post(_base(), json={"name": "Flow", "kind": "flow"}).json()
    reordered = api.post(f"{_base()}/reorder", json={"orderedIds": [flow["id"], DIAGRAM_ID]})
    assert reordered.status_code == 200
    assert reordered.json()["primaryCanvasId"] == flow["id"]

    copy = api.post(f"{_base()}/{flow['id']}/duplicate")
    assert copy.status_code == 201
    assert copy.json()["name"] == "Flow copy"


def test_non_owner_is_forbidden(client):
    api, current = client
    current["user_id"] = OTHER
    assert api.get(_base()).status_code == 403
    assert api.post(_base(), json={"name": "X", "kind": "other"}).status_code == 403


def test_unknown_workspace_is_404(client):
    api, _ = client
    response = api.get(_base("nope"))
    assert response.status_code == 404


def test_primary_save_mirrors_into_diagram(client, monkeypatch):
    api, _ = client
    mirrored = []
    monkeypatch.setattr(
        canvases_router.dynamodb_service,
        "update_diagram",
        lambda **kwargs: mirrored.append(kwargs),
    )
    created = api.post(_base(), json={"name": "Flow", "kind": "flow"}).json()

    # The legacy canvas stays primary (lowest order), so its saves mirror.
    api.put(f"{_base()}/{DIAGRAM_ID}", json={"nodes": [{"id": "p"}], "edges": [], "version": 1})
    assert len(mirrored) == 1
    assert mirrored[0]["diagram_id"] == DIAGRAM_ID
    assert mirrored[0]["nodes"] == [{"id": "p"}]

    # Saves to a non-primary tab must not overwrite the diagram.
    api.put(f"{_base()}/{created['id']}", json={"nodes": [{"id": "f"}], "edges": [], "version": 1})
    assert len(mirrored) == 1
