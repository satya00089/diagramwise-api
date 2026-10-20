"""Focused review gates for the multi-cloud cost-optimization walkthrough draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / "aiops_011.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

TITLE = "Design an AI-Powered Cloud Cost Optimization Platform"
DESCRIPTION = (
    "Design a platform that uses ML to analyze cloud spending patterns, identify "
    "waste, recommend rightsizing, optimize reserved capacity purchases, and "
    "forecast future costs across multi-cloud environments."
)
REQUIREMENTS = [
    "Analyze cloud spending across providers",
    "Detect idle and underutilized resources",
    "Recommend instance rightsizing based on usage",
    "Optimize reserved instance and savings plan coverage",
    "Forecast future cloud costs by team and service",
    "Identify cost anomalies and unexpected spikes",
    "Implement automated cost governance policies",
    "Provide cost allocation and showback/chargeback",
]
CONSTRAINTS = [
    "Cost savings recommendations accuracy above 90%",
    "Cost anomaly detection within 1 hour",
    "Support AWS, Azure, and GCP billing data",
    "Handle 10k+ cloud resources across accounts",
    "Cost forecast accuracy within 10%",
]
HINTS = [
    "Use time-series analysis for usage-based rightsizing",
    "Implement optimization algorithms for RI/SP purchasing",
    "Use anomaly detection for cost spike identification",
    "Implement tag-based cost allocation with inference for untagged",
    "Use ML clustering for workload profiling",
    "Implement what-if analysis for pricing model comparison",
]
STEP_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "decision_point",
    "scale_trigger",
}
CONNECTION_TYPES = {
    "api-call",
    "data-flow",
    "database-connection",
    "event-stream",
    "message-queue",
}


def load_problem():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == "aiops_011")


def load_guide():
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def _catalog_block(catalog, component_type):
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match, f"Unknown component catalog ID: {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), f"Could not isolate catalog block: {component_type}"
    return catalog[match.start():block_end]


def _assert_supported_properties(catalog_block, properties, context):
    supported = set(re.findall(r'\bkey:\s*"([^"]+)"', catalog_block))
    assert set(properties) <= supported, (
        f"{context} has unsupported properties: "
        f"{sorted(set(properties) - supported)}"
    )
    for key, value in properties.items():
        property_start = re.search(
            rf'\{{\s*key:\s*"{re.escape(key)}"', catalog_block
        )
        assert property_start, f"Missing catalog property definition: {key}"
        remainder = catalog_block[property_start.start():]
        next_property = re.search(r'\n\s*\{\s*key:', remainder[1:])
        property_block = (
            remainder[:next_property.start() + 1]
            if next_property else remainder
        )
        field_type = re.search(r'\btype:\s*"([^"]+)"', property_block)
        assert field_type, f"Catalog property {key} has no type"
        if field_type[1] == "boolean":
            assert type(value) is bool
        elif field_type[1] == "number":
            assert type(value) in (int, float)
        elif field_type[1] == "select":
            options = re.search(r'\boptions:\s*\[([^\]]*)\]', property_block, re.DOTALL)
            assert options, f"Catalog select {key} has no supported options"
            allowed = set(re.findall(r'"([^"]+)"', options[1]))
            assert value in allowed, f"Unsupported catalog value {key}={value!r}"
        else:
            assert isinstance(value, str), f"Catalog text field {key} must be a string"


def test_frozen_brief_and_pydantic_schema_are_preserved():
    problem = load_problem()
    guide = GuidedWalkthrough.model_validate(load_guide())

    assert problem["id"] == guide.problem_id == "aiops_011"
    assert problem["title"] == TITLE
    assert problem["description"] == DESCRIPTION
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert problem["hints"] == HINTS
    assert problem["has_guided_walkthrough"] is False
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps)
    assert 35 <= guide.totalSteps <= 60


def test_step_ids_phases_types_and_exact_action_anchors():
    guide = load_guide()
    steps = guide["steps"]
    assert [step["stepNumber"] for step in steps] == list(range(1, len(steps) + 1))
    assert len({step["id"] for step in steps}) == len(steps)
    assert all(step["type"] in STEP_TYPES for step in steps)
    assert all(step["title"].strip() and step["content"].strip() for step in steps)

    next_step = 1
    seen_phases = set()
    for phase in guide["phases"]:
        start, end = phase["stepRange"]
        assert phase["name"] not in seen_phases
        seen_phases.add(phase["name"])
        assert start == next_step
        assert start <= end <= len(steps)
        assert phase["description"].strip()
        assert all(steps[number - 1]["phase"] == phase["name"]
                   for number in range(start, end + 1))
        next_step = end + 1
    assert next_step == len(steps) + 1

    expected_anchors = {
        *(f"legacy-requirement:{number}" for number in range(1, len(REQUIREMENTS) + 1)),
        *(f"legacy-constraint:{number}" for number in range(1, len(CONSTRAINTS) + 1)),
    }
    anchors = {anchor for step in steps for anchor in step.get("requirementIds", [])}
    assert anchors == expected_anchors

    graph_actions = [
        step for step in steps
        if step["type"] in {"add_component", "add_connection"}
        or (step["type"] == "decision_point" and step.get("componentUpdate"))
    ]
    action_anchors = {
        anchor for step in graph_actions for anchor in step.get("requirementIds", [])
    }
    assert action_anchors == expected_anchors


def test_components_and_updates_use_real_catalog_types_and_properties():
    guide = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    added = {}

    for step in guide["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            assert component["nodeId"] not in added
            assert component["componentType"] != "custom"
            assert component["properties"]["componentName"] == component["label"]
            assert component["properties"]["purpose"] == component["description"]
            block = _catalog_block(catalog, component["componentType"])
            _assert_supported_properties(block, component["properties"], step["id"])
            added[component["nodeId"]] = (component, block)

        update = step.get("componentUpdate")
        if update:
            assert update["nodeId"] in added
            component, block = added[update["nodeId"]]
            assert update["properties"]
            _assert_supported_properties(block, update["properties"], step["id"])
            assert component["componentType"] != "custom"

    custom_nodes = {
        node_id for node_id, (component, _) in added.items()
        if component["componentType"] == "custom-component"
    }
    assert custom_nodes == {"cost_provider_adapter"}


def test_ordered_replay_builds_a_connected_graph_and_frozen_request():
    guide = load_guide()
    built = build_architecture(guide)
    architecture = built["architecture"]
    nodes = {component["id"] for component in architecture["components"]}
    edges = architecture["connections"]

    assert nodes
    assert edges
    assert all(edge["type"] in CONNECTION_TYPES for edge in edges)

    added = set()
    for step in sorted(guide["steps"], key=lambda row: row["stepNumber"]):
        if step["type"] == "add_component":
            node_id = step["component"]["nodeId"]
            assert node_id not in added
            added.add(node_id)
        elif step["type"] == "add_connection":
            edge = step["connection"]
            assert edge["sourceNodeId"] in added
            assert edge["targetNodeId"] in added

    assert added == nodes
    neighbors = {node_id: set() for node_id in nodes}
    edge_pairs = set()
    for edge in edges:
        pair = (edge["source"], edge["target"])
        assert edge["source"] in nodes and edge["target"] in nodes
        assert pair not in edge_pairs
        edge_pairs.add(pair)
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])

    reached = set()
    pending = deque([next(iter(nodes))])
    while pending:
        node_id = pending.popleft()
        if node_id in reached:
            continue
        reached.add(node_id)
        pending.extend(neighbors[node_id] - reached)
    assert reached == nodes

    problem = load_problem()
    request = make_request(problem, guide, built)
    assert request["problem"]["requirements"] == "\n".join(REQUIREMENTS)
    assert request["problem"]["constraints"] == "\n".join(CONSTRAINTS)
    assert request["problem"]["requirementRevision"].startswith("legacy-")
    assert len(request["components"]) == len(nodes)
    assert len(request["connections"]) == len(edges)
