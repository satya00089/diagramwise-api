"""Frozen-brief, catalog, replay, and payment-safety checks for the review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca86d"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": PROBLEM_ID,
    "title": "Design a Credit Card Processing System",
    "description": "Design a secure payment processing system for credit card transactions with fraud detection.",
    "requirements": [
        "Process credit card transactions",
        "Tokenization for card security",
        "Fraud detection and prevention",
        "3D Secure authentication",
        "Handle chargebacks and disputes",
        "Support multiple payment networks",
        "PCI DSS compliance",
        "Handle millions of transactions per day",
        "Real-time authorization",
    ],
    "constraints": [
        "ACID guarantees for transactions",
        "Low latency for payment authorization",
        "High security and encryption",
        "Regulatory compliance",
        "Zero tolerance for data loss",
    ],
    "hints": [
        "Tokenization for PCI compliance",
        "Machine learning for fraud detection",
        "State machine for transaction lifecycle",
        "Idempotency for duplicate requests",
        "Audit logs for compliance",
    ],
}
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


def test_exact_frozen_brief_matches_repository_snapshot():
    problem = frozen_problem()
    assert {key: problem[key] for key in FROZEN_BRIEF} == FROZEN_BRIEF
    assert problem["has_guided_walkthrough"] is False

    raw, guide = load_guide()
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert raw["totalSteps"] == len(raw["steps"]) == 69
    request = make_request(problem, raw, build_architecture(raw))
    assert request["problem"]["requirements"].splitlines() == FROZEN_BRIEF["requirements"]
    assert request["problem"]["constraints"].splitlines() == FROZEN_BRIEF["constraints"]


def test_phases_ordered_actions_and_accurate_anchors():
    raw, guide = load_guide()
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES and step.content.strip() for step in guide.steps)

    expected_anchors = {
        *(f"legacy-requirement:{index}" for index in range(1, len(FROZEN_BRIEF["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(FROZEN_BRIEF["constraints"]) + 1)),
    }
    actual_anchors = {anchor for step in raw["steps"] for anchor in step["requirementIds"]}
    assert actual_anchors == expected_anchors
    for step in raw["steps"]:
        assert step["requirementIds"]
        assert set(step["requirementIds"]) <= expected_anchors

    actionable = [
        step for step in raw["steps"]
        if step["type"] in {"add_component", "add_connection", "decision_point"}
    ]
    for anchor in expected_anchors:
        assert any(anchor in step["requirementIds"] for step in actionable), (
            f"{anchor} is only described, not connected to a design action or decision"
        )

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    nodes = set()
    edge_ids = set()
    for step in raw["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            assert component["nodeId"] not in nodes
            assert set(component["position"]) >= {"x", "y"}
            nodes.add(component["nodeId"])
        elif step["type"] == "add_connection":
            connection = step["connection"]
            assert connection["edgeId"] not in edge_ids
            assert connection["connectionType"] in CONNECTION_TYPES
            assert {connection["sourceNodeId"], connection["targetNodeId"]} <= nodes
            edge_ids.add(connection["edgeId"])
        elif step["type"] == "decision_point":
            assert step.get("decision", {}).get("alternatives")
            update = step.get("componentUpdate")
            assert update and update["nodeId"] in nodes and update["properties"]
        elif step["type"] == "scale_trigger":
            assert step.get("scaleTrigger")
        if step.get("componentUpdate"):
            assert step["componentUpdate"]["nodeId"] in nodes


def test_existing_catalog_ids_and_supported_properties():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"] if step.get("component")
    }
    assert additions
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
        assert match is not None, f"{step['id']}: unknown frontend catalog ID {component_type}"
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
            if field_type.group(1) in {"text", "textarea"}:
                assert isinstance(value, str)
            elif field_type.group(1) == "boolean":
                assert type(value) is bool
            elif field_type.group(1) == "number":
                assert type(value) in {int, float}
            elif field_type.group(1) == "select":
                options = re.search(r'\boptions:\s*\[([^\]]+)\]', field)
                assert options is not None
                assert value in re.findall(r'"([^"]+)"', options.group(1))


def test_replay_builds_one_connected_payment_graph():
    raw, _ = load_guide()
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {node["id"]: node for node in architecture["components"]}
    edges = architecture["connections"]
    assert len(nodes) == 18
    assert len(edges) == 42
    assert len(replay["acceptedDecisions"]) == 5
    assert replay["explanationOnlyStepIds"]
    assert nodes["cc_tokenizer"]["properties"]["originalComponentId"] == "payment-service"
    assert nodes["cc_ledger"]["properties"]["originalComponentId"] == "database"

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["type"] in CONNECTION_TYPES
        assert edge["source"] in nodes and edge["target"] in nodes
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["cc_client"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == set(nodes)


def test_payment_guidance_covers_safety_and_marks_unknowns():
    raw, _ = load_guide()
    authored_text = json.dumps(raw, ensure_ascii=False).casefold()

    for signal in (
        "facts from the frozen brief", "review assumptions", "tokenization", "opaque",
        "pan", "cvv", "never retained", "idempotency", "payload hash", "state machine",
        "acid", "local transaction", "append-only", "balanced ledger", "fraud",
        "3-d secure", "chargeback", "dispute", "at-least-once", "outbox",
        "unknown/pending", "never blindly retry", "reconcil", "settlement",
        "data loss", "authorization slo", "millions of transactions per day",
        "pci dss", "does not establish pci dss compliance", "retention",
    ):
        assert signal in authored_text, f"missing payment safety guidance: {signal}"

    assert "machine learning" in authored_text or "model" in authored_text
    assert "audit" in authored_text
    assert "not stated by the brief" in authored_text
    assert not re.search(r"\bp\d{2}\s*(?:<|below|under)\s*\d", authored_text)
    assert not re.search(r"\b(?:under|below|within|less than)\s+\d+(?:\.\d+)?\s*(?:ms|milliseconds|s|seconds)\b", authored_text)


def test_payment_operation_semantics_and_claim_boundaries_are_explicit():
    raw, _ = load_guide()
    steps = {step["id"]: step for step in raw["steps"]}
    lifecycle = steps["cc_37_state_machine"]["content"].casefold()
    idempotency = steps["cc_15_idempotency"]["content"].casefold()
    uncertain = steps["cc_49_retry_unknown"]["content"].casefold()
    authored_text = json.dumps(raw, ensure_ascii=False).casefold()

    for distinction in (
        "3-d secure authenticates the cardholder",
        "issuer authorization approves or declines",
        "does not capture funds",
        "capture is a later, separately identified command",
        "void or reversal releases an uncaptured authorization",
        "refund is a separate credit against a confirmed captured amount",
        "must not exceed the captured amount",
        "capture is still distinct from later settlement",
    ):
        assert distinction in lifecycle, f"missing lifecycle distinction: {distinction}"

    for rule in (
        "scope each money-moving command's stable idempotency identity",
        "merchant, payment intent, and operation kind",
        "canonical payload hash",
        "a new key alone does not authorize another capture",
    ):
        assert rule in idempotency, f"missing idempotency rule: {rule}"
    assert all(operation in uncertain for operation in ("authorization", "capture", "void", "refund"))
    assert "original provider idempotency identity" in uncertain

    assert "cvv is never retained" in authored_text
    assert "does not establish pci dss compliance" in authored_text
    assert "not a compliance attestation" in authored_text
    assert not re.search(r"\bpci[ -]?dss\s+(?:certified|certification achieved|compliant)\b", authored_text)
    assert not re.search(r"\b\d+(?:\.\d+)?\s*%\s*(?:availability|uptime)\b", authored_text)
    assert not re.search(r"\b\d[\d,]*(?:\.\d+)?\s*(?:ms|milliseconds)\b", authored_text)
    assert not re.search(r"\b\d[\d,]*(?:\.\d+)?\s*(?:transactions?|requests?)\s*(?:/|per)\s*(?:second|minute|hour|day)\b", authored_text)


def test_payment_critical_action_anchors_are_exact():
    raw, _ = load_guide()
    steps = {step["id"]: set(step["requirementIds"]) for step in raw["steps"]}
    expected = {
        "cc_04_client_gateway": {"legacy-requirement:1", "legacy-requirement:2", "legacy-requirement:9", "legacy-constraint:3"},
        "cc_05_tokenizer": {"legacy-requirement:2", "legacy-requirement:7", "legacy-constraint:3", "legacy-constraint:4"},
        "cc_06_client_tokenizer": {"legacy-requirement:2", "legacy-requirement:7", "legacy-constraint:3", "legacy-constraint:4"},
        "cc_07_token_gateway": {"legacy-requirement:1", "legacy-requirement:2", "legacy-requirement:7", "legacy-constraint:3", "legacy-constraint:4"},
        "cc_09_token_keys": {"legacy-requirement:2", "legacy-requirement:7", "legacy-constraint:3"},
        "cc_15_idempotency": {"legacy-requirement:1", "legacy-requirement:9", "legacy-constraint:1", "legacy-constraint:5"},
        "cc_16_token_boundary": {"legacy-requirement:2", "legacy-requirement:7", "legacy-constraint:3", "legacy-constraint:4"},
        "cc_33_networks_breaker": {"legacy-requirement:1", "legacy-requirement:6", "legacy-requirement:9", "legacy-constraint:5"},
        "cc_34_breaker_orchestrator": {"legacy-requirement:1", "legacy-requirement:9", "legacy-constraint:1", "legacy-constraint:5"},
        "cc_37_state_machine": {"legacy-requirement:1", "legacy-requirement:4", "legacy-requirement:5", "legacy-requirement:9", "legacy-constraint:1", "legacy-constraint:5"},
        "cc_38_ledger": {"legacy-requirement:1", "legacy-requirement:5", "legacy-requirement:7", "legacy-requirement:8", "legacy-constraint:1", "legacy-constraint:3", "legacy-constraint:5"},
        "cc_39_orchestrator_ledger": {"legacy-requirement:1", "legacy-requirement:9", "legacy-constraint:1", "legacy-constraint:5"},
        "cc_41_acid_boundary": {"legacy-requirement:1", "legacy-requirement:9", "legacy-constraint:1", "legacy-constraint:5"},
        "cc_48_worker_orchestrator": {"legacy-requirement:1", "legacy-requirement:5", "legacy-requirement:9", "legacy-constraint:1", "legacy-constraint:5"},
        "cc_49_retry_unknown": {"legacy-requirement:1", "legacy-requirement:6", "legacy-requirement:9", "legacy-constraint:1", "legacy-constraint:5"},
        "cc_50_disputes": {"legacy-requirement:5", "legacy-requirement:7", "legacy-constraint:3", "legacy-constraint:4", "legacy-constraint:5"},
        "cc_51_worker_disputes": {"legacy-requirement:1", "legacy-requirement:5", "legacy-constraint:5"},
        "cc_55_reconciliation": {"legacy-requirement:1", "legacy-requirement:5", "legacy-requirement:6", "legacy-requirement:8", "legacy-constraint:1", "legacy-constraint:5"},
        "cc_56_networks_recon": {"legacy-requirement:6", "legacy-requirement:8", "legacy-constraint:4", "legacy-constraint:5"},
        "cc_57_ledger_recon": {"legacy-requirement:1", "legacy-requirement:5", "legacy-constraint:1", "legacy-constraint:5"},
        "cc_58_recon_orchestrator": {"legacy-requirement:1", "legacy-requirement:5", "legacy-requirement:9", "legacy-constraint:1", "legacy-constraint:5"},
        "cc_63_network_monitor": {"legacy-requirement:6", "legacy-requirement:8", "legacy-requirement:9", "legacy-constraint:2", "legacy-constraint:5"},
        "cc_64_ledger_monitor": {"legacy-requirement:1", "legacy-requirement:5", "legacy-requirement:8", "legacy-constraint:1", "legacy-constraint:3", "legacy-constraint:5"},
        "cc_67_recon_monitor": {"legacy-requirement:6", "legacy-requirement:8", "legacy-constraint:1", "legacy-constraint:5"},
        "cc_68_scale": {"legacy-requirement:1", "legacy-requirement:6", "legacy-requirement:8", "legacy-requirement:9", "legacy-constraint:1", "legacy-constraint:2", "legacy-constraint:5"},
    }
    assert {step_id: steps[step_id] for step_id in expected} == expected
