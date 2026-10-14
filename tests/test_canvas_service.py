from typing import Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from boto3.dynamodb.conditions import BeginsWith, Equals
from botocore.exceptions import ClientError

from app.models.canvas_models import (
    build_canvas,
    MAX_CANVASES_PER_WORKSPACE,
    CanvasKind,
    CanvasRecord,
    CanvasValidationError,
    legacy_canvas_from_diagram,
)
from app.services.canvas_repository import CanvasRepository, CanvasVersionConflict
from app.services.canvas_service import CanvasNotFound, CanvasService

NOW = "2026-10-14T10:00:00+00:00"
WS = "diagram-1"


class InMemoryCanvasRepository:
    """Same interface as CanvasRepository, backed by a dict."""

    def __init__(self):
        self.rows: Dict[tuple, CanvasRecord] = {}

    def list_canvases(self, workspace_id: str) -> List[CanvasRecord]:
        rows = [c for (ws, _), c in self.rows.items() if ws == workspace_id and c.deletedAt is None]
        return sorted(rows, key=lambda c: c.order)

    def get_canvas(self, workspace_id: str, canvas_id: str) -> Optional[CanvasRecord]:
        row = self.rows.get((workspace_id, canvas_id))
        return row if row and row.deletedAt is None else None

    def put_new_canvas(self, canvas: CanvasRecord) -> bool:
        key = (canvas.workspaceId, canvas.id)
        if key in self.rows:
            return False
        self.rows[key] = canvas
        return True

    def update_meta(self, workspace_id, canvas_id, updates):
        current = self.get_canvas(workspace_id, canvas_id)
        if current is None:
            return None
        updated = current.model_copy(update=updates)
        self.rows[(workspace_id, canvas_id)] = updated
        return updated

    def save_content(self, workspace_id, canvas_id, nodes, edges, expected_version):
        current = self.get_canvas(workspace_id, canvas_id)
        if current is None or current.version != expected_version:
            raise CanvasVersionConflict(current.version if current else None)
        updated = current.model_copy(
            update={"nodes": nodes, "edges": edges, "version": expected_version + 1}
        )
        self.rows[(workspace_id, canvas_id)] = updated
        return updated

    def soft_delete(self, workspace_id, canvas_id):
        current = self.get_canvas(workspace_id, canvas_id)
        if current is None:
            return False
        self.rows[(workspace_id, canvas_id)] = current.model_copy(update={"deletedAt": NOW})
        return True


def _legacy(nodes=None, edges=None) -> CanvasRecord:
    return legacy_canvas_from_diagram(
        WS, nodes or [], edges or [], created_at=NOW, updated_at=NOW
    )


@pytest.fixture
def service():
    return CanvasService(InMemoryCanvasRepository())


# --- reads and legacy presentation -------------------------------------------------


def test_legacy_workspace_lists_virtual_canvas_without_writing(service):
    legacy = _legacy([{"id": "n1"}])
    canvases = service.list_canvases(WS, legacy)
    assert [c.id for c in canvases] == [WS]
    assert service.repository.rows == {}, "reading must not persist the legacy canvas"


def test_empty_workspace_without_legacy_lists_nothing(service):
    assert service.list_canvases(WS, None) == []


def test_get_legacy_canvas_by_diagram_id(service):
    legacy = _legacy([{"id": "n1"}])
    assert service.get_canvas(WS, WS, legacy).nodes == [{"id": "n1"}]
    with pytest.raises(CanvasNotFound):
        service.get_canvas(WS, "other", legacy)


# --- create -----------------------------------------------------------------------


def test_first_create_materializes_legacy_then_appends(service):
    legacy = _legacy([{"id": "n1"}])
    created = service.create_canvas(WS, "Flow", CanvasKind.FLOW, legacy)

    stored = service.list_canvases(WS, None)
    assert [c.id for c in stored] == [WS, created.id]
    assert stored[0].nodes == [{"id": "n1"}], "legacy content survives the first write"
    assert created.order == 1
    assert created.kind == CanvasKind.FLOW


