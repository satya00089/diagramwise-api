"""Frozen-brief, catalog, and connected replay checks for the Top-K draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca882"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
FROZEN_PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

STEP_TYPES = {
    "explanation", "add_component", "add_connection", "decision_point",
    "scale_trigger", "update_component", "conclusion",
}
CONNECTION_TYPES = {
    "http", "api-call", "database-connection", "message-queue", "data-flow",
}
EXPECTED_COMPONENTS = 13
EXPECTED_CONNECTIONS = 19


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def load_frozen_problem():
    problems = json.loads(FROZEN_PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next((item for item in problems if item.get("id") == PROBLEM_ID), None)
    assert problem is not None, f"Missing frozen problem brief for {PROBLEM_ID}"
    return problem


def test_schema_and_exact_frozen_brief_anchor_coverage():
    _, guide = load_guide()
    frozen_problem = load_frozen_problem()

    assert guide.problem_id == frozen_problem["id"] == PROBLEM_ID
    assert guide.version.endswith("-review-draft")
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps)
    assert [step.stepNumber for step in guide.steps] == list(
        range(1, guide.totalSteps + 1)
    )
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES and step.content.strip() for step in guide.steps)
    frozen_brief = guide.steps[0].content
    assert frozen_problem["title"] in frozen_brief
    assert frozen_problem["description"] in frozen_brief
    assert frozen_problem["has_guided_walkthrough"] is False
    for field in ("requirements", "constraints", "hints"):
        assert frozen_problem[field]
        assert all(statement in frozen_brief for statement in frozen_problem[field])

    expected_anchors = {
        *(
            f"legacy-requirement:{index}"
            for index in range(1, len(frozen_problem["requirements"]) + 1)
        ),
        *(
            f"legacy-constraint:{index}"
            for index in range(1, len(frozen_problem["constraints"]) + 1)
        ),
    }
    actual_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert actual_anchors == expected_anchors
    actionable = [
        step for step in guide.steps
        if step.type in {"add_component", "add_connection", "update_component"}
    ]
    for anchor in expected_anchors:
        assert any(anchor in step.requirementIds for step in actionable), (
            f"{anchor} is only described, not tied to a replayable design action"
        )


def test_phases_and_ordered_graph_actions_are_well_formed():
    _, guide = load_guide()
    next_step = 1
    nodes = {}
    edges = set()

    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end
        assert all(
            guide.steps[index - 1].phase == phase.name
            for index in range(start, end + 1)
        )
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    for step in guide.steps:
        if step.type == "add_component":
            assert step.component is not None
            assert step.component.nodeId not in nodes
            assert step.component.position.keys() >= {"x", "y"}
            nodes[step.component.nodeId] = step.component
        elif step.type == "add_connection":
            assert step.connection is not None
            connection = step.connection
            assert connection.edgeId not in edges
            assert connection.connectionType in CONNECTION_TYPES
            assert {connection.sourceNodeId, connection.targetNodeId} <= nodes.keys()
            edges.add(connection.edgeId)
        elif step.type == "update_component":
            assert step.componentUpdate is not None
            assert step.componentUpdate.nodeId in nodes
            assert step.componentUpdate.properties

    assert len(nodes) == EXPECTED_COMPONENTS
    assert len(edges) == EXPECTED_CONNECTIONS


def test_catalog_ids_and_editable_properties_match_frontend_definitions():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step.get("type") == "add_component"
    }

    assert components
    for step in raw["steps"]:
        if step.get("type") == "add_component":
            component = step["component"]
            component_type = component["componentType"]
            properties = component.get("properties", {})
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            component = components[update["nodeId"]]
            component_type = component["componentType"]
            properties = update.get("properties", {})
        else:
            continue

        match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
        assert match is not None, f"{step['id']}: unknown catalog ID {component_type}"
        block_end = catalog.find("\n  },", match.start())
        assert block_end != -1
        component_block = catalog[match.start():block_end]
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', component_block))
        assert set(properties) <= supported, (
            f"{step['id']}: unsupported properties "
            f"{sorted(set(properties) - supported)}"
        )
        if step.get("type") == "add_component":
            assert {"componentName", "purpose"} <= set(properties)
            assert properties["componentName"] == component["label"]
            assert len(properties["purpose"]) >= 70

        for key, value in properties.items():
            field_start = component_block.index(f'key: "{key}"')
            field_end = component_block.find("},", field_start)
            field = component_block[field_start:field_end]
            field_type = re.search(r'\btype:\s*"([^"]+)"', field)
            assert field_type is not None, f"{step['id']}/{key}: missing field type"
            kind = field_type.group(1)
            if kind in {"text", "textarea"}:
                assert isinstance(value, str)
            elif kind == "boolean":
                assert type(value) is bool
            elif kind == "number":
                assert type(value) in {int, float}
            elif kind == "select":
                options = re.search(r'\boptions:\s*\[([^\]]+)\]', field)
                assert options is not None
                assert value in re.findall(r'"([^"]+)"', options.group(1)), (
                    f"{step['id']}/{key}: unsupported option {value!r}"
                )


def test_all_actions_replay_to_one_connected_exact_ranking_graph():
    raw, _ = load_guide()
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {node["id"]: node for node in architecture["components"]}
    edges = architecture["connections"]

    assert len(nodes) == EXPECTED_COMPONENTS
    assert len(edges) == EXPECTED_CONNECTIONS
    assert nodes["rank_stream"]["properties"]["originalComponentId"] == "stream-processor"
    assert nodes["rank_cache"]["properties"]["engine"] == "redis"
    assert all(node["type"] != "custom" for node in nodes.values())

    edge_pairs = {(edge["source"], edge["target"]) for edge in edges}
    for expected in (
        ("rank_sources", "rank_gateway"),
        ("rank_gateway", "rank_ingest"),
        ("rank_ingest", "rank_event_store"),
        ("rank_event_store", "rank_outbox_relay"),
        ("rank_outbox_relay", "rank_broker"),
        ("rank_broker", "rank_stream"),
        ("rank_stream", "rank_state_store"),
        ("rank_state_store", "rank_index_projector"),
        ("rank_index_projector", "rank_cache"),
        ("rank_dashboard", "rank_gateway"),
        ("rank_gateway", "rank_query"),
        ("rank_query", "rank_cache"),
        ("rank_query", "rank_state_store"),
    ):
        assert expected in edge_pairs

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["rank_sources"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == set(nodes)
