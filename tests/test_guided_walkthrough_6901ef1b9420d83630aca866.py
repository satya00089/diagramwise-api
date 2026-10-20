"""Structural and brief-traceability contract for the Google Calendar review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca866"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

# This task supplied the current AWS brief verbatim. The older local fixture has
# different wording for its description, requirements, and constraints, so it
# is not treated as the source of truth for live legacy-anchor labels here.
TITLE = "Design Google Calendar"
DESCRIPTION = "Design a calendar application for creating, managing, and sharing events and appointments."
REQUIREMENTS = [
    "create/update/delete events",
    "recurring events",
    "share calendars/events",
    "invitations/reminders",
    "availability/scheduling",
    "multiple calendars/user",
    "millions of users",
    "device sync",
]
CONSTRAINTS = [
    "concurrent updates to same event",
    "timezones",
    "real-time notifications",
    "efficient conflict detection",
    "cross-device consistency",
]
STEP_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "decision_point",
    "scale_trigger",
}
CONNECTION_TYPES = {
    "http",
    "api-call",
    "database-connection",
    "message-queue",
    "data-flow",
}


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


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
        field_start = block.index(f'key: "{key}"')
        field_end = block.find("},", field_start)
        assert field_end != -1, f"{step_id}/{key}: catalog property field is incomplete"
        field = block[field_start:field_end]
        field_type = re.search(r'\btype:\s*"([^"]+)"', field)
        assert field_type is not None, f"{step_id}/{key}: catalog property has no type"
        kind = field_type.group(1)
        if kind == "boolean":
            assert type(value) is bool, f"{step_id}/{key} must be boolean"
        elif kind == "number":
            assert type(value) in (int, float), f"{step_id}/{key} must be numeric"
        elif kind == "select":
            options = re.search(r'\boptions:\s*\[([^\]]+)\]', field)
            assert options is not None, f"{step_id}/{key}: select has no options"
            assert value in re.findall(r'"([^"]+)"', options.group(1)), (
                f"{step_id}/{key} is not a catalog select option"
            )
        elif kind in {"text", "textarea"}:
            assert isinstance(value, str), f"{step_id}/{key} must be text"


def test_model_steps_and_phase_ranges_are_well_formed():
    raw, guide = load_guide()

    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0-review"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 50
    assert [step.stepNumber for step in guide.steps] == list(range(1, 51))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert {step.type for step in guide.steps} == STEP_TYPES

    expected_start = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == expected_start
        assert start <= end <= guide.totalSteps
        assert all(step.phase == phase.name for step in guide.steps[start - 1 : end])
        expected_start = end + 1
    assert expected_start == guide.totalSteps + 1
    assert raw["totalSteps"] == len(raw["steps"])

    for step in guide.steps:
        assert step.title and step.content and step.requirementIds
        assert set(step.requirementIds) <= {
            *(f"legacy-requirement:{index}" for index in range(1, len(REQUIREMENTS) + 1)),
            *(f"legacy-constraint:{index}" for index in range(1, len(CONSTRAINTS) + 1)),
        }
        if step.type == "add_component":
            assert step.component is not None
            assert step.component.position.keys() == {"x", "y"}
            assert step.component.label == step.component.properties["componentName"]
            assert not step.connection and not step.decision
        elif step.type == "add_connection":
            assert step.connection is not None
            assert step.connection.connectionType in CONNECTION_TYPES
            assert step.connection.label and step.connection.description
            assert not step.component and not step.decision
        elif step.type == "decision_point":
            assert step.decision is not None and step.componentUpdate is not None
            assert step.decision.question and step.decision.chosen and step.decision.chosenReason
            assert len(step.decision.alternatives) >= 2
            assert all(option.option and option.tradeoff for option in step.decision.alternatives)
        elif step.type == "scale_trigger":
            assert step.scaleTrigger is not None and step.componentUpdate is not None
            assert step.scaleTrigger.metric and step.scaleTrigger.action and step.scaleTrigger.impact
            assert step.scaleTrigger.component is not None


def test_exact_live_brief_and_every_legacy_anchor_has_an_action():
    raw, guide = load_guide()
    expected_ids = {
        *(f"legacy-requirement:{index}" for index in range(1, len(REQUIREMENTS) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(CONSTRAINTS) + 1)),
    }
    mapped_ids = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert mapped_ids == expected_ids

    brief = raw["steps"][0]["content"]
    for item in [TITLE, DESCRIPTION, *REQUIREMENTS, *CONSTRAINTS]:
        assert item in brief, f"Live brief item missing from guide framing: {item}"

    action_anchors = {
        "legacy-requirement:1": "calendar_09",
        "legacy-requirement:2": "calendar_27",
        "legacy-requirement:3": "calendar_14",
        "legacy-requirement:4": "calendar_25",
        "legacy-requirement:5": "calendar_17",
        "legacy-requirement:6": "calendar_12",
        "legacy-requirement:7": "calendar_48",
        "legacy-requirement:8": "calendar_36",
        "legacy-constraint:1": "calendar_11",
        "legacy-constraint:2": "calendar_30",
        "legacy-constraint:3": "calendar_25",
        "legacy-constraint:4": "calendar_17",
        "legacy-constraint:5": "calendar_36",
    }
    steps = {step.id: step for step in guide.steps}
    for anchor, step_id in action_anchors.items():
        assert anchor in steps[step_id].requirementIds
        assert steps[step_id].type != "explanation"


def test_components_and_updates_use_only_catalog_types_and_properties():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step.get("component")
    }
    assert len(components) == 16
    assert all(component["componentType"] != "custom-component" for component in components.values())

    for step in raw["steps"]:
        component = step.get("component")
        if component:
            assert component["properties"]["componentName"] == component["label"]
            assert len(component["properties"]["purpose"]) >= 70
            assert component["highlightReason"]
            assert_catalog_properties(
                catalog, component["componentType"], component["properties"], step["id"]
            )

        trigger_component = (step.get("scaleTrigger") or {}).get("component")
        if trigger_component:
            assert trigger_component["properties"]["componentName"] == trigger_component["label"]
            assert len(trigger_component["properties"]["purpose"]) >= 70
            assert_catalog_properties(
                catalog,
                trigger_component["componentType"],
                trigger_component["properties"],
                step["id"],
            )

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


def test_replay_builds_one_connected_calendar_graph_with_unique_actions():
    raw, _ = load_guide()
    component_ids = [
        step["component"]["nodeId"]
        for step in raw["steps"]
        if step.get("component")
    ]
    edge_ids = [
        step["connection"]["edgeId"]
        for step in raw["steps"]
        if step.get("connection")
    ]
    assert len(component_ids) == len(set(component_ids)) == 16
    assert len(edge_ids) == len(set(edge_ids)) == 25

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    edges = architecture["connections"]
    assert len(nodes) == 16
    assert len(edges) == 25
    assert len(replay["appliedStepIds"]) == 48
    assert len(replay["explanationOnlyStepIds"]) == 2
    assert len(replay["acceptedDecisions"]) == 5
    assert replay["provenance"]["problemId"] == PROBLEM_ID
    assert replay["provenance"]["walkthroughVersion"] == "1.0-review"

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] in CONNECTION_TYPES
        assert edge["label"] and edge["description"]
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["calendar_web"])
    while pending:
        node_id = pending.popleft()
        if node_id in reached:
            continue
        reached.add(node_id)
        pending.extend(neighbors[node_id] - reached)
    assert reached == set(nodes)

    edge_pairs = {(edge["source"], edge["target"]) for edge in edges}
    assert {
        ("calendar_web", "calendar_gateway"),
        ("calendar_mobile", "calendar_gateway"),
        ("calendar_gateway", "calendar_auth"),
        ("calendar_gateway", "calendar_api"),
        ("calendar_api", "calendar_store"),
        ("calendar_api", "calendar_sharing"),
        ("calendar_sharing", "calendar_store"),
        ("calendar_api", "calendar_availability"),
        ("calendar_availability", "calendar_store"),
        ("calendar_availability", "calendar_cache"),
        ("calendar_store", "calendar_outbox"),
        ("calendar_outbox", "calendar_broker"),
        ("calendar_broker", "calendar_recurrence"),
        ("calendar_recurrence", "calendar_store"),
        ("calendar_recurrence", "calendar_reminder_queue"),
        ("calendar_reminder_queue", "calendar_notifications"),
        ("calendar_gateway", "calendar_sync"),
        ("calendar_broker", "calendar_sync"),
        ("calendar_sync", "calendar_web"),
        ("calendar_sync", "calendar_mobile"),
        ("calendar_notifications", "calendar_mobile"),
        ("calendar_api", "calendar_monitoring"),
        ("calendar_availability", "calendar_monitoring"),
        ("calendar_broker", "calendar_monitoring"),
        ("calendar_reminder_queue", "calendar_monitoring"),
    } == edge_pairs


def test_calendar_content_covers_time_conflicts_recovery_and_privacy():
    raw, _ = load_guide()
    content = json.dumps(raw, ensure_ascii=False).casefold()
    for concept in (
        "iana timezone",
        "daylight-saving",
        "tombstone",
        "idempotency",
        "payload hash",
        "outbox",
        "dead-letter",
        "watermark",
        "base revision",
        "crdt",
        "revocation",
        "backup restore",
        "privacy",
        "cross-calendar",
    ):
        assert concept in content, f"Missing calendar-specific design concern: {concept}"


def test_calendar_critical_step_anchors_are_semantically_narrow():
    _, guide = load_guide()
    steps = {step.id: set(step.requirementIds) for step in guide.steps}
    expected = {
        "calendar_13": {"legacy-requirement:1", "legacy-requirement:2", "legacy-constraint:1", "legacy-constraint:2", "legacy-constraint:5"},
        "calendar_17": {"legacy-requirement:5", "legacy-requirement:6", "legacy-constraint:2", "legacy-constraint:4"},
        "calendar_18": {"legacy-requirement:5", "legacy-requirement:6", "legacy-constraint:4"},
        "calendar_19": {"legacy-requirement:5", "legacy-requirement:6", "legacy-constraint:2", "legacy-constraint:4"},
        "calendar_20": {"legacy-requirement:5", "legacy-requirement:6", "legacy-constraint:4"},
        "calendar_21": {"legacy-requirement:5", "legacy-constraint:4"},
        "calendar_22": {"legacy-requirement:5", "legacy-requirement:6", "legacy-constraint:4"},
        "calendar_27": {"legacy-requirement:2"},
        "calendar_28": {"legacy-requirement:2", "legacy-constraint:1"},
        "calendar_29": {"legacy-requirement:2", "legacy-requirement:5", "legacy-constraint:1", "legacy-constraint:4"},
        "calendar_30": {"legacy-requirement:2", "legacy-requirement:5", "legacy-constraint:2"},
        "calendar_31": {"legacy-requirement:2", "legacy-requirement:4", "legacy-constraint:3"},
        "calendar_32": {"legacy-requirement:2", "legacy-requirement:4", "legacy-constraint:1", "legacy-constraint:2", "legacy-constraint:3"},
        "calendar_33": {"legacy-requirement:3", "legacy-requirement:4", "legacy-constraint:3"},
        "calendar_34": {"legacy-requirement:4", "legacy-constraint:1", "legacy-constraint:3"},
        "calendar_35": {"legacy-requirement:4", "legacy-constraint:1", "legacy-constraint:3"},
        "calendar_36": {"legacy-requirement:1", "legacy-requirement:3", "legacy-requirement:8", "legacy-constraint:5"},
        "calendar_37": {"legacy-requirement:8", "legacy-constraint:5"},
        "calendar_38": {"legacy-requirement:8", "legacy-constraint:5"},
        "calendar_39": {"legacy-requirement:1", "legacy-requirement:8", "legacy-constraint:5"},
        "calendar_40": {"legacy-requirement:1", "legacy-requirement:8", "legacy-constraint:1", "legacy-constraint:5"},
        "calendar_41": {"legacy-requirement:4", "legacy-requirement:8", "legacy-constraint:3", "legacy-constraint:5"},
        "calendar_42": {"legacy-requirement:1", "legacy-requirement:8", "legacy-constraint:1", "legacy-constraint:5"},
    }
    for step_id, expected_ids in expected.items():
        assert steps[step_id] == expected_ids, f"{step_id}: misleading or missing brief anchors"


def test_recurrence_keeps_local_time_and_does_not_invent_a_dst_policy():
    raw, _ = load_guide()
    steps = {step["id"]: step for step in raw["steps"]}
    recurrence = steps["calendar_27"]["content"].casefold()
    timezone = steps["calendar_30"]["content"].casefold()
    decision = steps["calendar_30"]["decision"]

    assert "recurrence master rule" in recurrence
    assert "exceptions and cancellations" in recurrence
    assert "iana timezone" in timezone
    assert "local wall-clock rule" in timezone
    assert "all-day dates" in timezone
    assert "nonexistent or repeated local times" in timezone
    assert "the supplied brief does not choose those policies" in timezone
    assert "explicit dst policy" in decision["chosen"].casefold()
    assert "fixed duration" in decision["alternatives"][0]["option"].casefold()
    assert "drift" in decision["alternatives"][0]["tradeoff"].casefold()


def test_concurrent_event_edits_use_revision_conflicts_not_silent_overwrites():
    raw, _ = load_guide()
    steps = {step["id"]: step for step in raw["steps"]}
    content = steps["calendar_11"]["content"].casefold()
    decision = steps["calendar_11"]["decision"]

    for behavior in (
        "if-match/baseRevision".casefold(),
        "return a conflict",
        "latest authorized version",
        "do not silently overwrite",
        "payload hash",
    ):
        assert behavior in content
    assert "last-write-wins" in decision["alternatives"][0]["option"].casefold()
    assert "clock skew" in decision["alternatives"][0]["tradeoff"].casefold()


def test_invitation_and_reminder_delivery_is_durable_but_not_promised_exactly_once():
    raw, _ = load_guide()
    steps = {step["id"]: step for step in raw["steps"]}
    queue = steps["calendar_31"]["content"].casefold()
    delivery = steps["calendar_33"]["content"].casefold()
    retries = steps["calendar_35"]["content"].casefold()

    assert "event revision, occurrence, recipient, and reminder offset" in queue
    assert "rechecks that the event still exists" in queue
    assert "provider acceptance is not proof" in delivery
    assert "at-least-once queues" in retries
    assert "accepted-by-provider from delivered-to-device" in retries
    assert "unique delivery identity" in retries


def test_availability_is_freshness_marked_and_advisory_not_an_atomic_reservation():
    raw, _ = load_guide()
    steps = {step["id"]: step for step in raw["steps"]}
    service = steps["calendar_17"]["content"].casefold()
    cache = steps["calendar_21"]["content"].casefold()
    conflict = steps["calendar_22"]["content"].casefold()

    assert "freshness watermark" in service
    assert "as-of time" in cache
    assert "must not claim strong current availability" in cache
    assert "not automatically a write rejection" in conflict
    assert "free/busy check can race with another edit" in conflict
    assert "exclusive resource booking" in conflict
    assert "do not infer that invariant from this brief" in conflict


def test_cross_device_contract_states_write_read_behavior_and_staleness_tradeoff():
    raw, _ = load_guide()
    steps = {step["id"]: step for step in raw["steps"]}
    contract = steps["calendar_13"]["content"].casefold()
    mobile = steps["calendar_40"]["content"].casefold()
    push = steps["calendar_41"]["content"].casefold()

    for behavior in (
        "canonical event reads and revision checks use the authoritative store",
        "return write success only after commit",
        "availability is a derived projection with an as-of watermark",
        "other devices apply durable cursor pages",
        "both views may lag",
        "push is only a hint",
        "trades immediate cross-device and availability freshness",
        "the brief defines no propagation slo",
    ):
        assert behavior in contract
    assert "persists the new cursor only after applying all page records" in mobile
    assert "can still converge if push is delayed, collapsed, or lost" in push


def test_calendar_brief_does_not_gain_unprovided_numeric_service_slos():
    raw, _ = load_guide()
    narrative = "\n".join(step.get("content", "") for step in raw["steps"])
    framing = raw["steps"][0]["content"].casefold()

    assert "no dau/peak write rate" in framing
    assert "the brief gives no" in framing
    assert "latency or availability slo" in framing
    numeric_slo = re.compile(
        r"\b(?:latency|availability|notification|sync|freshness)[^\n.]{0,60}"
        r"(?:under|below|within|at most|<=)\s*\d+(?:\.\d+)?\s*"
        r"(?:ms|milliseconds|s|seconds|minutes|hours|%)\b",
        re.IGNORECASE,
    )
    assert not numeric_slo.search(narrative)
