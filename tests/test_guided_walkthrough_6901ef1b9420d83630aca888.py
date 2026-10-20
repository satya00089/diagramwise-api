"""Frozen-brief, catalog, and replay checks for the burger-distribution draft."""

from collections import deque
from fractions import Fraction
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca888"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

REQUIREMENTS = [
    "Handle millions of concurrent requests",
    "Fair distribution (first-come-first-served)",
    "Prevent duplicate claims",
    "Track inventory in real-time",
    "Generate claim codes/vouchers",
    "Handle when inventory runs out",
    "Prevent bot attacks",
    "User authentication",
]
CONSTRAINTS = [
    "Extreme traffic spike (millions in minutes)",
    "Accurate inventory counting",
    "No overselling",
    "Low latency for claim requests",
    "System should not crash under load",
]
HINTS = [
    "Queue-based request handling",
    "Redis for atomic inventory decrements",
    "Rate limiting per user",
    "CDN for static content",
    "Load balancing and auto-scaling",
]
ANCHORS = {
    *(f"legacy-requirement:{number}" for number in range(1, len(REQUIREMENTS) + 1)),
    *(f"legacy-constraint:{number}" for number in range(1, len(CONSTRAINTS) + 1)),
}


def _anchors(requirements=(), constraints=()):
    return {
        *(f"legacy-requirement:{number}" for number in requirements),
        *(f"legacy-constraint:{number}" for number in constraints),
    }


EXPECTED_STEP_ANCHORS = {
    "burger_01_brief": _anchors(range(1, 9), range(1, 6)),
    "burger_02_average": _anchors((1,), (1,)),
    "burger_03_assumptions": _anchors((1, 3, 5, 8), (1, 4, 5)),
    "burger_04_invariants": _anchors((3, 4, 5, 6), (2, 3)),
    "burger_05_entities": _anchors((2, 3, 4, 5, 8), (2, 3)),
    "burger_06_api": _anchors((3, 5, 6, 8)),
    "burger_07_pending": _anchors((4, 5, 6), (3,)),
    "burger_08_client": _anchors((1, 6, 8)),
    "burger_09_cdn": _anchors((1,), (1,)),
    "burger_10_waf": _anchors((7,), (1, 5)),
    "burger_11_balancer": _anchors((1,), (1, 5)),
    "burger_12_gateway": _anchors((3, 8), (1, 5)),
    "burger_13_auth": _anchors((3, 8)),
    "burger_14_limiter": _anchors((7, 8), (1, 5)),
    "burger_15_api": _anchors((1, 3, 8), (1, 4, 5)),
    "burger_16_redis": _anchors((3, 4), (2, 3)),
    "burger_17_queue": _anchors((1, 2), (1, 5)),
    "burger_18_worker": _anchors((1, 2, 3, 5), (1, 3, 5)),
    "burger_19_ledger": _anchors((3, 4, 5, 6), (2, 3)),
    "burger_20_voucher_events": _anchors((5,), (5,)),
    "burger_21_notifier": _anchors((5,)),
    "burger_22_secrets": _anchors((5,)),
    "burger_23_monitoring": _anchors((1, 4, 6, 7), (1, 2, 4, 5)),
    "burger_24_client_cdn": _anchors((1,), (1,)),
    "burger_25_cdn_waf": _anchors((7,), (1, 5)),
    "burger_26_waf_lb": _anchors((7,), (1, 5)),
    "burger_27_lb_gateway": _anchors((1,), (1, 5)),
    "burger_28_gateway_auth": _anchors((8,), (5,)),
    "burger_29_gateway_limiter": _anchors((7, 8), (1, 5)),
    "burger_30_auth_api": _anchors((3, 8)),
    "burger_31_limiter_api": _anchors((7,), (1, 5)),
    "burger_32_api_redis": _anchors((4,), (2, 3)),
    "burger_33_redis_api": _anchors((4, 6), (2, 3)),
    "burger_34_api_queue": _anchors((1, 2, 3), (1, 5)),
    "burger_35_queue_worker": _anchors((1, 2), (1, 5)),
    "burger_36_worker_ledger": _anchors((3, 4, 5, 6), (2, 3)),
    "burger_37_ledger_worker": _anchors((3, 5), (3, 5)),
    "burger_38_status": _anchors((4, 5, 6, 8)),
    "burger_39_outbox": _anchors((5,), (5,)),
    "burger_40_delivery": _anchors((5,)),
    "burger_41_api_secrets": _anchors((5,)),
    "burger_42_worker_secrets": _anchors((5,), (3,)),
    "burger_43_delivery_secrets": _anchors((5,)),
    "burger_44_api_metrics": _anchors((1, 7), (4, 5)),
    "burger_45_queue_metrics": _anchors((1, 2), (1, 4, 5)),
    "burger_46_ledger_metrics": _anchors((4,), (2, 3)),
    "burger_47_fairness": _anchors((1, 2), (1,)),
    "burger_48_stock_authority": _anchors((3, 4), (2, 3)),
    "burger_49_idempotency": _anchors((3, 5), (2, 3)),
    "burger_50_outage": _anchors((3, 4, 5), (2, 3, 5)),
    "burger_51_sold_out": _anchors((4, 6), (2, 3)),
    "burger_52_abuse_backpressure": _anchors((1, 2, 7, 8), (1, 5)),
    "burger_53_scale": _anchors((1,), (1, 5)),
    "burger_54_latency": _anchors((5,), (4,)),
    "burger_55_tests": _anchors((1, 2, 3, 4, 5, 6), (1, 2, 3, 5)),
    "burger_56_tradeoff": _anchors((1, 2), (1, 4)),
    "burger_57_recap": _anchors(range(1, 9), range(1, 6)),
}
ACTION_TYPES = {"add_component", "add_connection", "decision_point"}
CONNECTION_TYPES = {
    "http",
    "api-call",
    "data-flow",
    "database-connection",
    "event-stream",
    "message-queue",
}


