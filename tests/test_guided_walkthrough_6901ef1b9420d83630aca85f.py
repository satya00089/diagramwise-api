"""Frozen-brief, catalog, and connected replay checks for the rate-limiter draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca85f"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": PROBLEM_ID,
    "title": "Design an API Rate Limiter",
    "description": "Design a rate limiting system to control the number of requests a user can make to an API.",
    "requirements": [
        "Limit requests per user/IP within time window",
        "Support different rate limit tiers",
        "Provide clear error messages when limit exceeded",
        "Track and reset limits per time window",
        "Support distributed rate limiting",
        "Monitor and alert on rate limit breaches",
        "Handle millions of requests per second",
    ],
    "constraints": [
        "Low latency overhead (<10ms)",
        "Accurate counting in distributed system",
        "Handle clock skew across servers",
        "Memory efficient implementation",
        "Support multiple rate limit algorithms",
    ],
    "hints": [
        "Token bucket or leaky bucket algorithm",
        "Redis for distributed counters",
        "Sliding window log or fixed window counter",
        "In-memory cache for performance",
        "Rate limit headers in API responses",
    ],
}
STEP_TYPES = {"explanation", "add_component", "add_connection", "decision_point", "scale_trigger"}
CONNECTION_TYPES = {"http", "api-call", "database-connection", "message-queue", "data-flow"}
ACTION_TYPES = {"add_component", "add_connection", "decision_point", "scale_trigger"}
EXPECTED_COMPONENTS = {
    "web-app",
    "loadbalancer",
    "api-gateway",
    "cache",
    "database",
    "backend-server",
    "queue",
    "analytics",
    "monitoring",
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


def test_schema_order_and_exact_frozen_brief_anchor_coverage():
    problem = frozen_problem()
    raw, guide = load_guide()

    assert {field: problem[field] for field in FROZEN_BRIEF} == FROZEN_BRIEF
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 23
    assert set(raw) == {"problem_id", "version", "requirementRevision", "totalSteps", "phases", "steps"}
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES and step.content.strip() for step in guide.steps)

    expected_anchors = {
        *(f"legacy-requirement:{index}" for index in range(1, len(FROZEN_BRIEF["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(FROZEN_BRIEF["constraints"]) + 1)),
    }
    actual_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert actual_anchors == expected_anchors

    replay = build_architecture(raw)
    applied_step_ids = set(replay["appliedStepIds"])
    for anchor in expected_anchors:
        assert any(
            anchor in step.requirementIds
            and step.type in ACTION_TYPES
            and step.id in applied_step_ids
            for step in guide.steps
        ), f"{anchor} is not tied to an applied component, connection, or explicit decision action"

    request = make_request(problem, raw, replay)
    assert request["problem"]["id"] == FROZEN_BRIEF["id"]
    assert request["problem"]["title"] == FROZEN_BRIEF["title"]
    assert request["problem"]["description"] == FROZEN_BRIEF["description"]
    assert request["problem"]["requirements"].splitlines() == FROZEN_BRIEF["requirements"]
    assert request["problem"]["constraints"].splitlines() == FROZEN_BRIEF["constraints"]


def test_phases_and_ordered_unique_actions_replay_as_one_connected_graph():
    raw, guide = load_guide()
    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    node_ids = set()
    edge_ids = set()
    saw_connection = False
    for step in guide.steps:
        if step.type == "add_component":
            assert not saw_connection, "All replayed component additions must precede connection actions"
            assert step.component is not None
            assert step.component.nodeId not in node_ids
            assert step.component.position.keys() >= {"x", "y"}
            node_ids.add(step.component.nodeId)
        elif step.type == "add_connection":
            saw_connection = True
            assert step.connection is not None
            assert step.connection.edgeId not in edge_ids
            assert step.connection.connectionType in CONNECTION_TYPES
            assert {step.connection.sourceNodeId, step.connection.targetNodeId} <= node_ids
            edge_ids.add(step.connection.edgeId)
        elif step.type == "decision_point":
            assert step.decision is not None and step.decision.alternatives
        elif step.type == "scale_trigger":
            assert step.scaleTrigger is not None
        if step.componentUpdate is not None:
            assert step.componentUpdate.nodeId in node_ids
            assert step.componentUpdate.properties

    assert len(node_ids) == 9
    assert len(edge_ids) == 9

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    replayed_nodes = {node["id"] for node in architecture["components"]}
    neighbors = {node_id: set() for node_id in replayed_nodes}
    for edge in architecture["connections"]:
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["rl_client"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == replayed_nodes

    expected_applied = {
        step.id
        for step in guide.steps
        if step.type in {"add_component", "add_connection"}
        or (step.type == "decision_point" and step.componentUpdate is not None)
    }
    assert set(replay["appliedStepIds"]) == expected_applied
    assert len(replay["appliedStepIds"]) + len(replay["explanationOnlyStepIds"]) == guide.totalSteps


def test_existing_catalog_ids_and_supported_properties():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step.get("component")
    }
    assert {component["componentType"] for component in additions.values()} == EXPECTED_COMPONENTS

    for step in raw["steps"]:
        component = step.get("component")
        if component:
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
        assert_catalog_properties(catalog, component_type, properties, step["id"])


def test_replay_preserves_rate_limiter_specific_signals_and_tradeoffs():
    raw, guide = load_guide()
    replay = build_architecture(raw)
    nodes = {node["id"]: node for node in replay["architecture"]["components"]}
    purposes = " ".join(node["properties"].get("purpose", "") for node in nodes.values()).casefold()
    prose = " ".join(
        [step.content for step in guide.steps]
        + [node["properties"].get("purpose", "") for node in nodes.values()]
        + [
            text
            for step in guide.steps
            if step.decision
            for text in (
                step.decision.question,
                step.decision.chosen,
                step.decision.chosenReason,
                *(f"{alternative.option} {alternative.tradeoff}" for alternative in step.decision.alternatives),
            )
        ]
        + [
            text
            for step in guide.steps
            if step.scaleTrigger
            for text in (
                step.scaleTrigger.metric,
                step.scaleTrigger.action,
                step.scaleTrigger.impact,
            )
        ]
    ).casefold()

    gateway = nodes["rl_gateway"]["properties"]
    assert gateway["authentication"] == "JWT"
    assert gateway["rateLimiting"] is True and gateway["throttling"] is True
    assert nodes["rl_counters"]["properties"]["engine"] == "redis"
    assert "user or ip" in purposes
    assert "tier" in purposes and "versioned" in purposes
    assert "atomic" in purposes and "authoritative" in purposes

    for signal in (
        "token bucket",
        "leaky bucket",
        "sliding window log",
        "sliding window counter",
        "fixed window counter",
        "clock skew",
        "clock drift",
        "bounded in-memory",
        "millions of requests per second",
        "<10ms",
        "http 429",
        "ratelimit-limit",
        "ratelimit-remaining",
        "ratelimit-reset",
        "retry-after",
        "fail-open versus fail-closed",
        "hot subject",
    ):
        assert signal in prose, f"Missing rate-limiter design signal: {signal}"

    # The only explicit latency quantity in the prose is the brief's own constraint.
    quantities = re.findall(
        r"\b\d+(?:\.\d+)?\s*(?:ms|milliseconds?|seconds?|minutes?|hours?|days?|rps|qps)\b",
        prose,
    )
    assert {quantity.replace(" ", "").casefold() for quantity in quantities} <= {"10ms"}


def test_requirement_anchors_match_the_action_that_satisfies_them():
    _, guide = load_guide()
    steps = {step.id: step for step in guide.steps}

    # The gateway's admitted-request edge is not the user-facing limit error;
    # that contract belongs on the explicit rejection-response step.
    assert "legacy-requirement:3" not in steps["rl_15"].requirementIds
    assert "legacy-requirement:3" in steps["rl_16"].requirementIds

    # Clock-skew handling is explicit in the timing/failure decision, not in
    # the generic atomic-counter action by itself.
    assert "legacy-constraint:3" not in steps["rl_05"].requirementIds
    assert "legacy-constraint:3" not in steps["rl_13"].requirementIds
    assert "legacy-constraint:3" in steps["rl_22"].requirementIds

    # Throughput and latency claims must be grounded in the scale action, and
    # policy refresh must stay off the synchronous per-request database path.
    assert "legacy-requirement:7" in steps["rl_23"].requirementIds
    assert "legacy-constraint:1" in steps["rl_23"].requirementIds
    policy_path = " ".join(
        [steps["rl_14"].content]
        + [
            steps["rl_14"].connection.description,
            steps["rl_14"].connection.label,
        ]
    ).casefold()
    assert "local bounded" in policy_path
    assert "not synchronously" in policy_path