def test_materialize_is_idempotent(service):
    legacy = _legacy([{"id": "n1"}])
    service.materialize_legacy(WS, legacy)
    service.materialize_legacy(WS, _legacy([{"id": "changed"}]))
    stored = service.list_canvases(WS, None)
    assert len(stored) == 1
    assert stored[0].nodes == [{"id": "n1"}]


def test_create_enforces_limit(service):
    for i in range(MAX_CANVASES_PER_WORKSPACE):
        service.create_canvas(WS, f"Tab {i}", CanvasKind.OTHER, None)
    with pytest.raises(CanvasValidationError):
        service.create_canvas(WS, "Eleventh", CanvasKind.OTHER, None)


def test_create_dedupes_names(service):
    service.create_canvas(WS, "ER", CanvasKind.ER, None)
    second = service.create_canvas(WS, "er", CanvasKind.ER, None)
    assert second.name == "er (2)"


# --- rename, kind, reorder ---------------------------------------------------------


def test_rename_dedupes_against_other_canvases_only(service):
    a = service.create_canvas(WS, "Alpha", CanvasKind.OTHER, None)
    service.create_canvas(WS, "Beta", CanvasKind.OTHER, None)
    renamed = service.update_canvas(WS, a.id, None, name="beta")
    assert renamed.name == "beta (2)"
    same = service.update_canvas(WS, a.id, None, name="Alpha")
    assert same.name == "Alpha", "a canvas may keep its own name"


def test_rename_missing_canvas_raises(service):
    with pytest.raises(CanvasNotFound):
        service.update_canvas(WS, "missing", None, name="X")


def test_reorder_requires_every_canvas_exactly_once(service):
    a = service.create_canvas(WS, "A", CanvasKind.OTHER, None)
    b = service.create_canvas(WS, "B", CanvasKind.OTHER, None)
    with pytest.raises(CanvasValidationError):
        service.reorder_canvases(WS, [a.id], None)
    with pytest.raises(CanvasValidationError):
        service.reorder_canvases(WS, [a.id, a.id], None)
    reordered = service.reorder_canvases(WS, [b.id, a.id], None)
    assert [c.id for c in reordered] == [b.id, a.id]


# --- content save and conflicts -----------------------------------------------------


def test_save_validates_graph_before_writing(service):
    created = service.create_canvas(WS, "A", CanvasKind.OTHER, None)
    with pytest.raises(CanvasValidationError):
        service.save_content(WS, created.id, [{"id": "a"}], [{"id": "e", "source": "a", "target": "zz"}], 1, None)
    assert service.repository.get_canvas(WS, created.id).nodes == []


def test_save_increments_version_and_rejects_stale_writes(service):
    created = service.create_canvas(WS, "A", CanvasKind.OTHER, None)
    saved = service.save_content(WS, created.id, [{"id": "a"}], [], 1, None)
    assert saved.version == 2
    with pytest.raises(CanvasVersionConflict) as conflict:
        service.save_content(WS, created.id, [{"id": "stale"}], [], 1, None)
    assert conflict.value.current_version == 2
    assert service.repository.get_canvas(WS, created.id).nodes == [{"id": "a"}]


def test_save_on_legacy_canvas_materializes_then_writes(service):
    legacy = _legacy([{"id": "n1"}])
    saved = service.save_content(WS, WS, [{"id": "n1"}, {"id": "n2"}], [], 1, legacy)
    assert saved.version == 2
    assert len(service.repository.get_canvas(WS, WS).nodes) == 2


# --- delete and duplicate ----------------------------------------------------------


def test_cannot_delete_last_canvas(service):
    only = service.create_canvas(WS, "Only", CanvasKind.OTHER, None)
    with pytest.raises(CanvasValidationError, match="at least one"):
        service.delete_canvas(WS, only.id, None)


