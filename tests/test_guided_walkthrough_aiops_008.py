"""Local structural and frozen-brief gates for the AIOps change-risk draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / "aiops_008.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

REQUIREMENTS = [
    "Analyze historical change-incident correlations",
    "Score risk for proposed changes",
    "Identify high-risk change combinations",
    "Recommend optimal deployment windows",
    "Predict blast radius of proposed changes",
    "Track change success rate by type and team",
    "Enforce change policies based on risk scores",
    "Integrate with CI/CD and change management tools",
]
CONSTRAINTS = [
    "Risk scoring latency under 30 seconds",
    "Risk prediction accuracy above 85%",
    "Handle 1000+ changes per day",
    "Reduce change-related incidents by 40%",
    "Support automated approval for low-risk changes",
]
STEP_TYPES = {"explanation", "add_component", "add_connection"}
CONNECTION_TYPES = {"api-call", "data-flow", "database-connection", "event-stream"}
EXPECTED_COMPONENTS = {
    "aiops008_ci_cd": "ci-cd-pipeline",
    "aiops008_release_sources": "release-management",
    "aiops008_gateway": "api-gateway",
    "aiops008_intake": "backend-server",
    "aiops008_event_bus": "message-broker",
    "aiops008_history": "database",
    "aiops008_dependency_graph": "database",
    "aiops008_feature_store": "feature-store",
    "aiops008_training": "model-training",
    "aiops008_model": "ml-model",
    "aiops008_analytics": "analytics",
    "aiops008_monitoring": "monitoring",
    "aiops008_risk_analysis": "backend-server",
    "aiops008_policy": "backend-server",
}


def load_problem():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == "aiops_008")


def load_guide():
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def test_live_frozen_brief_and_walkthrough_schema():
    problem = load_problem()
    guide = GuidedWalkthrough.model_validate(load_guide())

    assert problem["title"] == "Design an AI-Driven Change Risk Assessment System"
    assert problem["description"] == (
        "Design a system that uses ML to assess the risk of production changes "
        "(deployments, config changes, infrastructure updates), predicts potential "
        "impact, and recommends safe deployment windows."
    )
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert problem["has_guided_walkthrough"] is False
    assert guide.problem_id == "aiops_008"
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 40


def test_all_brief_items_are_anchored_to_replayable_actions():
    guide = load_guide()
    steps = guide["steps"]
    assert [step["stepNumber"] for step in steps] == list(range(1, 41))
    assert len({step["id"] for step in steps}) == len(steps)
    assert all(step["type"] in STEP_TYPES for step in steps)

    next_step = 1
    for phase in guide["phases"]:
        start, end = phase["stepRange"]
        assert start == next_step
        assert start <= end
        assert phase["description"]
        assert all(steps[number - 1]["phase"] == phase["name"] for number in range(start, end + 1))
        next_step = end + 1
    assert next_step == 41
    assert len(guide["phases"]) == 4

    counts = {kind: sum(step["type"] == kind for step in steps) for kind in STEP_TYPES}
    assert counts == {"explanation": 3, "add_component": 14, "add_connection": 23}
    for step in steps:
        if step["type"] == "add_component":
            assert step["component"]["highlightReason"]
        elif step["type"] == "add_connection":
            assert step["connection"]["description"]

    expected_anchors = {
        *(f"legacy-requirement:{number}" for number in range(1, len(REQUIREMENTS) + 1)),
        *(f"legacy-constraint:{number}" for number in range(1, len(CONSTRAINTS) + 1)),
    }
    action_steps = [step for step in steps if step["type"] in {"add_component", "add_connection"}]
    action_anchors = {anchor for step in action_steps for anchor in step["requirementIds"]}
    all_anchors = {anchor for step in steps for anchor in step["requirementIds"]}
    assert all_anchors == expected_anchors
    assert action_anchors == expected_anchors

    # Keep the design targets tied to concrete architecture decisions, not just prose.
    for anchor, node_id in (
        ("legacy-requirement:1", "aiops008_history"),
        ("legacy-requirement:2", "aiops008_model"),
        ("legacy-requirement:3", "aiops008_risk_analysis"),
        ("legacy-requirement:4", "aiops008_risk_analysis"),
        ("legacy-requirement:5", "aiops008_dependency_graph"),
        ("legacy-requirement:6", "aiops008_analytics"),
        ("legacy-requirement:7", "aiops008_policy"),
        ("legacy-requirement:8", "aiops008_gateway"),
    ):
        step = next(
            step for step in steps
            if step["type"] == "add_component" and step["component"]["nodeId"] == node_id
        )
        assert anchor in step["requirementIds"]


def test_every_node_and_property_comes_from_the_frontend_catalog():
    guide = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}

    for step in guide["steps"]:
        if step["type"] != "add_component":
            continue
        component = step["component"]
        node_id = component["nodeId"]
        assert node_id not in components
        assert component["componentType"] != "custom-component"
        assert component["properties"]["componentName"] == component["label"]
        assert component["properties"]["purpose"] == component["description"]
        components[node_id] = component

        component_type = component["componentType"]
        match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
        assert match, f"{step['id']} uses unknown catalog ID {component_type}"
        block_end = catalog.find("\n  },", match.start())
        assert block_end > match.start()
        component_block = catalog[match.start():block_end]
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', component_block))
        properties = component["properties"]
        assert set(properties) <= supported, (
            f"{step['id']} has unsupported {component_type} properties "
            f"{sorted(set(properties) - supported)}"
        )

    assert {node_id: row["componentType"] for node_id, row in components.items()} == EXPECTED_COMPONENTS


def test_action_replay_produces_a_connected_graph_and_frozen_assessment_request():
    guide = load_guide()
    problem = load_problem()
    built = build_architecture(guide)
    architecture = built["architecture"]
    nodes = {component["id"] for component in architecture["components"]}
    edges = architecture["connections"]

    assert nodes == set(EXPECTED_COMPONENTS)
    assert len(edges) == 23
    assert len(built["appliedStepIds"]) == 37
    assert len(built["explanationOnlyStepIds"]) == 3
    assert all(edge["type"] in CONNECTION_TYPES for edge in edges)
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in edges)
    history = next(row for row in architecture["components"] if row["id"] == "aiops008_history")
    assert "conditional reservations" in history["properties"]["purpose"]
    collision_read = next(edge for edge in edges if edge["id"] == "aiops008_history_risk")
    assert "atomically" in collision_read["description"]
    assert "concurrent assessments" in collision_read["description"]
    assert {
        ("aiops008_ci_cd", "aiops008_gateway"),
        ("aiops008_release_sources", "aiops008_gateway"),
        ("aiops008_gateway", "aiops008_intake"),
        ("aiops008_intake", "aiops008_risk_analysis"),
        ("aiops008_model", "aiops008_risk_analysis"),
        ("aiops008_dependency_graph", "aiops008_risk_analysis"),
        ("aiops008_risk_analysis", "aiops008_policy"),
        ("aiops008_policy", "aiops008_intake"),
        ("aiops008_event_bus", "aiops008_analytics"),
        ("aiops008_analytics", "aiops008_training"),
    } <= {(edge["source"], edge["target"]) for edge in edges}

    adjacency = {node: set() for node in nodes}
    for edge in edges:
        adjacency[edge["source"]].add(edge["target"])
        adjacency[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque([next(iter(nodes))])
    while pending:
        node = pending.popleft()
        if node in reached:
            continue
        reached.add(node)
        pending.extend(adjacency[node] - reached)
    assert reached == nodes

    request = make_request(problem, guide, built)
    assert request["problem"]["requirements"] == "\n".join(REQUIREMENTS)
    assert request["problem"]["constraints"] == "\n".join(CONSTRAINTS)
    assert request["problem"]["requirementRevision"].startswith("legacy-")
    assert len(request["components"]) == 14

