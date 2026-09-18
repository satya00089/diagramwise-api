import asyncio
from types import SimpleNamespace

import pytest

from app.models.diagram_models import Diagram
from app.routers import diagrams as diagrams_router
from app.services.dynamodb_service import DynamoDBService
from scripts.backfill_diagram_counts import count_fields


def summary_item(**overrides):
    item = {
        "userId": "owner-1",
        "id": "diagram-1",
        "title": "Example",
        "description": "A summary",
        "createdAt": "2026-01-01T00:00:00+00:00",
        "updatedAt": "2026-01-02T00:00:00+00:00",
        "nodeCount": 3,
        "edgeCount": 2,
        "collaborators": [],
    }
    item.update(overrides)
    return item


def test_summary_response_excludes_canvas_arrays(monkeypatch):
    monkeypatch.setattr(
        diagrams_router.dynamodb_service,
        "get_user_by_id",
        lambda user_id: SimpleNamespace(
            id=user_id, name="Owner", email="owner@example.com", picture=None
        ),
    )

    response = diagrams_router.enrich_diagram_summary_response(
        Diagram(**summary_item()), "owner-1", {}
    )

    payload = response.model_dump()
    assert payload["nodeCount"] == 3
    assert payload["edgeCount"] == 2
    assert "nodes" not in payload
    assert "edges" not in payload


def test_summary_query_uses_projection_without_canvas_arrays(monkeypatch):
    class FakeTable:
        def __init__(self):
            self.calls = []

        def query(self, **kwargs):
            self.calls.append(kwargs)
            return {"Items": [summary_item()]}

    service = DynamoDBService.__new__(DynamoDBService)
    table = FakeTable()
    service.diagrams_table = table

    diagrams = service.get_diagram_summaries_by_user("owner-1")

    assert len(diagrams) == 1
    assert diagrams[0].nodeCount == 3
    assert "nodes" not in table.calls[0]["ExpressionAttributeNames"].values()
    assert "edges" not in table.calls[0]["ExpressionAttributeNames"].values()


def test_summary_page_query_returns_projected_page_and_cursor():
    class FakeTable:
        def query(self, **kwargs):
            assert kwargs["Limit"] == 2
            return {
                "Items": [summary_item()],
                "LastEvaluatedKey": {"userId": "owner-1", "id": "diagram-1"},
            }

    service = DynamoDBService.__new__(DynamoDBService)
    service.diagrams_table = FakeTable()

    diagrams, cursor = service.get_diagram_summary_page_by_user("owner-1", 2)

    assert len(diagrams) == 1
    assert diagrams[0].edgeCount == 2
    assert cursor == {"userId": "owner-1", "id": "diagram-1"}


def test_diagram_list_route_returns_cursor_page(monkeypatch):
    monkeypatch.setattr(
        diagrams_router.dynamodb_service,
        "get_diagram_summary_page_by_user",
        lambda **_: ([Diagram(**summary_item())], {"userId": "owner-1", "id": "diagram-1"}),
    )
    monkeypatch.setattr(
        diagrams_router.dynamodb_service,
        "get_user_by_id",
        lambda user_id: SimpleNamespace(
            id=user_id, name="Owner", email="owner@example.com", picture=None
        ),
    )

    response = asyncio.run(
        diagrams_router.get_diagrams(
            limit=1,
            cursor=None,
            current_user={"user_id": "owner-1"},
        )
    )

    payload = response.model_dump()
    assert payload["has_more"] is True
    assert payload["next_cursor"]
    assert payload["items"][0]["nodeCount"] == 3
    assert "nodes" not in payload["items"][0]
    assert "edges" not in payload["items"][0]


def test_update_writes_counts_with_canvas_updates():
    class FakeTable:
        def __init__(self):
            self.kwargs = None

        def update_item(self, **kwargs):
            self.kwargs = kwargs
            return {"Attributes": summary_item()}

    service = DynamoDBService.__new__(DynamoDBService)
    table = FakeTable()
    service.diagrams_table = table

    service.update_diagram(
        user_id="owner-1",
        diagram_id="diagram-1",
        nodes=[{"id": "n1"}, {"id": "n2"}],
        edges=[{"id": "e1"}],
    )

    values = table.kwargs["ExpressionAttributeValues"]
    assert values[":node_count"] == 2
    assert values[":edge_count"] == 1


def test_backfill_count_fields_rejects_malformed_canvas_data():
    assert count_fields({"nodes": [], "edges": []}) == (0, 0)
    with pytest.raises(ValueError, match="invalid nodes or edges"):
        count_fields({"nodes": {}, "edges": []})