def test_delete_keeps_others_and_hides_deleted(service):
    a = service.create_canvas(WS, "A", CanvasKind.OTHER, None)
    b = service.create_canvas(WS, "B", CanvasKind.OTHER, None)
    service.delete_canvas(WS, a.id, None)
    assert [c.id for c in service.list_canvases(WS, None)] == [b.id]
    with pytest.raises(CanvasNotFound):
        service.delete_canvas(WS, a.id, None)


def test_duplicate_copies_content_with_new_id_and_name(service):
    source = service.create_canvas(WS, "Flow", CanvasKind.FLOW, None)
    service.save_content(WS, source.id, [{"id": "a"}], [], 1, None)
    copy = service.duplicate_canvas(WS, source.id, None)
    assert copy.id != source.id
    assert copy.name == "Flow copy"
    assert copy.nodes == [{"id": "a"}]
    assert copy.version == 1


def test_duplicate_of_legacy_canvas_materializes_it(service):
    legacy = _legacy([{"id": "n1"}])
    copy = service.duplicate_canvas(WS, WS, legacy)
    names = [c.name for c in service.list_canvases(WS, None)]
    assert "Main" in names
    assert copy.name == "Main copy"


# --- repository mapping and conditional-write errors --------------------------------


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "x"}}, "UpdateItem")


def test_repository_maps_canvas_id_to_model_id():
    table = MagicMock()
    table.get_item.return_value = {
        "Item": {
            "workspaceId": WS,
            "canvasId": "c1",
            "name": "A",
            "kind": "flow",
            "order": 0,
            "nodes": [],
            "edges": [],
            "version": 1,
            "createdAt": NOW,
            "updatedAt": NOW,
        }
    }
    canvas = CanvasRepository(table, "owner-1").get_canvas(WS, "c1")
    assert canvas.id == "c1"
    assert canvas.kind == CanvasKind.FLOW


def test_repository_stale_save_raises_conflict_with_current_version():
    table = MagicMock()
    table.update_item.side_effect = _client_error("ConditionalCheckFailedException")
    table.get_item.return_value = {
        "Item": {
            "workspaceId": WS, "canvasId": "c1", "name": "A", "kind": "other",
            "order": 0, "nodes": [], "edges": [], "version": 5,
            "createdAt": NOW, "updatedAt": NOW,
        }
    }
    repository = CanvasRepository(table, "owner-1")
    with pytest.raises(CanvasVersionConflict) as conflict:
        repository.save_content(WS, "c1", [], [], 4)
    assert conflict.value.current_version == 5


def test_repository_save_condition_checks_version_not_just_existence():
    table = MagicMock()
    table.update_item.return_value = {"Attributes": {
        "workspaceId": WS, "canvasId": "c1", "name": "A", "kind": "other",
        "order": 0, "nodes": [], "edges": [], "version": 3,
        "createdAt": NOW, "updatedAt": NOW,
    }}
    CanvasRepository(table, "owner-1").save_content(WS, "c1", [], [], 2)
    kwargs = table.update_item.call_args.kwargs
    assert kwargs["ExpressionAttributeValues"][":next"] == 3
    assert "ConditionExpression" in kwargs


def test_repository_put_new_returns_false_when_taken():
    table = MagicMock()
    table.put_item.side_effect = _client_error("ConditionalCheckFailedException")
    canvas = _legacy()
    assert CanvasRepository(table, "owner-1").put_new_canvas(canvas) is False


def test_repository_other_client_errors_propagate():
    table = MagicMock()
    table.put_item.side_effect = _client_error("ProvisionedThroughputExceededException")
    repository = CanvasRepository(table, "owner-1")
    canvas = _legacy()
    with pytest.raises(ClientError):
        repository.put_new_canvas(canvas)


