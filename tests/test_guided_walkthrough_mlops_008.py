"""Structural review-draft checks for the data labeling walkthrough."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "mlops_008"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
CONNECTION_TYPES = {
    "api-call",
    "data-flow",
    "database-connection",
    "event-stream",
    "message-queue",
}
GRAPH_ACTIONS = {"add_component", "add_connection", "update_component"}


def load_problem() -> dict:
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def load_guide() -> dict:
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def catalog_component_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'(?m)^\s*id:\s*"{re.escape(component_type)}"', catalog)
    assert match, f"unknown catalog component type {component_type!r}"
    end = catalog.find("\n  },", match.start())
    assert end != -1, f"could not locate catalog block end for {component_type!r}"
    return catalog[match.start() : end]


def expected_anchors(problem: dict) -> set[str]:
    return {
        *(f"legacy-requirement:{index}" for index in range(1, len(problem["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(problem["constraints"]) + 1)),
    }


def test_opening_step_preserves_the_frozen_brief_and_names_hint_status():
    problem = load_problem()
    raw = load_guide()
    opening = raw["steps"][0]

    assert raw["problem_id"] == problem["id"] == PROBLEM_ID
    assert opening["stepNumber"] == 1
    assert opening["type"] == "explanation"
    content = opening["content"].casefold()
    for field in ("title", "slug", "description", "difficulty", "category", "domain", "estimated_time"):
        assert str(problem[field]).casefold() in content, f"frozen field missing: {field}"
    for field in ("requirements", "constraints", "hints", "tags", "companies"):
        for item in problem[field]:
            assert str(item).casefold() in content, f"frozen {field} item missing: {item}"
    assert "has_guided_walkthrough" not in content
    assert "hints are candidate approaches, not additional requirements" in content


def test_schema_phases_and_all_frozen_anchors_have_graph_actions():
    raw = load_guide()
    guide = GuidedWalkthrough.model_validate(raw)

    assert guide.problem_id == PROBLEM_ID
    assert guide.version.endswith("review-draft")
    assert guide.totalSteps == len(guide.steps) == 36
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(
        step.type
        in {"explanation", "add_component", "add_connection", "decision_point", "scale_trigger"}
        for step in guide.steps
    )

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(guide.steps[number - 1].phase == phase.name for number in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    expected = expected_anchors(load_problem())
    actual = {anchor for step in raw["steps"] for anchor in step["requirementIds"]}
    assert actual == expected
    for anchor in expected:
        assert any(
            step["type"] in GRAPH_ACTIONS and anchor in step["requirementIds"]
            for step in raw["steps"]
        ), f"{anchor} is not attached to a replayable graph action"


def test_catalog_properties_and_ordered_replay_form_one_connected_graph():
    raw = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = [step["component"] for step in raw["steps"] if step["type"] == "add_component"]
    connections = [step["connection"] for step in raw["steps"] if step["type"] == "add_connection"]

    assert len(additions) == 12
    assert len(connections) == 13
    assert len({component["nodeId"] for component in additions}) == len(additions)
    for component in additions:
        block = catalog_component_block(catalog, component["componentType"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        properties = set(component["properties"])
        assert {"componentName", "purpose"} <= properties
        assert properties <= supported, f"unsupported keys on {component['nodeId']}: {properties - supported}"
        assert component["label"].strip()
        assert component["description"].strip()
        assert component["highlightReason"].strip()

    seen_nodes: set[str] = set()
    seen_edges: set[str] = set()
    for step in raw["steps"]:
        if step["type"] == "add_component":
            node_id = step["component"]["nodeId"]
            assert node_id not in seen_nodes
            seen_nodes.add(node_id)
        elif step["type"] == "add_connection":
            edge = step["connection"]
            assert edge["sourceNodeId"] in seen_nodes
            assert edge["targetNodeId"] in seen_nodes
            assert edge["sourceNodeId"] != edge["targetNodeId"]
            assert edge["edgeId"] not in seen_edges
            assert edge["connectionType"] in CONNECTION_TYPES
            seen_edges.add(edge["edgeId"])

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {component["id"] for component in architecture["components"]}
    edges = architecture["connections"]
    assert nodes == {component["nodeId"] for component in additions}
    assert len(edges) == len(connections)
    assert len(replay["appliedStepIds"]) == len(additions) + len(connections)
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in edges)

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached: set[str] = set()
    pending = deque([next(iter(nodes))])
    while pending:
        current = pending.popleft()
        if current in reached:
            continue
        reached.add(current)
        pending.extend(neighbors[current] - reached)
    assert reached == nodes
