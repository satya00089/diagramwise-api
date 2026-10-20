"""Frozen-brief, catalog-property, and connected replay checks for surge pricing."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca883"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

STEP_TYPES = {
    "explanation", "add_component", "add_connection", "decision_point",
    "scale_trigger", "update_component", "conclusion",
}
ACTION_TYPES = {"add_component", "add_connection", "update_component"}
CONNECTION_TYPES = {
    "api-call", "event-stream", "message-queue", "database-connection", "data-flow",
}
EXPECTED_COMPONENT_COUNT = 11
EXPECTED_CONNECTION_COUNT = 17


def load_candidate():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    matches = [problem for problem in problems if problem["id"] == PROBLEM_ID]
    assert len(matches) == 1, f"expected one frozen problem brief for {PROBLEM_ID}"
    return raw, GuidedWalkthrough.model_validate(raw), matches[0]


def catalog_component_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'(?m)^\s*id:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"unknown catalog component type {component_type!r}"
    end = catalog.find("\n  },", match.start())
    assert end != -1, f"could not find catalog block end for {component_type!r}"
    return catalog[match.start() : end]


def expected_anchors(problem: dict) -> set[str]:
    return {
        *(f"legacy-requirement:{index}" for index, _ in enumerate(problem["requirements"], 1)),
        *(f"legacy-constraint:{index}" for index, _ in enumerate(problem["constraints"], 1)),
    }


def test_schema_matches_frozen_brief_and_has_no_embedded_publication_flag():
    raw, guide, problem = load_candidate()
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 33
    assert [step.stepNumber for step in guide.steps] == list(range(1, 34))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES and step.content.strip() for step in guide.steps)

    brief = guide.steps[0].content
    exact_values = [
        problem["title"], problem["slug"], problem["description"],
        problem["difficulty"], problem["category"], problem["domain"],
        problem["estimatedTime"], *problem["requirements"], *problem["constraints"],
        *problem["hints"], *problem["tags"], *problem["companies"],
    ]
    for exact_value in exact_values:
        assert exact_value in brief, f"frozen brief value missing: {exact_value}"
    serialized = json.dumps(raw, ensure_ascii=False)
    assert "has_guided_walkthrough" not in serialized


def test_phase_ranges_and_every_requirement_constraint_has_a_replayable_action():
    _, guide, problem = load_candidate()
    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    expected = expected_anchors(problem)
    actual = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert actual == expected
    for anchor in expected:
        assert any(
            step.type in ACTION_TYPES and anchor in step.requirementIds
            for step in guide.steps
        ), f"{anchor} is only described, not tied to a replayable action"


def test_all_added_nodes_use_existing_catalog_ids_and_supported_properties():
    raw, _, problem = load_candidate()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = [step["component"] for step in raw["steps"] if step["type"] == "add_component"]
    assert len(components) == EXPECTED_COMPONENT_COUNT
    assert len({component["nodeId"] for component in components}) == EXPECTED_COMPONENT_COUNT
    assert all(component["componentType"] != "custom-component" for component in components)

    for component in components:
        block = catalog_component_block(catalog, component["componentType"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert {"componentName", "purpose"} <= set(component["properties"])
        assert set(component["properties"]) <= supported, component["nodeId"]
        assert component["description"].strip()
        assert component["highlightReason"].strip()

    brief_requirements = " ".join(problem["requirements"] + problem["constraints"])
    broker = next(component for component in components if component["nodeId"] == "surge_event_bus")
    if not re.search(r"\breplication\b.{0,20}\d|\d.{0,20}\breplication\b", brief_requirements, re.I):
        assert "replication" not in broker["properties"], (
            "the frozen brief does not specify a broker replication factor"
        )


def test_ordered_actions_replay_to_one_connected_graph():
    raw, guide, _ = load_candidate()
    assert all(step.type in STEP_TYPES for step in guide.steps)
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    components = architecture["components"]
    connections = architecture["connections"]
    node_ids = {component["id"] for component in components}

    assert len(components) == EXPECTED_COMPONENT_COUNT
    assert len(connections) == EXPECTED_CONNECTION_COUNT
    assert node_ids == {
        step["component"]["nodeId"] for step in raw["steps"] if step["type"] == "add_component"
    }
    assert len(replay["appliedStepIds"]) == EXPECTED_COMPONENT_COUNT + EXPECTED_CONNECTION_COUNT
    assert all(edge["source"] in node_ids and edge["target"] in node_ids for edge in connections)
    assert all(edge["type"] in CONNECTION_TYPES for edge in connections)

    adjacency = {node_id: set() for node_id in node_ids}
    for edge in connections:
        adjacency[edge["source"]].add(edge["target"])
        adjacency[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque([next(iter(node_ids))])
    while pending:
        node_id = pending.popleft()
        if node_id in reached:
            continue
        reached.add(node_id)
        pending.extend(adjacency[node_id] - reached)
    assert reached == node_ids

    props = {component["id"]: component["properties"] for component in components}
    assert props["surge_zone_aggregator"]["stateful"] is True
    assert "millions-per-minute" in props["surge_zone_aggregator"]["purpose"]
    assert "protected attributes" in props["surge_pricing_engine"]["purpose"]
    assert "last-approved fallback" in props["surge_price_cache"]["purpose"]
    assert "version" in props["surge_quote_api"]["purpose"]
