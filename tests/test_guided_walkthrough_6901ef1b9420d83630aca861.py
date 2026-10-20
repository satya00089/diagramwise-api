"""Frozen-brief, catalog, action-order, and replay checks for the Kafka review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca861"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": PROBLEM_ID,
    "title": "Design a Distributed Stream Processing System like Kafka",
    "description": "Design a distributed streaming platform for real-time data pipelines and event-driven architectures.",
    "requirements": [
        "Publish and subscribe to streams of records",
        "Store streams durably and fault-tolerantly",
        "Process streams in real-time",
        "Support high throughput (millions of messages/sec)",
        "Guarantee message ordering within partition",
        "Support message replay",
        "Handle failures gracefully",
        "Scale horizontally",
    ],
    "constraints": [
        "Low latency for message delivery",
        "High durability (no data loss)",
        "Support large messages (up to 1MB)",
        "Handle network partitions",
        "Exactly-once or at-least-once delivery",
    ],
    "hints": [
        "Partition data for parallelism",
        "Replication for fault tolerance",
        "Commit log for durability",
        "Consumer groups for load balancing",
        "ZooKeeper or similar for coordination",
    ],
}
STEP_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "decision_point",
    "scale_trigger",
}
ACTION_TYPES = {"add_component", "add_connection", "decision_point"}
CONNECTION_TYPES = {
    "http",
    "tcp",
    "websocket",
    "message-queue",
    "database-connection",
    "api-call",
    "data-flow",
    "event-stream",
}


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def frozen_problem():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"{step_id}: unknown catalog ID {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), f"{step_id}: incomplete catalog block for {component_type}"
    return catalog[match.start() : block_end]


def assert_catalog_properties(catalog: str, component_type: str, properties: dict, step_id: str):
    block = catalog_block(catalog, component_type, step_id)
    supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
    assert set(properties) <= supported, (
        f"{step_id}: unsupported {component_type} properties "
        f"{sorted(set(properties) - supported)}"
    )

    for key, value in properties.items():
        field_start = re.search(rf'\{{\s*key:\s*"{re.escape(key)}"', block)
        assert field_start is not None, f"{step_id}: missing catalog property {component_type}.{key}"
        field_end = block.find("},", field_start.start())
        assert field_end != -1, f"{step_id}/{key}: catalog property field is incomplete"
        field = block[field_start.start() : field_end]
        field_type = re.search(r'\btype:\s*"([^"]+)"', field)
        assert field_type is not None, f"{step_id}/{key}: catalog property has no type"
        kind = field_type.group(1)
        if kind == "boolean":
            assert type(value) is bool, f"{step_id}/{key} must be boolean"
        elif kind == "number":
            assert type(value) in (int, float), f"{step_id}/{key} must be numeric"
        elif kind == "select":
            options = re.search(r'\boptions:\s*\[([^\]]*)\]', field, re.DOTALL)
            assert options is not None, f"{step_id}/{key}: select has no options"
            assert value in re.findall(r'"([^"]+)"', options.group(1)), (
                f"{step_id}/{key} is not a catalog select option"
            )
        elif kind in {"text", "textarea"}:
            assert isinstance(value, str), f"{step_id}/{key} must be text"


def reachable(start: str, neighbors: dict[str, set[str]]) -> set[str]:
    reached = set()
    pending = deque([start])
    while pending:
        node_id = pending.popleft()
        if node_id in reached:
            continue
        reached.add(node_id)
        pending.extend(neighbors[node_id] - reached)
    return reached


def test_frozen_brief_matches_repository_snapshot_exactly():
    problem = frozen_problem()
    assert {field: problem[field] for field in FROZEN_BRIEF} == FROZEN_BRIEF


def test_schema_order_phases_and_actionable_anchor_coverage():
    raw, guide = load_guide()
    assert set(raw) == {"problem_id", "version", "requirementRevision", "totalSteps", "phases", "steps"}
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 29
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES and step.title and step.content.strip() for step in guide.steps)

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end <= guide.totalSteps
        assert phase.description
        assert all(guide.steps[number - 1].phase == phase.name for number in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    expected_anchors = {
        *(f"legacy-requirement:{index}" for index in range(1, len(FROZEN_BRIEF["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(FROZEN_BRIEF["constraints"]) + 1)),
    }
    actual_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert actual_anchors == expected_anchors
    action_anchors = {
        anchor
        for step in guide.steps
        if step.type in ACTION_TYPES
        for anchor in step.requirementIds
    }
    assert action_anchors == expected_anchors, "every brief item needs a concrete design action or decision"
    for step in guide.steps:
        assert set(step.requirementIds) <= expected_anchors


def test_catalog_ids_properties_and_step_order_are_replayable():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}
    seen_edges = set()
    connection_count = 0

    for step in raw["steps"]:
        component = step.get("component")
        if component:
            node_id = component["nodeId"]
            assert node_id not in components
            assert component["componentType"] != "custom-component"
            assert component["properties"]["componentName"] == component["label"]
            assert len(component["properties"]["purpose"]) >= 70
            assert component["highlightReason"]
            assert set(component["position"]) == {"x", "y"}
            assert_catalog_properties(catalog, component["componentType"], component["properties"], step["id"])
            components[node_id] = component

        connection = step.get("connection")
        if connection:
            connection_count += 1
            assert connection["edgeId"] not in seen_edges
            assert connection["sourceNodeId"] in components
            assert connection["targetNodeId"] in components
            assert connection["connectionType"] in CONNECTION_TYPES
            assert connection["label"] and connection["description"]
            seen_edges.add(connection["edgeId"])

        update = step.get("componentUpdate")
        if update:
            assert update["nodeId"] in components
            assert update["properties"]
            assert_catalog_properties(
                catalog,
                components[update["nodeId"]]["componentType"],
                update["properties"],
                step["id"],
            )

        if step["type"] == "decision_point":
            assert step.get("decision") and update
            decision = step["decision"]
            assert decision["question"] and decision["chosen"] and decision["chosenReason"]
            assert len(decision["alternatives"]) >= 2
            assert all(option["option"] and option["tradeoff"] for option in decision["alternatives"])

    assert len(components) == 7
    assert connection_count == len(seen_edges) == 8
    assert {component["componentType"] for component in components.values()} == {
        "backend-server",
        "message-broker",
        "distributed-lock",
        "stream-processor",
        "processing-worker",
        "database",
        "monitoring",
    }
    assert components["stream_coordination"]["properties"]["backend"] == "Zookeeper"


def test_replay_builds_the_expected_connected_stream_architecture():
    raw, _ = load_guide()
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    edges = architecture["connections"]

    assert len(nodes) == 7
    assert len(edges) == 8
    assert len(replay["acceptedDecisions"]) == 6
    expected_applied = {
        step["id"]
        for step in raw["steps"]
        if step["type"] in {"add_component", "add_connection"}
        or (step["type"] == "decision_point" and step.get("componentUpdate"))
    }
    assert set(replay["appliedStepIds"]) == expected_applied
    assert replay["provenance"]["problemId"] == PROBLEM_ID
    assert replay["provenance"]["walkthroughVersion"] == "1.0.0-review-draft"
    assert all(edge["type"] in CONNECTION_TYPES for edge in edges)
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in edges)

    pairs = {(edge["source"], edge["target"]) for edge in edges}
    assert pairs == {
        ("stream_producers", "stream_broker"),
        ("stream_coordination", "stream_broker"),
        ("stream_broker", "stream_processor"),
        ("stream_broker", "stream_consumers"),
        ("stream_processor", "stream_broker"),
        ("stream_consumers", "stream_sink"),
        ("stream_broker", "stream_monitoring"),
        ("stream_processor", "stream_monitoring"),
    }
    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    assert reachable("stream_producers", neighbors) == set(nodes)


def test_guidance_covers_kafka_specific_contracts_and_avoids_invented_targets():
    raw, _ = load_guide()
    content = json.dumps(raw, ensure_ascii=False).casefold()
    for phrase in (
        "partition",
        "replicat",
        "append-only commit log",
        "consumer group",
        "zookeeper",
        "millions of messages per second",
        "1 mb",
        "network partition",
        "at-least-once",
        "exactly-once",
        "idempotent",
        "committed offset",
        "replay",
        "lag",
        "fencing",
        "no fixed partition count, replication factor, throughput threshold, latency target, or replay-retention duration",
    ):
        assert phrase in content, f"missing stream-system guidance: {phrase}"
