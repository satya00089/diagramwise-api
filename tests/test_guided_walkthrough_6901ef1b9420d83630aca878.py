"""Frozen-brief and replay checks for the on-call escalation review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca878"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

PHASES = [
    ("Contract, assumptions, and ingress", 1, 10),
    ("Identity, incident state, and schedule truth", 11, 20),
    ("Delivery, acknowledgement, and escalation", 21, 36),
    ("Operations and review questions", 37, 40),
]
ACTION_TYPES = {"add_component", "add_connection"}
CONNECTION_TYPES = {
    "https",
    "api-call",
    "database-connection",
    "data-flow",
    "event-stream",
    "message-queue",
}
EXPECTED_COMPONENTS = {
    "oncall_alert_source": "monitoring",
    "oncall_responder_client": "mobile-app",
    "oncall_api_gateway": "api-gateway",
    "oncall_identity_service": "auth-service",
    "oncall_incident_service": "backend-server",
    "oncall_schedule_engine": "backend-server",
    "oncall_primary_store": "database",
    "oncall_delivery_queue": "queue",
    "oncall_delivery_worker": "processing-worker",
    "oncall_channel_dispatcher": "notification-service",
    "oncall_operations_monitoring": "monitoring",
}
def load_candidate():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    matches = [problem for problem in problems if problem["id"] == PROBLEM_ID]
    assert len(matches) == 1
    return raw, GuidedWalkthrough.model_validate(raw), matches[0]


def expected_anchors(problem: dict) -> set[str]:
    return {
        *(f"legacy-requirement:{index}" for index, _ in enumerate(problem["requirements"], 1)),
        *(f"legacy-constraint:{index}" for index, _ in enumerate(problem["constraints"], 1)),
    }


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"{step_id}: unknown catalog component {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), f"{step_id}: incomplete catalog component"
    return catalog[match.start() : block_end]


def assert_supported_properties(catalog: str, component_type: str, properties: dict, step_id: str):
    block = catalog_block(catalog, component_type, step_id)
    supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
    assert set(properties) <= supported, (
        f"{step_id}: unsupported {component_type} properties "
        f"{sorted(set(properties) - supported)}"
    )

    for key, value in properties.items():
        start = re.search(rf'\{{\s*key:\s*"{re.escape(key)}"', block)
        assert start, f"{step_id}: missing property {component_type}.{key}"
        end = block.find("},", start.start())
        assert end > start.start(), f"{step_id}: incomplete property {key}"
        field = block[start.start() : end]
        kind = re.search(r'\btype:\s*"([^"]+)"', field)
        assert kind, f"{step_id}: missing type for {component_type}.{key}"
        property_type = kind.group(1)
        if property_type in {"text", "textarea"}:
            assert isinstance(value, str), f"{step_id}/{key} must be text"
        elif property_type == "boolean":
            assert type(value) is bool, f"{step_id}/{key} must be boolean"
        elif property_type == "number":
            assert type(value) in {int, float}, f"{step_id}/{key} must be numeric"
        elif property_type == "select":
            options = re.search(r'\boptions:\s*\[([^\]]*)\]', field, re.DOTALL)
            assert options, f"{step_id}/{key}: catalog options are missing"
            allowed = set(re.findall(r'"([^"]+)"', options.group(1)))
            assert value in allowed, f"{step_id}/{key}: unsupported option {value!r}"


def reachable(start: str, neighbors: dict[str, set[str]]) -> set[str]:
    seen = set()
    pending = deque([start])
    while pending:
        current = pending.popleft()
        if current not in seen:
            seen.add(current)
            pending.extend(neighbors[current] - seen)
    return seen


def test_frozen_brief_draft_schema_and_phase_order_are_exact():
    raw, guide, problem = load_candidate()

    assert problem["id"] == PROBLEM_ID
    assert set(raw) == {
        "problem_id",
        "version",
        "requirementRevision",
        "totalSteps",
        "phases",
        "steps",
    }
    assert guide.problem_id == problem["id"]
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 40
    assert [(phase.name, *phase.stepRange) for phase in guide.phases] == PHASES
    assert [step.stepNumber for step in guide.steps] == list(range(1, 41))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.title.strip() and step.content.strip() for step in guide.steps)

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end <= guide.totalSteps
        assert all(step.phase == phase.name for step in guide.steps[start - 1 : end])
        next_step = end + 1
    assert next_step == guide.totalSteps + 1


def test_functional_and_nonfunctional_brief_items_are_explicit():
    raw, _, problem = load_candidate()
    content = "\n".join(step["content"] for step in raw["steps"])
    requirement_step = next(step for step in raw["steps"] if step["id"] == "oncall-functional-requirements")
    constraint_step = next(step for step in raw["steps"] if step["id"] == "oncall-quality-constraints")

    assert "Functional requirements (preserved verbatim" in content
    assert "Non-functional constraints (preserved verbatim" in content
    for item in problem["requirements"] + problem["constraints"]:
        assert item in content
    assert all(item in requirement_step["content"] for item in problem["requirements"])
    assert all(item in constraint_step["content"] for item in problem["constraints"])
    assert requirement_step["requirementIds"] == [
        f"legacy-requirement:{index}" for index, _ in enumerate(problem["requirements"], 1)
    ]
    assert constraint_step["requirementIds"] == [
        f"legacy-constraint:{index}" for index, _ in enumerate(problem["constraints"], 1)
    ]


def test_every_brief_anchor_is_present_on_an_ordered_graph_action():
    _, guide, problem = load_candidate()
    expected = expected_anchors(problem)
    seen = set()
    on_actions = set()

    for step in guide.steps:
        anchors = set(step.requirementIds)
        assert len(anchors) == len(step.requirementIds), f"{step.id}: duplicate anchor"
        assert anchors <= expected, f"{step.id}: unknown anchor {anchors - expected}"
        seen.update(anchors)
        if step.type in ACTION_TYPES:
            assert anchors, f"{step.id}: graph action needs requirement or constraint anchors"
            on_actions.update(anchors)

    assert seen == on_actions == expected


def test_notification_channel_targets_match_the_frozen_requirement():
    raw, _, problem = load_candidate()
    channel_requirement = next(
        item for item in problem["requirements"] if "multi-channel notifications" in item.casefold()
    )
    channel_match = re.search(r"\(([^()]*)\)", channel_requirement)
    assert channel_match, "the frozen notification requirement should name its channels"
    channels = [channel.strip() for channel in channel_match.group(1).split(",")]
    dispatch_step = next(step for step in raw["steps"] if step["id"] == "oncall-add-channel-dispatcher")
    dispatch_component = dispatch_step["component"]
    dispatch_text = " ".join(
        (dispatch_step["title"], dispatch_step["content"], dispatch_component["properties"]["purpose"])
    ).casefold()
    assert all(channel.casefold() in dispatch_text for channel in channels)

    components = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step["type"] == "add_component"
    }
    app_delivery = next(
        step["connection"] for step in raw["steps"]
        if step.get("connection", {}).get("edgeId") == "oncall_dispatcher_to_responder"
    )
    assert components[app_delivery["targetNodeId"]]["componentType"] == "mobile-app"
    assert "push" in app_delivery["label"].casefold()
    assert "sms" not in app_delivery["label"].casefold()
    assert "phone" not in app_delivery["label"].casefold()
    assert "sms and phone" in app_delivery["description"].casefold()


def test_catalog_components_and_properties_replay_as_one_connected_graph():
    raw, guide, _ = load_candidate()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    nodes = {}
    edges = []

    for step in guide.steps:
        if step.type == "add_component":
            component = step.component
            assert component is not None
            assert component.componentType != "custom-component"
            assert component.nodeId not in nodes
            assert set(component.position) == {"x", "y"}
            assert component.properties["componentName"] == component.label
            assert len(component.properties["purpose"]) >= 70
            assert component.highlightReason
            assert component.data["originalComponentId"] == component.componentType
            assert_supported_properties(catalog, component.componentType, component.properties, step.id)
            nodes[component.nodeId] = component
        elif step.type == "add_connection":
            connection = step.connection
            assert connection is not None
            assert connection.sourceNodeId in nodes, f"{step.id}: source must precede edge"
            assert connection.targetNodeId in nodes, f"{step.id}: target must precede edge"
            assert connection.connectionType in CONNECTION_TYPES
            assert connection.label and connection.description
            edges.append(connection)

    assert {node_id: node.componentType for node_id, node in nodes.items()} == EXPECTED_COMPONENTS
    assert len(edges) == 15
    assert len({edge.edgeId for edge in edges}) == len(edges)

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    replay_nodes = {component["id"]: component for component in architecture["components"]}
    replay_edges = architecture["connections"]
    assert set(replay_nodes) == set(EXPECTED_COMPONENTS)
    assert len(replay_edges) == len(edges)
    assert replay["appliedStepIds"] == [step.id for step in guide.steps if step.type in ACTION_TYPES]
    assert all(edge["type"] in CONNECTION_TYPES for edge in replay_edges)

    neighbors = {node_id: set() for node_id in replay_nodes}
    pairs = set()
    for edge in replay_edges:
        assert edge["source"] in replay_nodes and edge["target"] in replay_nodes
        pair = frozenset((edge["source"], edge["target"]))
        assert pair not in pairs, "parallel duplicate topology obscures the replay graph"
        pairs.add(pair)
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    assert reachable("oncall_alert_source", neighbors) == set(replay_nodes)


def test_assumptions_failure_recovery_and_fallbacks_are_explicit():
    raw, guide, _ = load_candidate()
    text = json.dumps(raw, ensure_ascii=False).casefold()

    for phrase in (
        "design assumptions, not facts supplied by the problem",
        "does not specify dau",
        "no numeric latency or availability target",
        "at-least-once",
        "idempotency",
        "dead-letter",
        "alternate permitted channel",
        "outbox",
        "daylight-saving",
        "provider acceptance",
        "human acknowledgement",
        "open questions:",
    ):
        assert phrase in text

    decisions = [step for step in guide.steps if step.type == "decision_point"]
    assert len(decisions) >= 5
    assert all(step.decision and step.decision.chosenReason for step in decisions)
    assert all(step.decision.alternatives for step in decisions)
