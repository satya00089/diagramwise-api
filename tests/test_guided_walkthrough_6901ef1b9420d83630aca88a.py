"""Frozen-brief, catalog, and replay checks for the Wire Transfer API review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca88a"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

REQUIREMENTS = [
    "Initiate domestic and international wire transfers",
    "Account verification",
    "Transaction limits and controls",
    "Fraud detection and prevention",
    "Compliance with regulations (AML, KYC)",
    "Transaction status tracking",
    "Idempotency for API calls",
    "Audit trail for all transactions",
]
CONSTRAINTS = [
    "ACID guarantees",
    "High security and encryption",
    "Regulatory compliance",
    "Real-time fraud detection",
    "Zero tolerance for data loss",
]
STEP_TYPES = {
    "explanation", "add_component", "add_connection", "decision_point", "scale_trigger",
}
CONNECTION_TYPES = {
    "http", "api-call", "database-connection", "message-queue", "data-flow",
}


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def frozen_problem():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def test_schema_and_exact_frozen_brief_traceability():
    problem = frozen_problem()
    raw, guide = load_guide()

    assert problem["title"] == "Design and Implement a Wire Transfer API"
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert problem["has_guided_walkthrough"] is False
    assert guide.problem_id == PROBLEM_ID
    assert guide.version.endswith("-review")
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps)
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES for step in guide.steps)

    expected_ids = {
        *(f"legacy-requirement:{index}" for index in range(1, len(REQUIREMENTS) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(CONSTRAINTS) + 1)),
    }
    assert {key for step in guide.steps for key in step.requirementIds} == expected_ids
    action_steps = [
        step for step in guide.steps
        if step.type in {"add_component", "add_connection", "decision_point"}
    ]
    for requirement_id in expected_ids:
        assert any(requirement_id in step.requirementIds for step in action_steps), (
            f"{requirement_id} appears only in lesson text, without an action"
        )

    request = make_request(problem, raw, build_architecture(raw))
    assert request["problem"]["requirements"].splitlines() == REQUIREMENTS
    assert request["problem"]["constraints"].splitlines() == CONSTRAINTS


def test_action_anchors_match_scope_and_review_exercises_all_requirements():
    raw, _ = load_guide()
    steps = {step["id"]: step for step in raw["steps"]}
    expected_anchors = {
        "wire_07": {
            "legacy-requirement:1",
            "legacy-requirement:6",
            "legacy-requirement:7",
        },
        "wire_22": {"legacy-requirement:4", "legacy-constraint:4"},
        "wire_41": {
            "legacy-requirement:6",
            "legacy-requirement:8",
            "legacy-constraint:3",
        },
        "wire_53": {"legacy-constraint:2"},
        "wire_55": {"legacy-constraint:2"},
        "wire_57": {
            *(f"legacy-requirement:{index}" for index in range(1, 9)),
            *(f"legacy-constraint:{index}" for index in range(1, 6)),
        },
    }

    for step_id, expected in expected_anchors.items():
        assert set(steps[step_id]["requirementIds"]) == expected

    final_review = steps["wire_57"]["content"].casefold()
    assert "account ownership and verification failures" in final_review
    assert "kyc/sanctions review outcomes" in final_review
    assert "any quantitative fraud-response target" in final_review


def test_phases_and_actions_are_sequential_and_explicit():
    _, guide = load_guide()
    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    nodes = set()
    edges = set()
    decisions = 0
    for step in guide.steps:
        if step.type == "add_component":
            assert step.component is not None
            assert step.component.nodeId not in nodes
            assert step.component.position.keys() >= {"x", "y"}
            nodes.add(step.component.nodeId)
        elif step.type == "add_connection":
            assert step.connection is not None
            assert step.connection.edgeId not in edges
            assert step.connection.connectionType in CONNECTION_TYPES
            assert {step.connection.sourceNodeId, step.connection.targetNodeId} <= nodes
            edges.add(step.connection.edgeId)
        elif step.type == "decision_point":
            assert step.decision is not None and step.decision.alternatives
            assert step.componentUpdate is not None
            assert step.componentUpdate.nodeId in nodes
            assert step.componentUpdate.properties
            decisions += 1
        elif step.type == "scale_trigger":
            assert step.scaleTrigger is not None
        if step.componentUpdate is not None:
            assert step.componentUpdate.nodeId in nodes

    assert len(nodes) == 20
    assert len(edges) == 31
    assert decisions == 3


def test_existing_catalog_ids_and_editable_properties():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"] if step.get("component")
    }
    assert all(component["componentType"] != "custom-component" for component in additions.values())

    for step in raw["steps"]:
        if step.get("component"):
            component = step["component"]
            component_type = component["componentType"]
            properties = component["properties"]
            assert properties["componentName"] == component["label"]
            assert len(properties["purpose"]) >= 70
            assert component["highlightReason"]
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            component_type = additions[update["nodeId"]]["componentType"]
            properties = update["properties"]
        else:
            continue

        match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
        assert match is not None, f"{step['id']}: unknown catalog ID {component_type}"
        block_end = catalog.find("\n  },", match.start())
        assert block_end != -1
        component_block = catalog[match.start():block_end]
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', component_block))
        assert set(properties) <= supported, (
            f"{step['id']}: unsupported properties {sorted(set(properties) - supported)}"
        )
        for key, value in properties.items():
            field_start = component_block.index(f'key: "{key}"')
            field_end = component_block.find("},", field_start)
            field = component_block[field_start:field_end]
            field_type = re.search(r'\btype:\s*"([^"]+)"', field)
            assert field_type is not None
            if field_type.group(1) == "boolean":
                assert type(value) is bool, f"{step['id']}/{key} must be boolean"
            elif field_type.group(1) == "select":
                options = re.search(r'\boptions:\s*\[([^\]]+)\]', field)
                assert options is not None
                assert value in re.findall(r'"([^"]+)"', options.group(1)), (
                    f"{step['id']}/{key} is not a catalog select option"
                )


def test_replay_builds_one_connected_financial_flow():
    raw, _ = load_guide()
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {node["id"]: node for node in architecture["components"]}
    edges = {(edge["source"], edge["target"]): edge for edge in architecture["connections"]}

    assert len(nodes) == 20
    assert len(edges) == 30  # The API has separate initiation and status edges to the ledger.
    assert len(architecture["connections"]) == 31
    assert len(replay["acceptedDecisions"]) == 3
    assert len(replay["appliedStepIds"]) == 54
    assert len(replay["explanationOnlyStepIds"]) == 3
    assert nodes["wire_ledger"]["properties"]["originalComponentId"] == "database"
    assert nodes["wire_domestic"]["properties"]["originalComponentId"] == "payment-service"
    assert nodes["wire_international"]["properties"]["originalComponentId"] == "payment-service"

    for path in (
        ("wire_client", "wire_gateway"),
        ("wire_gateway", "wire_api"),
        ("wire_api", "wire_accounts"),
        ("wire_api", "wire_limits"),
        ("wire_api", "wire_compliance"),
        ("wire_api", "wire_risk"),
        ("wire_api", "wire_ledger"),
        ("wire_ledger", "wire_relay"),
        ("wire_relay", "wire_queue"),
        ("wire_queue", "wire_dispatch"),
        ("wire_dispatch", "wire_domestic"),
        ("wire_dispatch", "wire_international"),
        ("wire_dispatch", "wire_reconcile"),
        ("wire_reconcile", "wire_ledger"),
        ("wire_relay", "wire_archive"),
    ):
        assert path in edges

    neighbors = {node_id: set() for node_id in nodes}
    for edge in architecture["connections"]:
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["wire_client"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == set(nodes)


def test_replayed_properties_preserve_money_movement_and_failure_controls():
    raw, _ = load_guide()
    replay = build_architecture(raw)
    nodes = {node["id"]: node for node in replay["architecture"]["components"]}
    purpose = lambda node_id: nodes[node_id]["properties"]["purpose"].casefold()

    assert "payload hash" in purpose("wire_api")
    assert "unique scoped idempotency key" in purpose("wire_ledger")
    assert "atomic limit/funds reservation" in purpose("wire_ledger")
    assert "transactional outbox" in purpose("wire_ledger")
    assert {"wal", "pitr", "backups", "multiAZ", "auditLog"} <= set(
        nodes["wire_ledger"]["properties"]
    )
    assert "jurisdiction-specific kyc, aml, sanctions" in purpose("wire_compliance")
    assert "blocks the rail" in purpose("wire_risk")
    assert "never blindly resubmit" in purpose("wire_dispatch")
    assert "confirmed settlement" in purpose("wire_domestic")
    assert "confirmed settlement" in purpose("wire_international")
    assert "compensating entries" in purpose("wire_reconcile")
    assert "integrity-checked" in purpose("wire_archive")
    assert "backup and restore verification" in purpose("wire_monitor")
    assert "rotate" in purpose("wire_keys")

    decisions = " ".join(decision["chosen"].casefold() for decision in replay["acceptedDecisions"])
    assert "durable unique idempotency" in decisions
    assert "block rail dispatch" in decisions
    assert "transactional outbox" in decisions