def test_repository_list_follows_pagination_and_hides_deleted():
    table = MagicMock()
    base = {"workspaceId": WS, "name": "A", "kind": "other", "nodes": [], "edges": [],
            "version": 1, "createdAt": NOW, "updatedAt": NOW}
    table.query.side_effect = [
        {"Items": [dict(base, canvasId="b", order=1)], "LastEvaluatedKey": {"k": 1}},
        {"Items": [dict(base, canvasId="a", order=0), dict(base, canvasId="gone", order=2, deletedAt=NOW)]},
    ]
    canvases = CanvasRepository(table, "owner-1").list_canvases(WS)
    assert [c.id for c in canvases] == ["a", "b"]


# --- legacy sync ----------------------------------------------------------------------


def test_sync_is_noop_without_canvas_records(service):
    assert service.sync_primary_from_legacy(WS, [{"id": "n"}], []) is False
    assert service.repository.rows == {}


def test_sync_writes_primary_canvas_only(service):
    primary = service.create_canvas(WS, "Main", CanvasKind.OTHER, None)
    other = service.create_canvas(WS, "Flow", CanvasKind.FLOW, None)
    assert service.sync_primary_from_legacy(WS, [{"id": "legacy"}], []) is True
    assert service.repository.get_canvas(WS, primary.id).nodes == [{"id": "legacy"}]
    assert service.repository.get_canvas(WS, other.id).nodes == []


def test_sync_skips_invalid_legacy_graph_without_raising(service):
    service.create_canvas(WS, "Main", CanvasKind.OTHER, None)
    bad_edges = [{"id": "e", "source": "a", "target": "missing"}]
    assert service.sync_primary_from_legacy(WS, [{"id": "a"}], bad_edges) is False


def test_sync_retries_on_conflict_then_succeeds(service):
    primary = service.create_canvas(WS, "Main", CanvasKind.OTHER, None)
    real_save = service.repository.save_content
    calls = {"n": 0}

    def flaky_save(workspace_id, canvas_id, nodes, edges, expected_version):
        calls["n"] += 1
        if calls["n"] == 1:
            # Simulate a concurrent writer bumping the version between read and write.
            real_save(workspace_id, canvas_id, [], [], expected_version)
            raise CanvasVersionConflict(expected_version + 1)
        return real_save(workspace_id, canvas_id, nodes, edges, expected_version)

    service.repository.save_content = flaky_save
    assert service.sync_primary_from_legacy(WS, [{"id": "legacy"}], []) is True
    assert calls["n"] == 2
    assert service.repository.get_canvas(WS, primary.id).nodes == [{"id": "legacy"}]


# --- storage layout: canvases are items in the diagrams table ------------------------


def test_canvas_item_uses_owner_partition_and_composite_sort_key():
    table = MagicMock()
    repo = CanvasRepository(table, "owner-1")
    canvas = _legacy([{"id": "n1"}])
    repo.put_new_canvas(canvas)
    item = table.put_item.call_args.kwargs["Item"]
    assert item["userId"] == "owner-1"
    assert item["id"] == f"{WS}#canvas#{WS}"
    assert item["canvasId"] == WS
    assert item["recordType"] == "canvas"
    assert item["kind"] == "other", "kind must be stored as a plain string"


def test_canvas_round_trips_through_item_shape():
    table = MagicMock()
    repo = CanvasRepository(table, "owner-1")
    canvas = build_canvas(WS, "Flow", CanvasKind.FLOW, [], NOW, canvas_id="c9")
    repo.put_new_canvas(canvas)
    stored = table.put_item.call_args.kwargs["Item"]
    table.get_item.return_value = {"Item": stored}
    loaded = repo.get_canvas(WS, "c9")
    assert loaded == canvas


def test_list_queries_only_this_workspaces_canvas_prefix():
    table = MagicMock()
    table.query.return_value = {"Items": []}
    CanvasRepository(table, "owner-1").list_canvases(WS)
    kwargs = table.query.call_args.kwargs
    expression = kwargs["KeyConditionExpression"].get_expression()
    parts = expression["values"]
    assert any(isinstance(part, BeginsWith) for part in parts)
    assert any(isinstance(part, Equals) for part in parts)
