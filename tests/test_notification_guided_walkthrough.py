"""Structural, catalog, and requirement coverage checks for Notification System walkthrough."""

import json
import re
from collections import deque
from pathlib import Path

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture

ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "data/guided-walkthroughs/68d7013f6f42e23bb16a2233.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    guide = GuidedWalkthrough.model_validate(raw)
    return raw, guide


def test_notification_walkthrough_has_complete_ordered_phases_and_actions():
    raw, guide = load_guide()

    assert guide.problem_id == "68d7013f6f42e23bb16a2233"
    assert guide.totalSteps == len(guide.steps)
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps

    expected_start = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == expected_start
        assert start <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        expected_start = end + 1
    assert expected_start == guide.totalSteps + 1

    applied = build_architecture(raw)
    architecture = applied["architecture"]
    components = {component["id"] for component in architecture["components"]}
    assert len(components) >= 20
    assert len(architecture["connections"]) >= 30
    assert len(applied["appliedStepIds"]) > len(applied["explanationOnlyStepIds"])

    # The applied architecture is one connected graph, with no dangling nodes or edges.
    neighbors = {component_id: set() for component_id in components}
    for edge in architecture["connections"]:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    visited = set()
    pending = deque([next(iter(components))])
    while pending:
        node_id = pending.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        pending.extend(neighbors[node_id] - visited)
    assert visited == components


def test_notification_walkthrough_covers_each_brief_requirement_and_constraint():
    raw, _ = load_guide()
    searchable = json.dumps(raw, ensure_ascii=False).casefold()

    required_signals = (
        "email",
        "sms",
        "push",
        "in-app",
        "marketing",
        "transactional",
        "alerts",
        "opt-out",
        "template",
        "delivery",
        "analytics",
        "rate",
        "million",
        "p95",
        "retry",
        "dead-letter",
        "privacy",
        "experiment",
        "spike",
    )
    for signal in required_signals:
        assert signal in searchable, f"Walkthrough does not explicitly cover {signal!r}"


def test_notification_walkthrough_uses_existing_palette_ids_and_supported_properties():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step.get("type") == "add_component"
    }
    assert additions
    assert all(component["componentType"] != "custom-component" for component in additions.values())

    for step in raw["steps"]:
        if step.get("type") == "add_component":
            component = step["component"]
            component_type = component["componentType"]
            properties = component.get("properties", {})
        elif step.get("componentUpdate"):
            component_type = additions[step["componentUpdate"]["nodeId"]]["componentType"]
            properties = step["componentUpdate"].get("properties", {})
        else:
            continue

        match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
        assert match is not None, f"{step['id']} uses unknown palette id {component_type!r}"
        block_end = catalog.find("\n  },", match.start())
        block = catalog[match.start():block_end]
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert set(properties) <= supported, (
            f"{step['id']} has unsupported properties "
            f"{sorted(set(properties) - supported)}"
        )


def test_notification_walkthrough_anchors_exactly_cover_frozen_brief_on_graph_actions():
    raw, _ = load_guide()
    frozen_problems = json.loads(
        (ROOT / "tests/fixtures/walkthroughs/problems.json").read_text(encoding="utf-8")
    )
    frozen_problem = next(
        problem for problem in frozen_problems if problem["id"] == raw["problem_id"]
    )
    expected_anchors = {
        *(f"legacy-requirement:{index}" for index in range(1, len(frozen_problem["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(frozen_problem["constraints"]) + 1)),
    }
    graph_action_types = {"add_component", "add_connection", "update_component"}
    graph_actions = [step for step in raw["steps"] if step["type"] in graph_action_types]
    all_anchors = {
        anchor for step in raw["steps"] for anchor in step.get("requirementIds", [])
    }
    graph_action_anchors = {
        anchor for step in graph_actions for anchor in step.get("requirementIds", [])
    }

    assert all_anchors == expected_anchors
    assert graph_action_anchors == expected_anchors
    assert all(
        not step.get("requirementIds")
        for step in raw["steps"]
        if step["type"] not in graph_action_types
    )


def test_notification_anchors_match_the_behavior_of_the_tagged_action():
    raw, _ = load_guide()
    steps = {step["id"]: step for step in raw["steps"]}

    assert steps["notif_04"]["requirementIds"] == ["legacy-requirement:6"]
    assert set(steps["notif_07"]["requirementIds"]) == {
        "legacy-requirement:2",
        "legacy-requirement:6",
    }
    # Client-command deduplication is distinct from delivery-failure retries.
    assert steps["notif_13"].get("requirementIds", []) == []
    assert set(steps["notif_16"]["requirementIds"]) == {
        "legacy-requirement:4",
        "legacy-constraint:4",
    }
    assert steps["notif_21"]["requirementIds"] == ["legacy-constraint:4"]
    assert set(steps["notif_38"]["requirementIds"]) == {
        "legacy-requirement:3",
        "legacy-constraint:3",
    }
    assert all(
        steps[step_id]["requirementIds"] == ["legacy-constraint:2"]
        for step_id in ("notif_51", "notif_52", "notif_53", "notif_54", "notif_55")
    )


def test_notification_numeric_claims_are_sourced_or_labeled_as_assumptions():
    raw, _ = load_guide()
    frozen_problems = json.loads(
        (ROOT / "tests/fixtures/walkthroughs/problems.json").read_text(encoding="utf-8")
    )
    frozen_problem = next(
        problem for problem in frozen_problems if problem["id"] == raw["problem_id"]
    )
    brief_text = json.dumps(frozen_problem, ensure_ascii=False).casefold()
    by_id = {step["id"]: step for step in raw["steps"]}

    assert "millions" in brief_text
    assert "10 million" not in brief_text
    sizing = by_id["notif_01"]["content"].casefold()
    assert "assume 10 million notification requests/day" in sizing
    assert "10x peak" in sizing
    assert "about 116 requests/second average" in sizing
    assert "1,160 at peak" in sizing
    assert "about 4,640 channel delivery attempts/second" in sizing
    assert "under 100ms p95 as a provisional goal" in sizing

    delivery_target = by_id["notif_24"]["content"].casefold()
    assert "95%" in delivery_target and "five seconds" in delivery_target
    assert "provisional goal" in delivery_target

    configuration_note = by_id["notif_74"]["content"].casefold()
    for setting in (
        "shard and replica counts",
        "worker concurrency",
        "cache ttl",
        "queue visibility and retry budgets",
        "event partitions and retention",
        "analytics sampling and retention",
        "monitoring retention",
        "illustrative configuration assumptions",
    ):
        assert setting in configuration_note
