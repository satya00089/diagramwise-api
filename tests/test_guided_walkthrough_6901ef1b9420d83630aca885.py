"""Structural and frozen-brief checks for the ETA/location review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca885"
GUIDE_PATH = ROOT / "data/guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests/fixtures/walkthroughs/problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic/src/config/components.ts"


def load_frozen_brief() -> dict:
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    matches = [row for row in problems if row.get("id") == PROBLEM_ID]
    assert len(matches) == 1, f"Expected one frozen brief for {PROBLEM_ID}"
    return matches[0]


FROZEN_BRIEF = load_frozen_brief()
EXPECTED_ANCHORS = {
    *(f"legacy-requirement:{index}" for index in range(1, len(FROZEN_BRIEF["requirements"]) + 1)),
    *(f"legacy-constraint:{index}" for index in range(1, len(FROZEN_BRIEF["constraints"]) + 1)),
}
ACTION_TYPES = {"add_component", "add_connection", "update_component"}
STEP_TYPES = {"explanation", "add_component", "add_connection", "decision_point", "scale_trigger", "update_component"}
ANCHOR_EVIDENCE = {
    "legacy-requirement:1": ("arrival time", "route alternatives"),
    "legacy-requirement:2": ("location", "trip"),
    "legacy-requirement:3": ("recompute", "trip state"),
    "legacy-requirement:4": ("alternative route algorithms",),
    "legacy-requirement:5": ("large", "active-trip"),
    "legacy-requirement:6": ("trip", "sharing permissions"),
    "legacy-requirement:7": ("battery", "sampling"),
    "legacy-requirement:8": ("historical traffic",),
    "legacy-constraint:1": ("every few seconds",),
    "legacy-constraint:2": ("estimate arrival",),
    "legacy-constraint:3": ("gps", "map-match"),
    "legacy-constraint:4": ("low-latency", "trip"),
    "legacy-constraint:5": ("battery", "sampling"),
}


def load_rows() -> tuple[dict, dict]:
    return FROZEN_BRIEF, json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"{step_id}: unknown component type {component_type}"
    end = catalog.find("\n  },", match.start())
    assert end > match.start(), f"{step_id}: incomplete catalog entry"
    return catalog[match.start() : end]


def test_frozen_brief_matches_the_candidate_scope():
    problem, raw = load_rows()
    assert problem["id"] == PROBLEM_ID
    assert raw["problem_id"] == problem["id"]
    assert set(ANCHOR_EVIDENCE) == EXPECTED_ANCHORS
    assert "has_guided_walkthrough" not in raw


def test_schema_phases_and_all_brief_anchors_have_action_evidence():
    _, raw = load_rows()
    guide = GuidedWalkthrough.model_validate(raw)
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 33
    assert [step.stepNumber for step in guide.steps] == list(range(1, 34))
    assert len({step.id for step in guide.steps}) == 33
    assert all(step.type in STEP_TYPES and step.title.strip() and step.content.strip() for step in guide.steps)

    next_number = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_number <= end <= guide.totalSteps
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_number = end + 1
    assert next_number == guide.totalSteps + 1

    mapped = {anchor for step in raw["steps"] for anchor in step.get("requirementIds", [])}
    actionable = {
        anchor
        for step in raw["steps"]
        if step["type"] in ACTION_TYPES
        for anchor in step.get("requirementIds", [])
    }
    assert mapped == actionable == EXPECTED_ANCHORS
    for anchor, phrases in ANCHOR_EVIDENCE.items():
        carriers = [
            step for step in raw["steps"]
            if step["type"] in ACTION_TYPES and anchor in step.get("requirementIds", [])
        ]
        assert any(all(phrase in json.dumps(step, ensure_ascii=False).casefold() for phrase in phrases) for step in carriers), anchor


def test_components_use_catalog_ids_and_supported_properties():
    _, raw = load_rows()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}
    for step in raw["steps"]:
        if step["type"] != "add_component":
            continue
        component = step["component"]
        assert component["nodeId"] not in components
        assert set(component["position"]) == {"x", "y"}
        properties = component["properties"]
        assert set(properties) == {"componentName", "purpose"}
        assert properties["componentName"] == component["label"]
        assert properties["purpose"].strip()
        block = catalog_block(catalog, component["componentType"], step["id"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert set(properties) <= supported
        components[component["nodeId"]] = component
    assert len(components) == 12


def test_ordered_actions_replay_to_one_connected_graph():
    _, raw = load_rows()
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    node_ids = {step["component"]["nodeId"] for step in raw["steps"] if step["type"] == "add_component"}
    edges = [step["connection"] for step in raw["steps"] if step["type"] == "add_connection"]
    assert {component["id"] for component in architecture["components"]} == node_ids
    assert len(architecture["components"]) == 12
    assert len(architecture["connections"]) == len(edges) == 17
    assert len(replay["appliedStepIds"]) == 29

    neighbors = {node_id: set() for node_id in node_ids}
    for edge in edges:
        neighbors[edge["sourceNodeId"]].add(edge["targetNodeId"])
        neighbors[edge["targetNodeId"]].add(edge["sourceNodeId"])
    reached, pending = set(), deque(["eta_mobile"])
    while pending:
        current = pending.popleft()
        if current in reached:
            continue
        reached.add(current)
        pending.extend(neighbors[current] - reached)
    assert reached == node_ids


def test_eta_predictions_and_historical_traffic_reach_their_consumers():
    _, raw = load_rows()
    connections = {
        (step["connection"]["sourceNodeId"], step["connection"]["targetNodeId"]): step
        for step in raw["steps"]
        if step["type"] == "add_connection"
    }

    prediction = connections[("eta_model", "eta_trip")]
    assert set(prediction["requirementIds"]) == {
        "legacy-requirement:1",
        "legacy-requirement:3",
    }
    assert "predicted eta" in prediction["content"].casefold()

    historical_traffic = connections[("eta_history", "eta_routing")]
    assert set(historical_traffic["requirementIds"]) == {
        "legacy-requirement:1",
        "legacy-requirement:8",
    }
    assert "historical traffic" in historical_traffic["content"].casefold()

    by_id = {step["id"]: step for step in raw["steps"]}
    cache_step = json.dumps(by_id["eta_loc_s16"], ensure_ascii=False).casefold()
    rider_update_step = json.dumps(by_id["eta_loc_s26"], ensure_ascii=False).casefold()
    assert "geospatial indexing" in cache_step
    assert "interpolate" in rider_update_step
