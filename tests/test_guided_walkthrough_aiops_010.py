"""Structural and frozen-brief gates for the chaos engineering walkthrough draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / "aiops_010.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
STEP_TYPES = {"explanation", "add_component", "add_connection"}
CONNECTION_TYPES = {"api-call", "data-flow", "database-connection", "event-stream"}
EXPECTED_COMPONENTS = {
    "aiops010_pipeline": "ci-cd-pipeline",
    "aiops010_console": "web-app",
    "aiops010_gateway": "api-gateway",
    "aiops010_control": "backend-server",
    "aiops010_registry": "database",
    "aiops010_safety": "backend-server",
    "aiops010_scheduler": "backend-server",
    "aiops010_bus": "message-broker",
    "aiops010_runners": "processing-worker",
    "aiops010_targets": "backend-server",
    "aiops010_monitor": "monitoring",
    "aiops010_results": "database",
    "aiops010_training": "model-training",
    "aiops010_recommender": "ml-model",
    "aiops010_analytics": "analytics",
    "aiops010_scorecard": "web-app",
}
ANCHOR_COMPONENTS = {
    "legacy-requirement:1": "aiops010_control",
    "legacy-requirement:2": "aiops010_runners",
    "legacy-requirement:3": "aiops010_monitor",
    "legacy-requirement:4": "aiops010_safety",
    "legacy-requirement:5": "aiops010_recommender",
    "legacy-requirement:6": "aiops010_results",
    "legacy-requirement:7": "aiops010_scorecard",
    "legacy-requirement:8": "aiops010_pipeline",
    "legacy-constraint:1": "aiops010_safety",
    "legacy-constraint:2": "aiops010_scheduler",
    "legacy-constraint:3": "aiops010_safety",
    "legacy-constraint:4": "aiops010_scheduler",
    "legacy-constraint:5": "aiops010_analytics",
}


def load_problem():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == "aiops_010")


def load_guide():
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def test_frozen_brief_and_runtime_schema():
    problem = load_problem()
    guide = GuidedWalkthrough.model_validate(load_guide())

    assert problem["title"] == "Design an Automated Chaos Engineering Platform"
    assert len(problem["requirements"]) == 8
    assert len(problem["constraints"]) == 5
    assert problem["has_guided_walkthrough"] is False
    assert guide.problem_id == "aiops_010"
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 41

    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end
        assert phase.description
        assert all(guide.steps[number - 1].phase == phase.name for number in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1


def test_every_frozen_item_is_anchored_to_a_graph_action():
    problem = load_problem()
    guide = load_guide()
    expected_anchors = {
        *(f"legacy-requirement:{i}" for i in range(1, len(problem["requirements"]) + 1)),
        *(f"legacy-constraint:{i}" for i in range(1, len(problem["constraints"]) + 1)),
    }
    actions = [step for step in guide["steps"] if step["type"] in {"add_component", "add_connection"}]
    assert all(step["type"] in STEP_TYPES for step in guide["steps"])
    assert {anchor for step in guide["steps"] for anchor in step["requirementIds"]} == expected_anchors
    assert {anchor for step in actions for anchor in step["requirementIds"]} == expected_anchors

    for anchor, node_id in ANCHOR_COMPONENTS.items():
        step = next(
            row for row in guide["steps"]
            if row["type"] == "add_component" and row["component"]["nodeId"] == node_id
        )
        assert anchor in step["requirementIds"]


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
        if not node in reached:
            reached.add(node)
            pending.extend(adjacency[node] - reached)
    assert reached == nodes

    request = make_request(load_problem(), guide, built)
    problem = load_problem()
    assert request["problem"]["requirements"] == "\n".join(problem["requirements"])
    assert request["problem"]["constraints"] == "\n".join(problem["constraints"])
    assert request["problem"]["requirementRevision"].startswith("legacy-")
    assert len(request["components"]) == len(EXPECTED_COMPONENTS)
