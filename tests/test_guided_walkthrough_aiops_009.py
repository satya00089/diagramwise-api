"""Structural and frozen-brief gates for the SLA monitoring walkthrough draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / "aiops_009.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
STEP_TYPES = {"explanation", "add_component", "add_connection"}
CONNECTION_TYPES = {"api-call", "data-flow", "database-connection", "event-stream"}
EXPECTED_COMPONENTS = {
    "aiops009_targets": "backend-server",
    "aiops009_collectors": "processing-worker",
    "aiops009_dashboard": "web-app",
    "aiops009_gateway": "api-gateway",
    "aiops009_control": "backend-server",
    "aiops009_registry": "database",
    "aiops009_bus": "message-broker",
    "aiops009_evaluator": "backend-server",
    "aiops009_metrics": "database",
    "aiops009_training": "model-training",
    "aiops009_forecaster": "ml-model",
    "aiops009_response": "backend-server",
    "aiops009_reports": "analytics",
}
ANCHOR_COMPONENTS = {
    "legacy-requirement:1": "aiops009_collectors",
    "legacy-requirement:2": "aiops009_evaluator",
    "legacy-requirement:3": "aiops009_forecaster",
    "legacy-requirement:4": "aiops009_forecaster",
    "legacy-requirement:5": "aiops009_registry",
    "legacy-requirement:6": "aiops009_reports",
    "legacy-requirement:7": "aiops009_response",
    "legacy-requirement:8": "aiops009_registry",
    "legacy-constraint:1": "aiops009_collectors",
    "legacy-constraint:2": "aiops009_training",
    "legacy-constraint:3": "aiops009_registry",
    "legacy-constraint:4": "aiops009_evaluator",
    "legacy-constraint:5": "aiops009_dashboard",
}


def load_problem():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == "aiops_009")


def load_guide():
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def test_frozen_brief_and_runtime_schema():
    problem = load_problem()
    guide = GuidedWalkthrough.model_validate(load_guide())

    assert problem["title"] == "Design a Smart SLA Monitoring and Prediction System"
    assert len(problem["requirements"]) == 8
    assert len(problem["constraints"]) == 5
    assert problem["has_guided_walkthrough"] is False
    assert guide.problem_id == "aiops_009"
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 38

    expected_step_numbers = list(range(1, guide.totalSteps + 1))
    assert [step.stepNumber for step in guide.steps] == expected_step_numbers
    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end
        assert phase.description
        assert all(guide.steps[number - 1].phase == phase.name for number in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1


def test_every_frozen_item_is_anchored_to_a_graph_action():
    guide = load_guide()
    expected_anchors = {
        *(f"legacy-requirement:{i}" for i in range(1, len(load_problem()["requirements"]) + 1)),
        *(f"legacy-constraint:{i}" for i in range(1, len(load_problem()["constraints"]) + 1)),
    }
    actions = [step for step in guide["steps"] if step["type"] in {"add_component", "add_connection"}]
    assert all(step["type"] in STEP_TYPES for step in guide["steps"])
    assert {anchor for step in guide["steps"] for anchor in step["requirementIds"]} == expected_anchors
    assert {anchor for step in actions for anchor in step["requirementIds"]} == expected_anchors

    components = {
        step["component"]["nodeId"]: step["component"]
        for step in guide["steps"]
        if step["type"] == "add_component"
    }
    for anchor, node_id in ANCHOR_COMPONENTS.items():
        assert anchor in next(
            step["requirementIds"] for step in guide["steps"]
            if step["type"] == "add_component" and step["component"]["nodeId"] == node_id
        )


def test_catalog_components_and_properties_replay_as_one_connected_graph():
    guide = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}
    for step in guide["steps"]:
        if step["type"] != "add_component":
            continue
        component = step["component"]
        node_id = component["nodeId"]
        assert node_id not in components
        assert component["properties"] == {
            "componentName": component["label"], "purpose": component["description"]
        }
        components[node_id] = component
        match = re.search(rf'\bid:\s*"{re.escape(component["componentType"])}"', catalog)
        assert match, f"Unknown catalog ID: {component['componentType']}"
        block_end = catalog.find("\n  },", match.start())
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', catalog[match.start():block_end]))
        assert set(component["properties"]) <= supported

    assert {node: row["componentType"] for node, row in components.items()} == EXPECTED_COMPONENTS
    built = build_architecture(guide)
    architecture = built["architecture"]
    nodes = {row["id"] for row in architecture["components"]}
    edges = architecture["connections"]
    assert nodes == set(EXPECTED_COMPONENTS)
    assert len(edges) == 20
    assert len({edge["id"] for edge in edges}) == len(edges)
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in edges)
    assert all(edge["type"] in CONNECTION_TYPES for edge in edges)

    adjacency = {node: set() for node in nodes}
    for edge in edges:
        adjacency[edge["source"]].add(edge["target"])
        adjacency[edge["target"]].add(edge["source"])
    reached, pending = set(), deque([next(iter(nodes))])
    while pending:
        node = pending.popleft()
        if node not in reached:
            reached.add(node)
            pending.extend(adjacency[node] - reached)
    assert reached == nodes

    request = make_request(load_problem(), guide, built)
    assert request["problem"]["requirements"] == "\n".join(load_problem()["requirements"])
    assert request["problem"]["constraints"] == "\n".join(load_problem()["constraints"])
    assert request["problem"]["requirementRevision"].startswith("legacy-")
    assert len(request["components"]) == len(EXPECTED_COMPONENTS)
