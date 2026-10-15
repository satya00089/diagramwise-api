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


def test_legacy_get_projects_the_primary_canvas_graph(monkeypatch):
    diagram = Diagram(**summary_item(nodes=[{"id": "stale"}], edges=[]))

    class FakeRepository:
        def __init__(self, *_args):
            pass

        def list_canvas_summaries(self, _diagram_id):
            return [{"id": "canvas-primary", "order": 0}]

        def get_canvas(self, _diagram_id, _canvas_id):
            return SimpleNamespace(
                nodes=[{"id": "canonical"}], edges=[],
            )

    monkeypatch.setattr(diagrams_router, "CanvasRepository", FakeRepository)
    monkeypatch.setattr(
        diagrams_router.dynamodb_service,
        "get_diagram",
        lambda _user_id, _diagram_id: diagram,
    )
    monkeypatch.setattr(
        diagrams_router.dynamodb_service,
        "get_user_by_id",
        lambda _user_id: None,
    )

    endpoint = diagrams_router.get_diagram(
        "diagram-1", current_user={"user_id": "owner-1"}
    )
    try:
        endpoint.send(None)
        raise AssertionError("diagram GET endpoint unexpectedly yielded")
    except StopIteration as completed:
        response = completed.value

    assert response.nodes == [{"id": "canonical"}]


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


@pytest.mark.parametrize(
    "method_name", ["get_diagrams_by_user", "get_diagram_summaries_by_user"]
)
def test_owned_diagram_queries_hide_canvas_records(method_name):
    class FakeTable:
        def query(self, **kwargs):
            return {
                "Items": [
                    summary_item(),
                    summary_item(
                        id="diagram-1#canvas#canvas-1", recordType="canvas"
                    ),
                ]
            }

    service = DynamoDBService.__new__(DynamoDBService)
    service.diagrams_table = FakeTable()

    diagrams = getattr(service, method_name)("owner-1")

    assert [diagram.id for diagram in diagrams] == ["diagram-1"]


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


def test_summary_page_filter_excludes_canvas_metadata_records():
    class FakeTable:
        def __init__(self):
            self.query_kwargs = None

        def query(self, **kwargs):
            self.query_kwargs = kwargs
            return {"Items": [summary_item()]}

    service = DynamoDBService.__new__(DynamoDBService)
    table = FakeTable()
    service.diagrams_table = table

    diagrams, _ = service.get_diagram_summary_page_by_user("owner-1", 24)

    assert len(diagrams) == 1
    filter_expression = table.query_kwargs["FilterExpression"].get_expression()
    assert filter_expression["operator"] == "AND"
    canvas_exclusion = filter_expression["values"][1].get_expression()
    assert canvas_exclusion["operator"] == "OR"
    canvas_not_equals = canvas_exclusion["values"][1].get_expression()
    assert canvas_not_equals["values"][1] == "canvas"


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


def test_clear_diagram_graph_removes_legacy_arrays_and_keeps_counts():
    class FakeTable:
        def update_item(self, **kwargs):
            self.kwargs = kwargs

    service = DynamoDBService.__new__(DynamoDBService)
    table = FakeTable()
    service.diagrams_table = table

    assert service.clear_diagram_graph("owner-1", "diagram-1", 4, 2)

    assert "REMOVE #nodes, #edges" in table.kwargs["UpdateExpression"]
    assert table.kwargs["ExpressionAttributeNames"] == {
        "#nodes": "nodes",
        "#edges": "edges",
    }
    values = table.kwargs["ExpressionAttributeValues"]
    assert values[":node_count"] == 4
    assert values[":edge_count"] == 2


def test_backfill_count_fields_rejects_malformed_canvas_data():
    assert count_fields({"nodes": [], "edges": []}) == (0, 0)
    with pytest.raises(ValueError, match="invalid nodes or edges"):
        count_fields({"nodes": {}, "edges": []})
