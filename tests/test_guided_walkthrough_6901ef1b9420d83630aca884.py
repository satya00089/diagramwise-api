"""Frozen live-brief, catalog, and graph-replay checks for Netflix screen limits."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca884"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
FROZEN_BRIEFS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"


def load_frozen_brief():
    rows = json.loads(FROZEN_BRIEFS_PATH.read_text(encoding="utf-8"))
    matches = [row for row in rows if row.get("id") == PROBLEM_ID]
    assert len(matches) == 1, f"Expected one frozen brief for {PROBLEM_ID}"
    return matches[0]


FROZEN_BRIEF = load_frozen_brief()
ANCHORS = {
    *(f"legacy-requirement:{index}" for index in range(1, len(FROZEN_BRIEF["requirements"]) + 1)),
    *(f"legacy-constraint:{index}" for index in range(1, len(FROZEN_BRIEF["constraints"]) + 1)),
}
ACTION_TYPES = {"add_component", "add_connection"}
STEP_TYPES = ACTION_TYPES | {"scale_trigger", "explanation"}
CONNECTION_TYPES = {
    "http",
    "api-call",
    "database-connection",
    "message-queue",
    "data-flow",
}
EXPECTED_PHASES = [
    ("Set the access contract and protect the entry point", 1, 8),
    ("Track leases and reserve a screen atomically", 9, 14),
    ("Publish lifecycle events and reclaim expired sessions", 15, 21),
    ("Survive failure, detect abuse, and scale", 22, 31),
]
EXPECTED_ACTION_ANCHORS = {
    "netflix_02_client": "r3 r4",
    "netflix_03_gateway": "r3 c1 c5",
    "netflix_04_client_gateway": "r3 c1 c2",
    "netflix_05_rate_limiter": "c5",
    "netflix_06_gateway_limiter": "c5",
    "netflix_07_session_service": "r1 r2 r3 r5 r7 c1 c5",
    "netflix_08_limiter_service": "r3 c5",
    "netflix_09_authoritative_store": "r1 r2 r5 r7 c3 c4",
    "netflix_10_service_store": "r1 r2 r3 r5 c1 c2 c3 c4",
    "netflix_11_store_result": "r1 r2 c3 c4",
    "netflix_12_service_client_lease": "r2 r3 c1 c3 c5",
    "netflix_15_outbox_relay": "r3 r6 r8",
    "netflix_16_store_outbox": "r3 r6 r8",
    "netflix_17_event_bus": "r3 r6 r7 r8",
    "netflix_18_relay_bus": "r3 r6 r8",
    "netflix_19_lifecycle_worker": "r4 r6 r8 c3 c4",
    "netflix_20_bus_worker": "r3 r6 r8",
    "netflix_21_worker_store": "r4 r8 c2 c3 c4",
    "netflix_22_monitoring": "r6 r7 c1 c5",
    "netflix_23_service_metrics": "r6 c1 c5",
    "netflix_24_store_metrics": "r1 r2 r6 r7 c3 c4",
    "netflix_25_bus_metrics": "r3 r6 r8",
}


def expand_anchor_codes(codes: str) -> set[str]:
    return {
        f"legacy-{'requirement' if code[0] == 'r' else 'constraint'}:{code[1:]}"
        for code in codes.split()
    }
EXPECTED_ACTION_ANCHORS = {
    "netflix_02_client": "r3 r4",
    "netflix_03_gateway": "r3 c1 c5",
    "netflix_04_client_gateway": "r3 c1 c2",
    "netflix_05_rate_limiter": "c5",
    "netflix_06_gateway_limiter": "c5",
    "netflix_07_session_service": "r1 r2 r3 r5 r7 c1 c5",
    "netflix_08_limiter_service": "r3 c5",
    "netflix_09_authoritative_store": "r1 r2 r5 r7 c3 c4",
    "netflix_10_service_store": "r1 r2 r3 r5 c1 c2 c3 c4",
    "netflix_11_store_result": "r1 r2 c3 c4",
    "netflix_12_service_client_lease": "r2 r3 c1 c3 c5",
    "netflix_15_outbox_relay": "r3 r6 r8",
    "netflix_16_store_outbox": "r3 r6 r8",
    "netflix_17_event_bus": "r3 r6 r7 r8",
    "netflix_18_relay_bus": "r3 r6 r8",
    "netflix_19_lifecycle_worker": "r4 r6 r8 c3 c4",
    "netflix_20_bus_worker": "r3 r6 r8",
    "netflix_21_worker_store": "r4 r8 c2 c3 c4",
    "netflix_22_monitoring": "r6 r7 c1 c5",
    "netflix_23_service_metrics": "r6 c1 c5",
    "netflix_24_store_metrics": "r1 r2 r6 r7 c3 c4",
    "netflix_25_bus_metrics": "r3 r6 r8",
}


def expand_anchor_codes(codes: str) -> set[str]:
    return {
        f"legacy-{'requirement' if code[0] == 'r' else 'constraint'}:{code[1:]}"
        for code in codes.split()
    }


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"{step_id}: unknown catalog component {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), f"{step_id}: incomplete catalog component entry"
    return catalog[match.start() : block_end]


def assert_supported_properties(catalog: str, component_type: str, properties: dict, step_id: str):
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
            assert options, f"{step_id}/{key}: missing select options"
            allowed = set(re.findall(r'"([^"]+)"', options.group(1)))
            assert value in allowed, f"{step_id}/{key}: unsupported option {value!r}"


def reachable(start: str, neighbors: dict[str, set[str]]) -> set[str]:
    reached = set()
    pending = deque([start])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    return reached


def test_frozen_live_brief_and_review_draft_schema():
    raw, guide = load_guide()
    first_step = guide.steps[0]

    assert guide.problem_id == FROZEN_BRIEF["id"]
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 31
    assert raw["totalSteps"] == len(raw["steps"])
    assert {step.type for step in guide.steps} == STEP_TYPES
    assert [step.stepNumber for step in guide.steps] == list(range(1, 32))
    assert [(phase.name, *phase.stepRange) for phase in guide.phases] == EXPECTED_PHASES
    for value in (
        FROZEN_BRIEF["title"],
        FROZEN_BRIEF["description"],
        *FROZEN_BRIEF["requirements"],
        *FROZEN_BRIEF["constraints"],
        *FROZEN_BRIEF["hints"],
    ):
        assert value.casefold() in first_step.content.casefold(), f"Live brief omitted: {value}"
    assert "not supplied targets" in first_step.content
    assert "review-draft" in guide.version


def test_phases_and_every_live_requirement_constraint_have_graph_action_anchors():
    _, guide = load_guide()

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end <= guide.totalSteps
        assert all(step.phase == phase.name for step in guide.steps[start - 1 : end])
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    all_anchors = set()
    action_anchors = set()
    for step in guide.steps:
        anchors = set(step.requirementIds)
        assert len(anchors) == len(step.requirementIds), f"{step.id}: duplicate anchor"
        assert anchors <= ANCHORS, f"{step.id}: unknown anchor(s) {sorted(anchors - ANCHORS)}"
        all_anchors.update(anchors)
        if step.type in ACTION_TYPES:
            action_anchors.update(anchors)
            assert anchors == expand_anchor_codes(EXPECTED_ACTION_ANCHORS[step.id]), (
                f"{step.id}: imprecise requirement-to-action anchors"
            )
    assert {step.id for step in guide.steps if step.type in ACTION_TYPES} == set(EXPECTED_ACTION_ANCHORS)
    assert all_anchors == ANCHORS
    assert action_anchors == ANCHORS


def test_catalog_components_and_replayed_graph_are_connected_and_end_to_end():
    raw, guide = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}
    edges = {}

    for step in guide.steps:
        if step.type == "add_component":
            component = step.component
            assert component is not None
            assert component.nodeId not in components
            assert set(component.position) == {"x", "y"}
            assert all(type(value) in {int, float} for value in component.position.values())
            assert component.properties["componentName"] == component.label
            assert len(component.properties["purpose"]) >= 60
            assert component.componentType != "custom-component"
            assert component.highlightReason
            assert_supported_properties(catalog, component.componentType, component.properties, step.id)
            components[component.nodeId] = component
        elif step.type == "add_connection":
            connection = step.connection
            assert connection is not None
            assert connection.edgeId not in edges
            assert connection.sourceNodeId in components
            assert connection.targetNodeId in components
            assert connection.connectionType in CONNECTION_TYPES
            assert connection.label and connection.description
            edges[connection.edgeId] = connection

    assert len(components) == 9
    assert len(edges) == 13

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    replayed_edges = architecture["connections"]
    assert set(nodes) == set(components)
    assert len(replayed_edges) == len(edges)

    neighbors = {node_id: set() for node_id in nodes}
    edge_pairs = set()
    for edge in replayed_edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
        edge_pairs.add((edge["source"], edge["target"]))
    assert reachable("netflix_clients", neighbors) == set(nodes)
    assert {
        ("netflix_clients", "netflix_gateway"),
        ("netflix_gateway", "netflix_rate_limiter"),
        ("netflix_rate_limiter", "netflix_session_service"),
        ("netflix_session_service", "netflix_session_store"),
        ("netflix_session_store", "netflix_outbox_relay"),
        ("netflix_outbox_relay", "netflix_session_bus"),
        ("netflix_session_bus", "netflix_lifecycle_worker"),
        ("netflix_lifecycle_worker", "netflix_session_store"),
    } <= edge_pairs


def test_screen_limit_correctness_security_partition_and_lifecycle_decisions_are_explicit():
    raw, _ = load_guide()
    authored = json.dumps(raw, ensure_ascii=False).casefold()

    for phrase in (
        "conditional transaction",
        "idempotency key",
        "one home region",
        "fails closed",
        "stale replica",
        "device-bound lease",
        "proof-of-possession",
        "do not treat source ip as device identity",
        "transactional outbox",
        "ttl timing is asynchronous",
        "tier downgrade",
        "heartbeat writes per second",
        "one million active streams",
        "33,000 heartbeat renewals per second",
        "no path grants more committed active sessions than the authoritative tier cap",
        "no exact latency slo",
        "one committed, unexpired playback authorization",
        "two concurrent playback sessions on one device count separately",
        "same idempotency and session ids do not add another slot",
        "at most one reservation commits",
        "stop, expiry, and revocation race on the lease state/version",
        "keep its slot counted until the playback enforcement point confirms stop or the issued lease expires",
        "a self-contained signed lease cannot be recalled offline",
    ):
        assert phrase in authored, f"Missing Netflix session design signal: {phrase}"
