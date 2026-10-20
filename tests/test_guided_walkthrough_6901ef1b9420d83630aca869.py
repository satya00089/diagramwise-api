"""Frozen-brief, catalog, and connected replay checks for the job scheduler draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca869"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": PROBLEM_ID,
    "title": "Design a Job Scheduler",
    "description": (
        "Design a distributed job scheduling system to execute tasks at "
        "specified times or intervals."
    ),
    "requirements": [
        "Schedule jobs for future execution",
        "Support one-time and recurring jobs",
        "Prioritize jobs based on importance",
        "Retry failed jobs with backoff",
        "Track job status and history",
        "Support cron-like expressions",
        "Distribute jobs across workers",
        "Handle millions of jobs",
    ],
    "constraints": [
        "Accurate timing for job execution",
        "Handle worker failures gracefully",
        "Avoid duplicate job execution",
        "Support long-running jobs",
        "Efficient job queue management",
    ],
}

SUPPORTED_STEP_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "decision_point",
    "scale_trigger",
    "update_component",
}
GRAPH_ACTION_TYPES = {"add_component", "add_connection", "update_component"}
CONNECTION_TYPES = {
    "http",
    "api-call",
    "database-connection",
    "message-queue",
    "data-flow",
}


def load_candidate():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    matches = [problem for problem in problems if problem["id"] == PROBLEM_ID]
    assert len(matches) == 1
    return raw, GuidedWalkthrough.model_validate(raw), matches[0]


def expected_anchors(problem):
    return {
        *(f"legacy-requirement:{index}" for index in range(1, len(problem["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(problem["constraints"]) + 1)),
    }


def catalog_block(catalog, component_type, step_id):
    match = re.search(rf'^\s+id:\s*"{re.escape(component_type)}"\s*,', catalog, re.MULTILINE)
    assert match is not None, f"{step_id}: unknown catalog component {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), f"{step_id}: incomplete catalog component {component_type}"
    return catalog[match.start() : block_end]


def assert_catalog_properties(catalog, component_type, properties, step_id):
    block = catalog_block(catalog, component_type, step_id)
    supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
    assert set(properties) <= supported, (
        f"{step_id}: unsupported {component_type} properties "
        f"{sorted(set(properties) - supported)}"
    )

    for key, value in properties.items():
        field_start = re.search(rf'\{{\s*key:\s*"{re.escape(key)}"', block)
        assert field_start, f"{step_id}: missing catalog property {component_type}.{key}"
        field_end = block.find("},", field_start.start())
        assert field_end > field_start.start(), f"{step_id}: incomplete property {key}"
        field = block[field_start.start() : field_end]
        field_type = re.search(r'\btype:\s*"([^"]+)"', field)
        assert field_type, f"{step_id}: {component_type}.{key} has no catalog type"

        kind = field_type.group(1)
        if kind in {"text", "textarea"}:
            assert isinstance(value, str), f"{step_id}/{key} must be text"
        elif kind == "boolean":
            assert type(value) is bool, f"{step_id}/{key} must be boolean"
        elif kind == "number":
            assert type(value) in {int, float}, f"{step_id}/{key} must be numeric"
        elif kind == "select":
            options = re.search(r'\boptions:\s*\[([^\]]*)\]', field, re.DOTALL)
            assert options, f"{step_id}/{key}: catalog options are missing"
            allowed = set(re.findall(r'"([^"]+)"', options.group(1)))
            assert value in allowed, f"{step_id}/{key}: unsupported option {value!r}"


def connected_from(start, neighbors):
    reached = set()
    pending = deque([start])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    return reached


def test_runtime_draft_matches_frozen_brief_and_covers_every_anchor_with_actions():
    raw, guide, problem = load_candidate()
    assert {key: problem[key] for key in FROZEN_BRIEF} == FROZEN_BRIEF
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps)
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in SUPPORTED_STEP_TYPES and step.content.strip() for step in guide.steps)

    expected = expected_anchors(problem)
    all_anchors = {anchor for step in raw["steps"] for anchor in step.get("requirementIds", [])}
    action_anchors = {
        anchor
        for step in raw["steps"]
        if step["type"] in GRAPH_ACTION_TYPES
        for anchor in step.get("requirementIds", [])
    }
    assert all_anchors == expected
    assert action_anchors == expected, (
        "Every frozen requirement and constraint must be evidenced by an applied graph action."
    )


def test_phases_actions_and_connections_are_ordered_and_unique():
    raw, guide, _ = load_candidate()
    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    nodes = {}
    edge_ids = set()
    for step in guide.steps:
        if step.type == "add_component":
            assert step.component is not None
            component = step.component
            assert component.nodeId not in nodes
            assert component.componentType != "custom-component"
            assert component.position.keys() >= {"x", "y"}
            nodes[component.nodeId] = component
        elif step.type == "add_connection":
            assert step.connection is not None
            connection = step.connection
            assert connection.edgeId not in edge_ids
            assert connection.connectionType in CONNECTION_TYPES
            assert connection.sourceNodeId != connection.targetNodeId
            assert {connection.sourceNodeId, connection.targetNodeId} <= nodes.keys()
            assert connection.label.strip() and connection.description.strip()
            edge_ids.add(connection.edgeId)

    assert nodes and edge_ids
    assert len(nodes) == 8
    assert len(edge_ids) == 13
    assert raw["totalSteps"] == len(raw["steps"])


def test_catalog_component_ids_and_property_values_are_supported():
    raw, _, _ = load_candidate()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = [step["component"] for step in raw["steps"] if step.get("component")]
    assert components

    for step in raw["steps"]:
        component = step.get("component")
        if step.get("type") == "add_component":
            assert component is not None
            properties = component.get("properties", {})
            assert properties.get("componentName") == component["label"]
            assert properties.get("purpose", "").strip()
            assert component.get("highlightReason", "").strip()
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            component = next(
                item["component"]
                for item in raw["steps"]
                if item.get("component", {}).get("nodeId") == update["nodeId"]
            )
            properties = update.get("properties", {})
        else:
            continue

        assert_catalog_properties(catalog, component["componentType"], properties, step["id"])


def test_replay_produces_one_connected_catalog_backed_graph():
    raw, _, _ = load_candidate()
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {node["id"]: node for node in architecture["components"]}
    edges = architecture["connections"]

    assert len(nodes) == 8
    assert len(edges) == 13
    assert not [node["id"] for node in nodes.values() if node["type"] == "custom"]
    assert replay["appliedStepIds"] == [
        step["id"] for step in raw["steps"] if step["type"] in GRAPH_ACTION_TYPES
    ]
    assert replay["acceptedDecisions"] == []

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    assert connected_from("job_api", neighbors) == set(nodes)
