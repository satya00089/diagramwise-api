"""Structural, palette, and brief-coverage checks for the demand forecast walkthrough."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "ml_010"
GUIDE_PATH = ROOT / "data/guided-walkthroughs/ml_010.json"
PROBLEMS_PATH = ROOT / "tests/fixtures/walkthroughs/problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic/src/config/components.ts"
CONNECTION_TYPES = {
    "api-call",
    "data-flow",
    "database-connection",
    "event-stream",
    "http",
    "message-queue",
}


def load_problem():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def load_guide():
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def test_walkthrough_schema_order_phases_and_all_legacy_anchors():
    raw = load_guide()
    guide = GuidedWalkthrough.model_validate(raw)
    problem = load_problem()

    assert guide.problem_id == PROBLEM_ID
    assert guide.totalSteps == len(guide.steps) == 46
    assert [step.stepNumber for step in guide.steps] == list(range(1, 47))
    assert len({step.id for step in guide.steps}) == 46

    expected_ids = {
        *(f"legacy-requirement:{index}" for index in range(1, len(problem["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(problem["constraints"]) + 1)),
    }
    mapped_ids = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert mapped_ids == expected_ids

    expected_start = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == expected_start
        assert start <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        expected_start = end + 1
    assert expected_start == guide.totalSteps + 1


def test_guide_replays_to_a_single_connected_save_reload_safe_graph():
    raw = load_guide()
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    components = {component["id"] for component in architecture["components"]}
    edges = architecture["connections"]

    assert len(components) == 17
    assert len(edges) == 20
    assert len(replay["appliedStepIds"]) == 37
    assert all(edge["source"] in components and edge["target"] in components for edge in edges)
    assert all(edge["type"] in CONNECTION_TYPES for edge in edges)

    neighbors = {component_id: set() for component_id in components}
    for edge in edges:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque([next(iter(components))])
    while pending:
        component_id = pending.popleft()
        if component_id in reached:
            continue
        reached.add(component_id)
        pending.extend(neighbors[component_id] - reached)
    assert reached == components


def test_components_reuse_catalog_ids_and_only_source_connectors_are_custom():
    raw = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step["type"] == "add_component"
    }
    assert len(additions) == 17

    custom_labels = {
        component["label"]
        for component in additions.values()
        if component["componentType"] == "custom-component"
    }
    assert custom_labels == {"Retail Source Connectors", "Weather & Economic Feeds"}
    # The catalog does not provide native retail or generic external-data connectors.
    assert 'id: "data-source"' not in catalog
    assert 'id: "external-api"' not in catalog

    for step in raw["steps"]:
        if step["type"] == "add_component":
            component_type = step["component"]["componentType"]
            properties = step["component"].get("properties", {})
        elif step.get("componentUpdate"):
            node_id = step["componentUpdate"]["nodeId"]
            component_type = additions[node_id]["componentType"]
            properties = step["componentUpdate"].get("properties", {})
        else:
            if step["type"] == "add_connection":
                connection = step["connection"]
                assert connection["sourceNodeId"] in additions
                assert connection["targetNodeId"] in additions
            continue

        match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
        assert match, f"{step['id']} uses unknown component ID {component_type!r}"
        block_end = catalog.find("\n  },", match.start())
        component_block = catalog[match.start():block_end]
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', component_block))
        assert {"componentName", "purpose"} <= set(properties)
        assert set(properties) <= supported, (
            f"{step['id']} uses unsupported {component_type} properties: "
            f"{sorted(set(properties) - supported)}"
        )


def test_walkthrough_teaches_each_forecasting_requirement_and_operational_gate():
    text = json.dumps(load_guide(), ensure_ascii=False).casefold()
    required_concepts = (
        "daily",
        "weekly",
        "monthly",
        "store",
        "region",
        "national",
        "seasonality",
        "holidays",
        "promotion",
        "price",
        "weather",
        "economic",
        "p10",
        "p50",
        "p90",
        "new products",
        "cold-start",
        "per series",
        "deepar",
        "temporal fusion transformer",
        "rolling-origin",
        "mape",
        "below 15%",
        "100k",
        "two hours",
        "90-day",
        "coherent",
        "reconcile",
    )
    for concept in required_concepts:
        assert concept in text, f"Walkthrough does not explicitly cover {concept!r}"