def _load():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    return raw, GuidedWalkthrough.model_validate(raw), problem


def _catalog_entry(catalog: str, component_id: str) -> str:
    match = re.search(
        rf'(?ms)^ {{4}}id: "{re.escape(component_id)}",.*?^ {{2}}\}},?',
        catalog,
    )
    assert match, f"Unknown component catalog ID: {component_id}"
    return match.group(0)


def _reachable(start: str, neighbors: dict[str, set[str]]) -> set[str]:
    reached = set()
    pending = deque([start])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    return reached


def test_schema_phases_and_every_frozen_requirement_anchor_is_actionable():
    raw, guide, problem = _load()

    assert problem["title"] == (
        "Design Backend for an App to Distribute 6 Million Free Burgers in One Hour"
    )
    assert problem["description"] == (
        "Design a system to handle flash distribution of limited items with high concurrency and fairness."
    )
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert problem["hints"] == HINTS
    assert problem["has_guided_walkthrough"] is False
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0-review"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps)
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps

    phase_by_number = {
        number: phase.name
        for phase in guide.phases
        for number in range(phase.stepRange[0], phase.stepRange[1] + 1)
    }
    assert list(phase_by_number) == list(range(1, guide.totalSteps + 1))
    assert all(phase_by_number[step.stepNumber] == step.phase for step in guide.steps)

    all_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert {
        step.id: set(step.requirementIds) for step in guide.steps
    } == EXPECTED_STEP_ANCHORS
    action_anchors = {
        anchor for step in guide.steps
        if step.type in ACTION_TYPES
        for anchor in step.requirementIds
    }
    assert all_anchors == action_anchors == ANCHORS

    request = make_request(problem, raw, build_architecture(raw))
    assert request["problem"]["requirements"].splitlines() == REQUIREMENTS
    assert request["problem"]["constraints"].splitlines() == CONSTRAINTS


def test_campaign_rate_math_and_unspecified_slos_are_explicit():
    raw, _, problem = _load()
    steps = {step["id"]: step for step in raw["steps"]}
    target_burgers = 6_000_000
    campaign_seconds = 60 * 60
    average_burgers_per_second = Fraction(target_burgers, campaign_seconds)
    average_burgers_per_minute = Fraction(target_burgers, 60)

    assert problem["title"].endswith("6 Million Free Burgers in One Hour")
    assert average_burgers_per_second == Fraction(5_000, 3)
    assert average_burgers_per_minute == 100_000

    rate_text = steps["burger_02_average"]["content"]
    assert "6,000,000 burgers / 3,600 seconds" in rate_text
    assert "1,666.67 burgers per second" in rate_text
    assert "100,000 burgers per minute" in rate_text
    assert "one successful voucher redeems exactly one burger" in rate_text
    assert "not a peak-capacity target" in rate_text
    assert "no arrival curve, retry rate, or peak request rate" in rate_text

    assumptions = steps["burger_03_assumptions"]["content"].casefold()
    assert "numeric claim-latency slo" in assumptions
    assert "numeric availability/uptime target" in assumptions
    assert "do not infer any of those from the one-hour average" in assumptions

    prose = json.dumps(raw, ensure_ascii=False).casefold()
    assert not re.search(
        r"\b\d+(?:\.\d+)?\s*%\s*(?:availability|uptime)\b"
        r"|\b(?:availability|uptime)\s+(?:slo|target)\s*"
        r"(?:is|of|=|:)?\s*\d+(?:\.\d+)?\s*%",
        prose,
    )


