from __future__ import annotations

from scripts.migrate_description_to_purpose import (
    _migrate_canvas_item,
    _migrate_catalog_item,
    new_report,
)


def test_migrates_nodes_and_edges_without_touching_top_level_description():
    report = new_report("diagrams")
    item = {
        "userId": "u1",
        "id": "d1",
        "description": "diagram metadata",
        "nodes": [
            {"id": "n1", "data": {"description": "stores data"}},
            {
                "id": "n2",
                "data": {"properties": {"description": "legacy nested"}},
            },
        ],
        "edges": [{"id": "e1", "data": {"description": "carries reads"}}],
    }

    updated, changed, skipped = _migrate_canvas_item(item, report)

    assert changed is True
    assert skipped is False
    assert updated["description"] == "diagram metadata"
    assert updated["nodes"][0]["data"] == {"purpose": "stores data"}
    assert updated["nodes"][1]["data"]["properties"] == {"purpose": "legacy nested"}
    assert updated["edges"][0]["data"] == {"purpose": "carries reads"}


def test_purpose_wins_conflicts_and_second_run_is_idempotent():
    item = {
        "nodes": [{"data": {"purpose": "new", "description": "old"}}],
        "edges": [{"data": {"purpose": "new flow", "description": "old flow"}}],
    }
    report = new_report("diagrams")
    updated, changed, _ = _migrate_canvas_item(item, report)

    assert changed is True
    assert updated["nodes"][0]["data"] == {"purpose": "new"}
    assert updated["edges"][0]["data"] == {"purpose": "new flow"}
    assert len(report["conflicts"]) == 2

    second_report = new_report("diagrams")
    second, changed_again, _ = _migrate_canvas_item(updated, second_report)
    assert second == updated
    assert changed_again is False
    assert second_report["migrated_fields"] == 0


def test_catalog_migration_preserves_special_fields_and_metadata():
    report = new_report("components")
    item = {
        "platform": "aws",
        "id": "x",
        "description": "catalog description",
        "properties": [
            {"key": "description", "label": "Description"},
            {"key": "description", "label": "Body"},
            {"key": "description", "label": "Content"},
        ],
    }

    updated, changed, skipped = _migrate_catalog_item(item, report)

    assert changed is True
    assert skipped is False
    assert updated["description"] == "catalog description"
    assert updated["properties"][0]["key"] == "purpose"
    assert updated["properties"][0]["label"] == "Purpose"
    assert updated["properties"][1]["key"] == "description"
    assert updated["properties"][2]["key"] == "description"
