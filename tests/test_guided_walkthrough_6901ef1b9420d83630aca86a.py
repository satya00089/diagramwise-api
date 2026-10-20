"""Frozen-brief, catalog, and connected replay checks for the hotel booking draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca86a"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
FROZEN_BRIEF = {
    "id": "6901ef1b9420d83630aca86a",
    "title": "Design a Hotel Booking System",
    "description": (
        "Design a reservation system for booking hotel rooms with availability "
        "management and payment processing."
    ),
    "requirements": [
        "Search hotels by location and dates",
        "Check room availability in real-time",
        "Book and cancel reservations",
        "Handle concurrent booking requests",
        "Payment processing and confirmation",
        "Manage room inventory",
        "Support different room types",
        "Handle millions of bookings",
    ],
    "constraints": [
        "Prevent double booking",
        "Handle race conditions for same room",
        "Real-time availability updates",
        "Support cancellations and refunds",
        "Transaction consistency for payments",
    ],
    "hints": [
        "Optimistic or pessimistic locking",
        "Database transactions for booking",
        "Inventory management system",
        "Event sourcing for audit trail",
        "Cache room availability",
    ],
}
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
GRAPH_ACTION_TYPES = {"add_component", "add_connection"}


def legacy_anchor_ids(*, requirements=(), constraints=()):
    return {
        *(f"legacy-requirement:{index}" for index in requirements),
        *(f"legacy-constraint:{index}" for index in constraints),
    }


EXPECTED_ACTION_ANCHORS = {
    "hbs_02": legacy_anchor_ids(requirements=(1, 3)),
    "hbs_03": legacy_anchor_ids(requirements=(1, 3)),
    "hbs_04": legacy_anchor_ids(requirements=(1, 3)),
    "hbs_05": legacy_anchor_ids(requirements=(1, 2, 7)),
    "hbs_06": legacy_anchor_ids(requirements=(1,)),
    "hbs_07": legacy_anchor_ids(requirements=(2,), constraints=(3,)),
    "hbs_08": legacy_anchor_ids(
        requirements=(2, 3, 4, 6, 7), constraints=(1, 2)
    ),
    "hbs_09": legacy_anchor_ids(
        requirements=(3, 4, 5, 6, 7), constraints=(1, 2, 5)
    ),
    "hbs_10": legacy_anchor_ids(requirements=(1,)),
    "hbs_11": legacy_anchor_ids(requirements=(3,)),
    "hbs_12": legacy_anchor_ids(requirements=(1,)),
    "hbs_13": legacy_anchor_ids(requirements=(2,)),
    "hbs_14": legacy_anchor_ids(requirements=(1, 2, 7), constraints=(3,)),
    "hbs_15": legacy_anchor_ids(
        requirements=(3, 4, 5, 6, 7), constraints=(1, 2, 5)
    ),
    "hbs_21": legacy_anchor_ids(requirements=(5,), constraints=(4, 5)),
    "hbs_22": legacy_anchor_ids(requirements=(3, 5), constraints=(3, 4)),
    "hbs_23": legacy_anchor_ids(requirements=(3, 5)),
    "hbs_24": legacy_anchor_ids(requirements=(5,), constraints=(5,)),
    "hbs_25": legacy_anchor_ids(requirements=(5,), constraints=(5,)),
    "hbs_26": legacy_anchor_ids(requirements=(3, 5), constraints=(3, 4)),
    "hbs_27": legacy_anchor_ids(requirements=(3, 5)),
    "hbs_28": legacy_anchor_ids(requirements=(2, 6), constraints=(3,)),
    "hbs_29": legacy_anchor_ids(requirements=(1, 2), constraints=(3,)),
    "hbs_35": legacy_anchor_ids(requirements=(2, 8), constraints=(2, 3)),
}


UNSUPPORTED_NUMERIC_PROMISE = re.compile(
    r"\b(?:p95|p99)\b"
    r"|\b\d+(?:\.\d+)?\s*(?:%|ms|milliseconds?|seconds?|minutes?|hours?|"
    r"qps|rps|requests?\s+per\s+second|bookings?\s+per\s+(?:second|minute|hour|day))\b"
    r"|\b\d+(?:\.\d+)?\s*(?:k|m|million|billion)\+?\s+"
    r"(?:concurrent\s+)?(?:requests?|bookings?|users?|rooms?|hotels?)\b",
    re.IGNORECASE,
)


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def frozen_problem():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def expected_anchors():
    return {
        *(f"legacy-requirement:{index}" for index in range(1, len(FROZEN_BRIEF["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(FROZEN_BRIEF["constraints"]) + 1)),
    }


def test_frozen_brief_schema_version_and_actionable_anchor_coverage():
    problem = frozen_problem()
    brief_snapshot = {key: problem[key] for key in FROZEN_BRIEF}
    raw, guide = load_guide()

    assert brief_snapshot == FROZEN_BRIEF
    assert problem["has_guided_walkthrough"] is False
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 36
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES and step.content.strip() for step in guide.steps)

    actual_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert actual_anchors == expected_anchors()
    actionable_steps = {
        step["id"]: set(step.get("requirementIds", []))
        for step in raw["steps"]
        if step["type"] in GRAPH_ACTION_TYPES | {"scale_trigger"}
    }
    assert actionable_steps == EXPECTED_ACTION_ANCHORS
    actionable_anchors = set().union(*actionable_steps.values())
    assert actionable_anchors == expected_anchors(), (
        "Every brief requirement and constraint must trace to a specific graph or scale action."
    )


def walk_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_strings(child)


def test_brief_facts_assumptions_and_unquantified_targets_stay_distinct():
    raw, _ = load_guide()
    steps = {step["id"]: step for step in raw["steps"]}
    scope = steps["hbs_01"]["content"].casefold()

    assert "brief facts:" in scope
    assert "design assumptions in this draft:" in scope
    assert "candidate approaches, not additional requirements" in scope
    assert "quantify availability freshness or traffic" in scope

    assert "not a reservation guarantee" in steps["hbs_05"]["content"]
    assert "no cache freshness interval is specified" in steps["hbs_07"]["content"]
    assert "no measurable freshness interval" in steps["hbs_14"]["content"]
    assert "no promised freshness interval" in steps["hbs_29"]["content"]
    assert "not demonstrated capacity" in steps["hbs_34"]["content"]
    assert "not a shared acid transaction" in steps["hbs_30"]["decision"]["chosen"].casefold()

    guide_text = " ".join(walk_strings(raw["steps"]))
    assert UNSUPPORTED_NUMERIC_PROMISE.search(guide_text) is None


def test_phases_ordered_actions_and_connection_types_are_well_formed():
    raw, guide = load_guide()
    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    nodes = {}
    edge_ids = set()
    component_action_ids = []
    connection_action_ids = []
    for step in guide.steps:
        if step.type == "add_component":
            assert step.component is not None
            component = step.component
            assert component.nodeId not in nodes
            assert component.position.keys() >= {"x", "y"}
            nodes[component.nodeId] = component
            component_action_ids.append(step.id)
        elif step.type == "add_connection":
            assert step.connection is not None
            connection = step.connection
            assert connection.edgeId not in edge_ids
            assert connection.connectionType in CONNECTION_TYPES
            assert {connection.sourceNodeId, connection.targetNodeId} <= nodes.keys()
            edge_ids.add(connection.edgeId)
            connection_action_ids.append(step.id)

    assert len(nodes) == 10
    assert len(edge_ids) == 13
    assert len(component_action_ids) == len(set(component_action_ids))
    assert len(connection_action_ids) == len(set(connection_action_ids))


def test_replay_contains_every_explicit_action_in_one_connected_graph():
    raw, _ = load_guide()
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {node["id"]: node for node in architecture["components"]}
    edges = architecture["connections"]
    expected_actions = [
        step["id"] for step in raw["steps"] if step["type"] in GRAPH_ACTION_TYPES
    ]

    assert len(nodes) == 10
    assert len(edges) == 13
    assert replay["appliedStepIds"] == expected_actions
    assert replay["acceptedDecisions"] == [], (
        "Reading a decision point must not be counted as an accepted learner decision."
    )
    assert nodes["hbs_booking_store"]["properties"]["type"] == "RDBMS"
    assert nodes["hbs_booking_store"]["properties"]["workload"] == "OLTP"
    assert nodes["hbs_availability_cache"]["properties"]["cacheStrategy"] == "cache-aside"
    assert nodes["hbs_payment_service"]["properties"]["originalComponentId"] == "payment-service"

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["hbs_guest_client"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == set(nodes)


def test_catalog_ids_properties_and_select_values_are_supported():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = [step["component"] for step in raw["steps"] if step.get("component")]

    assert components
    assert all(component["componentType"] != "custom-component" for component in components)
    for step in raw["steps"]:
        component = step.get("component")
        if not component:
            continue
        assert component["properties"]["componentName"] == component["label"]
        assert component["properties"]["purpose"].strip()
        assert component["highlightReason"].strip()
        component_type = component["componentType"]
        match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
        assert match is not None, f"{step['id']}: unknown catalog ID {component_type}"
        block_end = catalog.find("\n  },", match.start())
        assert block_end != -1
        component_block = catalog[match.start():block_end]
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', component_block))
        properties = component["properties"]
        assert set(properties) <= supported, (
            f"{step['id']}: unsupported properties {sorted(set(properties) - supported)}"
        )

        for key, value in properties.items():
            field_start = component_block.index(f'key: "{key}"')
            field_end = component_block.find("},", field_start)
            assert field_end != -1, f"{step['id']}/{key}: incomplete catalog field"
            field = component_block[field_start:field_end]
            field_type = re.search(r'\btype:\s*"([^"]+)"', field)
            assert field_type is not None, f"{step['id']}/{key}: missing catalog field type"
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
                    f"{step['id']}/{key}: {value!r} is not a supported option"
                )


def test_hotel_decisions_cover_contention_payments_cancellation_and_scale():
    raw, _ = load_guide()
    decisions = {
        step["id"]: step["decision"]
        for step in raw["steps"]
        if step["type"] == "decision_point"
    }
    assert {
        "hbs_16",
        "hbs_17",
        "hbs_18",
        "hbs_30",
        "hbs_31",
        "hbs_32",
        "hbs_34",
    } <= decisions.keys()
    assert all(decision["alternatives"] for decision in decisions.values())

    chosen = {step_id: decision["chosen"].casefold() for step_id, decision in decisions.items()}
    assert "authoritative" in chosen["hbs_16"] and "cache" in chosen["hbs_16"]
    assert "room type" in chosen["hbs_17"] and "stay date" in chosen["hbs_17"]
    assert all(
        signal in chosen["hbs_18"]
        for signal in ("transaction", "lock", "idempotency", "every night")
    )
    assert all(
        signal in chosen["hbs_30"]
        for signal in ("saga", "idempotency", "reconciled", "refund")
    )
    assert all(
        signal in chosen["hbs_31"]
        for signal in ("cancellation policy", "refund", "not specified")
    )
    assert all(signal in chosen["hbs_32"] for signal in ("outbox", "audit", "event sourcing"))
    assert all(signal in chosen["hbs_34"] for signal in ("millions", "measured", "transactionally"))

    scope = raw["steps"][0]["content"].casefold()
    assert "design assumptions in this draft" in scope
    assert "database engine" in scope
    assert "cancellation/refund eligibility" in scope
    assert "quantify availability freshness or traffic" in scope
    assert "deployment geography" in scope
