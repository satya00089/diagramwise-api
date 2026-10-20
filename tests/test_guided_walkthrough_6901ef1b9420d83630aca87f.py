"""Frozen-brief, catalog, connected replay, and policy checks for the ads draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca87f"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": PROBLEM_ID,
    "title": "Develop an Ads Management and Display System for a Social Feed",
    "description": "Design an advertising platform for targeting, serving, and billing ads in social media feeds.",
    "category": "Advertising",
    "requirements": [
        "Create and manage ad campaigns",
        "Target ads by demographics and interests",
        "Serve ads in user feeds",
        "Track impressions and clicks",
        "Billing and budget management",
        "A/B testing for ad creatives",
        "Fraud detection and prevention",
        "Handle billions of ad impressions per day",
        "Real-time bidding support",
    ],
    "constraints": [
        "Low latency for ad serving (<100ms)",
        "Fair ad distribution",
        "Accurate tracking and attribution",
        "Privacy compliance (GDPR, CCPA)",
        "Prevent click fraud",
    ],
    "hints": [
        "Ad ranking and auction algorithms",
        "User profiling for targeting",
        "Real-time bidding infrastructure",
        "Impression/click tracking pipeline",
        "Machine learning for optimization",
    ],
}
ANCHORS = {
    *(f"legacy-requirement:{index}" for index in range(1, 10)),
    *(f"legacy-constraint:{index}" for index in range(1, 6)),
}
ACTION_TYPES = {"add_component", "add_connection"}
STEP_TYPES = ACTION_TYPES | {"decision_point", "scale_trigger", "explanation"}
CONNECTION_TYPES = {
    "https",
    "api-call",
    "database-connection",
    "message-queue",
    "data-flow",
}
EXPECTED_PHASES = [
    ("Define the campaign contract and policy inputs", 1, 13),
    ("Gate candidates and decide inside the latency budget", 14, 30),
    ("Deliver, verify events, and reconcile spend", 31, 58),
]


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


def assert_supported_catalog_properties(
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


def reachable(start: str, neighbors: dict[str, set[str]]) -> set[str]:
    reached = set()
    pending = deque([start])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    return reached


def test_exact_frozen_brief_and_review_draft_schema():
    raw, guide, problem = load_guide()

    assert {key: problem[key] for key in FROZEN_BRIEF} == FROZEN_BRIEF
    assert problem["has_guided_walkthrough"] is False
    assert set(raw) == {
        "problem_id", "version", "requirementRevision", "totalSteps", "phases", "steps"
    }
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 58
    assert all(step.type in STEP_TYPES and step.title.strip() and step.content.strip() for step in guide.steps)


def test_ordered_phases_and_every_requirement_constraint_is_actionable():
    raw, guide, _ = load_guide()

    assert [(phase.name, *phase.stepRange) for phase in guide.phases] == EXPECTED_PHASES
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps

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
        assert len(anchors) == len(step.requirementIds), f"{step.id}: repeated anchor"
        assert anchors <= ANCHORS, f"{step.id}: unknown anchors {sorted(anchors - ANCHORS)}"
        all_anchors.update(anchors)
        if step.type in ACTION_TYPES:
            action_anchors.update(anchors)
    assert all_anchors == ANCHORS
    assert action_anchors == ANCHORS


def test_catalog_supported_actions_replay_as_one_connected_graph():
    raw, guide, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}
    edge_ids = set()
    edge_pairs = set()
    action_ids = []

    for step in guide.steps:
        if step.type == "add_component":
            component = step.component
            assert component is not None
            assert component.nodeId not in components
            assert set(component.position) == {"x", "y"}
            assert component.properties["componentName"] == component.label
            assert len(component.properties["purpose"]) >= 60
            assert component.highlightReason
            assert component.componentType != "custom-component"
            assert_supported_catalog_properties(
                catalog, component.componentType, component.properties, step.id
            )
            components[component.nodeId] = component
            action_ids.append(step.id)
        elif step.type == "add_connection":
            connection = step.connection
            assert connection is not None
            assert connection.edgeId not in edge_ids
            assert connection.sourceNodeId in components
            assert connection.targetNodeId in components
            assert connection.connectionType in CONNECTION_TYPES
            assert connection.label and connection.description
            edge_ids.add(connection.edgeId)
            edge_pairs.add((connection.sourceNodeId, connection.targetNodeId))
            action_ids.append(step.id)
        elif step.type == "decision_point":
            assert step.decision is not None
            assert step.decision.question and step.decision.chosen
            assert step.decision.chosenReason
            assert len(step.decision.alternatives) >= 2
        elif step.type == "scale_trigger":
            assert step.scaleTrigger is not None
            assert step.scaleTrigger.metric and step.scaleTrigger.action and step.scaleTrigger.impact

    assert len(components) == 21
    assert len(edge_ids) == 27

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    edges = architecture["connections"]
    assert len(nodes) == 21
    assert len(edges) == 27
    assert replay["appliedStepIds"] == action_ids
    assert replay["acceptedDecisions"] == []

    neighbors = {node_id: set() for node_id in nodes}
    replay_pairs = set()
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
        replay_pairs.add((edge["source"], edge["target"]))
    assert reachable("ads_feed_client", neighbors) == set(nodes)
    assert {
        ("ads_feed_service", "ads_gateway"),
        ("ads_gateway", "ads_decision_service"),
        ("ads_decision_service", "ads_privacy_policy"),
        ("ads_decision_service", "ads_pacing_frequency"),
        ("ads_decision_service", "ads_bid_exchange"),
        ("ads_event_ingest", "ads_event_broker"),
        ("ads_event_broker", "ads_fraud_processor"),
        ("ads_fraud_processor", "ads_billing_ledger"),
        ("ads_billing_reconciler", "ads_billing_ledger"),
    } <= replay_pairs


def test_ads_walkthrough_covers_latency_privacy_pacing_experiments_and_finance():
    raw, _, _ = load_guide()
    authored = json.dumps(raw, ensure_ascii=False).casefold()

    for phrase in (
        *[value.casefold() for value in FROZEN_BRIEF["requirements"]],
        *[value.casefold() for value in FROZEN_BRIEF["constraints"]],
        "hints are prompts, not additional requirements",
        "under 100 ms",
        "30ms",
        "no-fill",
        "campaign pacing",
        "frequency cap",
        "atomic budget reservations",
        "fairness metric",
        "gdpr",
        "ccpa",
        "opt-out",
        "data deletion",
        "sensitive categories",
        "contextual-only",
        "session-level",
        "a/b",
        "variant",
        "click fraud",
        "at-least-once",
        "idempotent",
        "immutable",
        "reconcile",
        "cpm",
        "cpc",
        "11.6k per second",
        "peak-to-average ratio",
    ):
        assert phrase in authored, f"Missing ads design signal: {phrase}"
