"""Frozen brief, catalog, replay, and queue semantics for the local review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca867"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": "6901ef1b9420d83630aca867",
    "title": "Design a Distributed Queue like RabbitMQ",
    "description": "Design a message queue system for reliable asynchronous communication between distributed services.",
    "requirements": [
        "Publish and consume messages",
        "Support multiple queues and topics",
        "Message persistence and durability",
        "Dead letter queue for failed messages",
        "Message ordering guarantees",
        "Support different delivery patterns (pub/sub, point-to-point)",
        "Handle millions of messages per second",
        "Message acknowledgment and retry logic",
    ],
    "constraints": [
        "Low message latency",
        "High throughput",
        "No message loss",
        "Handle consumer failures",
        "Support priority queues",
    ],
    "hints": [
        "Separate metadata and message storage",
        "Replication for durability",
        "Consumer groups for load balancing",
        "Message TTL and expiration",
        "Flow control and backpressure",
    ],
}
EXPECTED_PHASES = [
    ("Set delivery and durability guarantees", 1, 5),
    ("Route messages and separate stored data", 6, 12),
    ("Consume, acknowledge, and recover", 13, 21),
    ("Preserve order and scale from evidence", 22, 24),
]
CONNECTION_TYPES = {
    "http",
    "api-call",
    "database-connection",
    "tcp",
    "message-queue",
    "data-flow",
}
ACTION_TYPES = {"add_component", "add_connection"}
STEP_TYPES = ACTION_TYPES | {"explanation", "decision_point", "scale_trigger"}
EXPECTED_NODE_TYPES = {
    "queue_publishers": "backend-server",
    "queue_broker": "message-broker",
    "queue_metadata": "database",
    "queue_topic_subscriptions": "queue",
    "queue_point_to_point": "queue",
    "queue_consumer_group": "processing-worker",
    "queue_retry": "queue",
    "queue_dead_letter": "queue",
}
EXPECTED_EDGE_PAIRS = {
    ("queue_publishers", "queue_broker"),
    ("queue_broker", "queue_metadata"),
    ("queue_broker", "queue_topic_subscriptions"),
    ("queue_broker", "queue_point_to_point"),
    ("queue_topic_subscriptions", "queue_consumer_group"),
    ("queue_point_to_point", "queue_consumer_group"),
    ("queue_consumer_group", "queue_broker"),
    ("queue_broker", "queue_retry"),
    ("queue_retry", "queue_broker"),
    ("queue_broker", "queue_dead_letter"),
}


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    matches = [problem for problem in problems if problem["id"] == PROBLEM_ID]
    assert len(matches) == 1
    return raw, GuidedWalkthrough.model_validate(raw), matches[0]


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"{step_id}: unknown catalog component {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), f"{step_id}: incomplete component catalog entry"
    return catalog[match.start() : block_end]


def assert_catalog_properties(
    catalog: str, component_type: str, properties: dict, step_id: str
) -> None:
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
        assert field_type, f"{step_id}: property {component_type}.{key} has no type"
        if field_type.group(1) in {"text", "textarea"}:
            assert isinstance(value, str), f"{step_id}/{key} must be text"
        elif field_type.group(1) == "boolean":
            assert type(value) is bool, f"{step_id}/{key} must be boolean"
        elif field_type.group(1) == "number":
            assert type(value) in {int, float}, f"{step_id}/{key} must be numeric"
        elif field_type.group(1) == "select":
            options = re.search(r'\boptions:\s*\[([^\]]*)\]', field, re.DOTALL)
            assert options, f"{step_id}/{key}: catalog select options are missing"
            allowed = set(re.findall(r'"([^"]+)"', options.group(1)))
            assert value in allowed, f"{step_id}/{key}: unsupported select option {value!r}"


def connected_from(start: str, neighbors: dict[str, set[str]]) -> set[str]:
    reached = set()
    pending = deque([start])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    return reached


def test_exact_frozen_brief_schema_version_and_phase_order():
    raw, guide, problem = load_guide()

    assert {field: problem[field] for field in FROZEN_BRIEF} == FROZEN_BRIEF
    assert problem["has_guided_walkthrough"] is False
    assert set(raw) == {
        "problem_id",
        "version",
        "requirementRevision",
        "totalSteps",
        "phases",
        "steps",
    }
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 24
    assert [(phase.name, *phase.stepRange) for phase in guide.phases] == EXPECTED_PHASES
    assert {step.type for step in guide.steps} == STEP_TYPES
    assert all(step.title.strip() and step.content.strip() for step in guide.steps)


def test_step_order_and_every_brief_anchor_has_an_action():
    _, guide, _ = load_guide()
    expected_anchors = {
        *(f"legacy-requirement:{index}" for index in range(1, 9)),
        *(f"legacy-constraint:{index}" for index in range(1, 6)),
    }
    assert [step.stepNumber for step in guide.steps] == list(range(1, 25))
    assert len({step.id for step in guide.steps}) == guide.totalSteps

    next_step = 1
    all_anchors = set()
    action_anchors = set()
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end <= guide.totalSteps
        assert all(step.phase == phase.name for step in guide.steps[start - 1 : end])
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    for step in guide.steps:
        anchors = set(step.requirementIds)
        assert len(anchors) == len(step.requirementIds), f"{step.id}: repeated anchor"
        assert anchors <= expected_anchors, f"{step.id}: unknown anchor"
        all_anchors.update(anchors)
        if step.type in ACTION_TYPES:
            action_anchors.update(anchors)
    assert all_anchors == expected_anchors
    assert action_anchors == expected_anchors


def test_catalog_components_supported_properties_and_connected_replay():
    raw, guide, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    component_ids = []
    edge_ids = []
    action_ids = []
    seen_nodes = {}
    seen_edges = set()

    for step in guide.steps:
        if step.type == "add_component":
            component = step.component
            assert component is not None
            assert component.nodeId not in seen_nodes
            assert set(component.position) == {"x", "y"}
            assert all(type(value) in {int, float} for value in component.position.values())
            assert component.properties["componentName"] == component.label
            assert len(component.properties["purpose"]) >= 70
            assert component.highlightReason
            assert component.componentType in set(EXPECTED_NODE_TYPES.values())
            assert component.componentType != "custom-component"
            assert_catalog_properties(catalog, component.componentType, component.properties, step.id)
            seen_nodes[component.nodeId] = component
            component_ids.append(component.nodeId)
            action_ids.append(step.id)
        elif step.type == "add_connection":
            connection = step.connection
            assert connection is not None
            assert connection.edgeId not in seen_edges
            assert connection.sourceNodeId in seen_nodes
            assert connection.targetNodeId in seen_nodes
            assert connection.connectionType in CONNECTION_TYPES
            assert connection.label and connection.description
            seen_edges.add(connection.edgeId)
            edge_ids.append(connection.edgeId)
            action_ids.append(step.id)

    assert len(component_ids) == len(set(component_ids)) == len(EXPECTED_NODE_TYPES)
    assert len(edge_ids) == len(set(edge_ids)) == len(EXPECTED_EDGE_PAIRS)
    assert {node_id: component.componentType for node_id, component in seen_nodes.items()} == EXPECTED_NODE_TYPES
    assert action_ids == [step["id"] for step in raw["steps"] if step["type"] in ACTION_TYPES]

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    edges = architecture["connections"]
    assert set(nodes) == set(EXPECTED_NODE_TYPES)
    assert len(edges) == len(EXPECTED_EDGE_PAIRS)
    assert replay["appliedStepIds"] == action_ids
    assert all(edge["type"] in CONNECTION_TYPES for edge in edges)
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in edges)

    neighbors = {node_id: set() for node_id in nodes}
    edge_pairs = set()
    for edge in edges:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
        edge_pairs.add((edge["source"], edge["target"]))
    assert edge_pairs == EXPECTED_EDGE_PAIRS
    assert connected_from("queue_publishers", neighbors) == set(nodes)


def test_queue_delivery_ordering_retry_and_failure_semantics_are_explicit():
    raw, _, _ = load_guide()
    components = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step.get("component")
    }
    broker = components["queue_broker"]
    metadata = components["queue_metadata"]
    topic_queue = components["queue_topic_subscriptions"]
    work_queue = components["queue_point_to_point"]
    consumers = components["queue_consumer_group"]
    retry_queue = components["queue_retry"]
    dead_letter = components["queue_dead_letter"]

    assert broker["componentType"] == "message-broker"
    assert broker["properties"]["durable"] is True
    assert "replicated" in broker["properties"]["purpose"].casefold()
    assert "quorum" in broker["properties"]["purpose"].casefold()
    assert metadata["componentType"] == "database"
    assert "do not store message payloads" in metadata["properties"]["purpose"].casefold()
    assert "pub/sub" in topic_queue["properties"]["purpose"].casefold()
    assert "point-to-point" in work_queue["properties"]["purpose"].casefold()
    assert "priority" in work_queue["properties"]["purpose"].casefold()
    assert "ordering key" in work_queue["properties"]["purpose"].casefold()
    assert consumers["componentType"] == "processing-worker"
    assert "consumer group" in consumers["properties"]["purpose"].casefold()
    assert "at least once" in consumers["properties"]["purpose"].casefold()
    assert retry_queue["properties"]["durable"] is True
    assert retry_queue["properties"]["backoff"] == "exponential"
    assert "retry budget" in retry_queue["properties"]["purpose"].casefold()
    assert dead_letter["properties"]["durable"] is True
    assert "retry budget" in dead_letter["properties"]["purpose"].casefold()

    numeric_policy_fields = {"partitions", "replication", "retention", "maxRetries", "visibilityTimeout"}
    for component in components.values():
        assert not (numeric_policy_fields & set(component["properties"])), (
            f"{component['nodeId']}: draft must not invent numeric policy targets"
        )

    authored = json.dumps(raw["steps"][1:], ensure_ascii=False).casefold()
    for signal in (
        "at least once",
        "duplicates",
        "idempotent",
        "per ordering key",
        "global fifo",
        "priority",
        "acknowledges only after",
        "redelivery",
        "transient failures",
        "permanent failures",
        "dead-letter",
        "backpressure",
        "expiresat",
        "millions of messages per second",
        "no numeric",
    ):
        assert signal in authored, f"Missing queue design signal: {signal}"


def test_brief_facts_are_separate_from_delivery_storage_and_ordering_choices():
    raw, _, _ = load_guide()
    steps = {step["id"]: step for step in raw["steps"]}
    contract = steps["queue_02_delivery_contract"]["content"].casefold()
    broker = steps["queue_04_broker"]["content"].casefold()
    ordering = steps["queue_22_order_priority_tradeoff"]["content"].casefold()

    assert "brief facts:" in contract
    assert "does not define exactly-once versus at-least-once" in contract
    assert "design choices in this walkthrough:" in contract
    assert "not against every correlated failure" in contract
    assert "independent failure domains" in broker
    assert "fence a stale leader" in broker
    assert "brief asks for message ordering but leaves its scope open" in ordering
    assert "not a total order" in ordering


def test_retries_dlq_idempotency_and_backpressure_preserve_the_chosen_contract():
    raw, _, _ = load_guide()
    steps = {step["id"]: step for step in raw["steps"]}
    producer = steps["queue_03_publishers"]["content"].casefold()
    worker_ack = steps["queue_16_ack_nack"]["content"].casefold()
    retry = steps["queue_17_retry_queue"]["content"].casefold()
    transfer = steps["queue_18_broker_retry_path"]["content"].casefold()
    redelivery = steps["queue_19_retry_redelivery"]["content"].casefold()
    dead_letter = steps["queue_20_dead_letter_queue"]["content"].casefold()
    pressure = steps["queue_23_scale_and_backpressure"]["scaleTrigger"]["action"].casefold()

    assert "do not assume that the broker deduplicates publishes" in producer
    assert "consumer idempotency is still required" in producer
    assert "idempotency record is committed atomically" in worker_ack
    assert "not an exactly-once side-effect promise" in worker_ack
    assert "original sequence" in retry and "remains the head for its key" in retry
    assert "before advancing or acknowledging" in transfer
    assert "before dispatching a later sequence" in redelivery
    assert "redrives this same sequence ahead of them" in dead_letter
    assert "audited skip" in dead_letter
    assert "retryable outcome" in pressure and "never acknowledge" in pressure


def test_walkthrough_does_not_invent_numeric_service_or_policy_targets():
    raw, _, _ = load_guide()
    authored = json.dumps(raw["steps"][1:], ensure_ascii=False)
    unsupported_numeric_target = re.compile(
        r"\b(?:p\d{2}|\d+(?:\.\d+)?\s*(?:ms|milliseconds?|seconds?|sec|minutes?|mins?|"
        r"hours?|days?|%|replicas?|partitions?|retries|attempts|messages?\s+per\s+second|"
        r"msgs?/s|rps))\b",
        re.IGNORECASE,
    )
    assert unsupported_numeric_target.search(authored) is None
