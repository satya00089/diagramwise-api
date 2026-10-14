import pytest

from app.models.canvas_models import (
    MAX_CANVAS_NAME_LENGTH,
    MAX_CANVASES_PER_WORKSPACE,
    CanvasKind,
    CanvasRecord,
    CanvasValidationError,
    build_canvas,
    canvas_summary,
    dedupe_canvas_name,
    ensure_not_last_canvas,
    legacy_canvas_from_diagram,
    normalize_canvas_name,
    primary_canvas,
    validate_canvas_graph,
)

NOW = "2026-10-14T10:00:00+00:00"


def _canvas(canvas_id: str, name: str, order: int, deleted: bool = False) -> CanvasRecord:
    return CanvasRecord(
        id=canvas_id,
        workspaceId="ws-1",
        name=name,
        order=order,
        createdAt=NOW,
        updatedAt=NOW,
        deletedAt=NOW if deleted else None,
    )


def test_normalize_name_trims_and_collapses_whitespace():
    assert normalize_canvas_name("  High   level \t design ") == "High level design"


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_normalize_name_rejects_empty(raw):
    with pytest.raises(CanvasValidationError):
        normalize_canvas_name(raw)


def test_normalize_name_rejects_too_long():
    with pytest.raises(CanvasValidationError):
        normalize_canvas_name("x" * (MAX_CANVAS_NAME_LENGTH + 1))


def test_dedupe_is_case_insensitive_and_numbered():
    assert dedupe_canvas_name("ER", ["Flow"]) == "ER"
    assert dedupe_canvas_name("er", ["ER"]) == "er (2)"
    assert dedupe_canvas_name("ER", ["ER", "ER (2)"]) == "ER (3)"


def test_dedupe_keeps_result_within_length_limit():
    long_name = "x" * MAX_CANVAS_NAME_LENGTH
    result = dedupe_canvas_name(long_name, [long_name])
    assert len(result) <= MAX_CANVAS_NAME_LENGTH
    assert result.endswith(" (2)")


def test_validate_graph_accepts_consistent_canvas():
    nodes = [{"id": "a"}, {"id": "b"}]
    edges = [{"id": "e1", "source": "a", "target": "b"}]
    validate_canvas_graph(nodes, edges)


def test_validate_graph_rejects_duplicate_node_ids():
    with pytest.raises(CanvasValidationError, match="Duplicate node id"):
        validate_canvas_graph([{"id": "a"}, {"id": "a"}], [])


def test_validate_graph_rejects_cross_canvas_edge():
    nodes = [{"id": "a"}]
    edges = [{"id": "e1", "source": "a", "target": "elsewhere"}]
    with pytest.raises(CanvasValidationError, match="not on this canvas"):
        validate_canvas_graph(nodes, edges)


def test_validate_graph_rejects_node_without_id():
    with pytest.raises(CanvasValidationError):
        validate_canvas_graph([{"label": "no id"}], [])


def test_capacity_blocks_eleventh_canvas():
    existing = [_canvas(f"c{i}", f"Canvas {i}", i) for i in range(MAX_CANVASES_PER_WORKSPACE)]
    with pytest.raises(CanvasValidationError, match="at most"):
        build_canvas("ws-1", "One more", CanvasKind.FLOW, existing, NOW)


def test_build_canvas_appends_with_next_order_and_unique_name():
    existing = [_canvas("c1", "High level", 0), _canvas("c2", "Flow", 3)]
    created = build_canvas("ws-1", "flow", CanvasKind.FLOW, existing, NOW, canvas_id="c3")
    assert created.id == "c3"
    assert created.order == 4
    assert created.name == "flow (2)"
    assert created.version == 1
    assert created.nodes == [] and created.edges == []


def test_primary_canvas_is_lowest_active_order():
    canvases = [
        _canvas("gone", "Deleted", 0, deleted=True),
        _canvas("b", "B", 2),
        _canvas("a", "A", 1),
    ]
    assert primary_canvas(canvases).id == "a"


def test_primary_canvas_none_when_empty_or_all_deleted():
    assert primary_canvas([]) is None
    assert primary_canvas([_canvas("x", "X", 0, deleted=True)]) is None


def test_cannot_remove_last_active_canvas():
    with pytest.raises(CanvasValidationError, match="at least one"):
        ensure_not_last_canvas([_canvas("only", "Only", 0)])
    ensure_not_last_canvas([_canvas("a", "A", 0), _canvas("b", "B", 1)])


def test_legacy_diagram_becomes_single_canvas_with_same_id():
    canvas = legacy_canvas_from_diagram(
        "diag-123",
        nodes=[{"id": "n1"}],
        edges=[],
        created_at=NOW,
        updated_at=NOW,
    )
    assert canvas.id == "diag-123"
    assert canvas.name == "Main"
    assert canvas.order == 0
    assert canvas.nodes == [{"id": "n1"}]


def test_canvas_summary_omits_payload_and_counts_items():
    canvas = legacy_canvas_from_diagram(
        "d",
        nodes=[{"id": "a"}, {"id": "b"}],
        edges=[{"id": "e", "source": "a", "target": "b"}],
        created_at=NOW,
        updated_at=NOW,
    )
    summary = canvas_summary(canvas)
    assert summary["nodeCount"] == 2
    assert summary["edgeCount"] == 1
    assert "nodes" not in summary and "edges" not in summary
    assert summary["kind"] == "other"