def test_ordered_actions_replay_to_one_connected_claim_and_recovery_graph():
    raw, guide, _ = _load()
    seen_nodes = {}
    seen_edges = set()
    for step in guide.steps:
        if step.type == "add_component":
            component = step.component.model_dump()
            assert component["nodeId"] not in seen_nodes
            assert set(component["position"]) == {"x", "y"}
            seen_nodes[component["nodeId"]] = component
        elif step.type == "add_connection":
            edge = step.connection
            assert edge.edgeId not in seen_edges
            assert edge.sourceNodeId in seen_nodes
            assert edge.targetNodeId in seen_nodes
            assert edge.connectionType in CONNECTION_TYPES
            assert edge.label and edge.description
            seen_edges.add(edge.edgeId)
        elif step.type == "decision_point":
            assert step.decision is not None
            assert step.decision.chosen and step.decision.chosenReason
            assert len(step.decision.alternatives) >= 2
            assert step.componentUpdate is not None
            assert step.componentUpdate.nodeId in seen_nodes
            assert step.componentUpdate.properties

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {node["id"]: node for node in architecture["components"]}
    edges = architecture["connections"]
    assert len(nodes) >= 15
    assert len(edges) >= 15
    assert len(replay["appliedStepIds"]) + len(replay["explanationOnlyStepIds"]) == guide.totalSteps
    assert replay["acceptedDecisions"]

    neighbors = {node_id: set() for node_id in nodes}
    directed = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
        directed[edge["source"]].add(edge["target"])
    assert _reachable("burger_client", neighbors) == set(nodes)

    def reaches(source: str, target: str) -> bool:
        return target in _reachable(source, directed)

    assert reaches("burger_client", "claim_gateway")
    assert reaches("claim_gateway", "claim_api")
    assert reaches("claim_api", "claim_queue")
    assert reaches("claim_queue", "claim_worker")
    assert reaches("claim_worker", "claim_ledger")
    assert reaches("claim_ledger", "voucher_queue")
    assert reaches("voucher_queue", "voucher_delivery")
    assert all(node["properties"].get("purpose") for node in nodes.values())

    request = make_request(next(row for row in json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
                                if row["id"] == PROBLEM_ID), raw, replay)
    assert request["components"] == architecture["components"]
    assert request["connections"] == architecture["connections"]


def test_all_nodes_and_updates_use_supported_catalog_properties_and_options():
    raw, _, _ = _load()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}

    for step in raw["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            assert component["componentType"] != "custom-component"
            assert component["properties"]["componentName"] == component["label"]
            assert len(component["properties"]["purpose"]) >= 60
            components[component["nodeId"]] = component

    for step in raw["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            component_type = component["componentType"]
            properties = component["properties"]
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            component_type = components[update["nodeId"]]["componentType"]
            properties = update["properties"]
        else:
            continue

        entry = _catalog_entry(catalog, component_type)
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', entry))
        assert set(properties) <= supported, (
            f"{step['id']}: unsupported properties {sorted(set(properties) - supported)}"
        )
        for key, value in properties.items():
            start = entry.index(f'key: "{key}"')
            end = entry.find("},", start)
            field = entry[start:end]
            field_type = re.search(r'\btype:\s*"([^"]+)"', field)
            assert field_type, f"{step['id']}/{key}: catalog property has no type"
            if field_type.group(1) == "boolean":
                assert type(value) is bool
            elif field_type.group(1) == "select":
                options = re.search(r'\boptions:\s*\[([^\]]+)\]', field)
                assert options
                assert value in re.findall(r'"([^"]+)"', options.group(1))

    assert {
        component["componentType"] for component in components.values()
    } >= {
        "web-app", "cdn", "firewall", "loadbalancer", "api-gateway",
        "auth-service", "rate-limiter", "webserver", "cache", "queue",
        "processing-worker", "database", "notification-service",
        "secrets-manager", "monitoring",
    }


def test_domain_guidance_covers_fairness_idempotency_stock_bots_and_recovery():
    raw, _, _ = _load()
    prose = " ".join(
        json.dumps(step, ensure_ascii=False) for step in raw["steps"]
    ).casefold()

    for phrase in (
        "6 million",
        "one hour",
        "first-come-first-served",
        "idempotency",
        "unique",
        "atomic",
        "voucher",
        "sold out",
        "bot",
        "authenticated",
        "queue",
        "redis",
        "database commit",
        "fail closed",
        "reconcile",
        "dead-letter",
        "retry",
        "queue lag",
        "assumption",
    ):
        assert phrase in prose, f"Missing burger-claim design topic: {phrase}"

    # The problem does not define an identity policy or peak arrival rate.
    assert "one successful claim is allowed per authenticated account per campaign" in prose
    assert "not a peak-capacity" in prose
