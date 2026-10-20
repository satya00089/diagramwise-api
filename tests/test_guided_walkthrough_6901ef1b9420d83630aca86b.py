"""Frozen-brief, catalog, decision, and replay checks for the A/B testing draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca86b"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

# This projection is the supplied strongly-read brief. Snapshot metadata such as
# category, tags, and timestamps is deliberately outside the frozen design brief.
FROZEN_BRIEF = {
    "id": "6901ef1b9420d83630aca86b",
    "title": "Design an A/B Testing System",
    "description": (
        "Design a platform to run experiments and A/B tests to compare different versions of features."
    ),
    "requirements": [
        "Create and manage experiments",
        "Randomly assign users to variants",
        "Track experiment metrics and events",
        "Statistical analysis of results",
        "Support multiple concurrent experiments",
        "Segment users for targeting",
        "Handle billions of events",
        "Real-time experiment monitoring",
    ],
    "constraints": [
        "Consistent variant assignment per user",
        "Minimize experiment bias",
        "Handle high traffic volume",
        "Statistical significance calculation",
        "Support gradual rollouts",
    ],
    "hints": [
        "Deterministic hash function for assignment",
        "Feature flag system integration",
        "Data pipeline for metrics collection",
        "Statistical testing frameworks",
        "Cache user assignments",
    ],
}
STEP_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "decision_point",
    "scale_trigger",
}
ACTION_TYPES = {"add_component", "add_connection"}
CONNECTION_TYPES = {
    "http",
    "api-call",
    "database-connection",
    "message-queue",
    "data-flow",
}
EXPECTED_PHASES = [
    ("Frame the experiment contract", 1, 4),
    ("Create experiments and connect gradual rollout", 5, 13),
    ("Assign eligible users consistently", 14, 27),
    ("Collect events and build analysis data", 28, 41),
    ("Monitor results and review validity", 42, 51),
]


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    return raw, GuidedWalkthrough.model_validate(raw), problem


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'^\s*id:\s*"{re.escape(component_type)}"', catalog, re.MULTILINE)
    assert match is not None, f"{step_id}: unknown catalog component {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), f"{step_id}: incomplete component catalog entry"
    return catalog[match.start() : block_end]


def assert_supported_properties(catalog: str, component: dict, step_id: str) -> None:
    block = catalog_block(catalog, component["componentType"], step_id)
    fields = {}
    for match in re.finditer(r'\{\s*key:\s*"([^"]+)"', block):
        end = block.find("},", match.start())
        assert end > match.start(), f"{step_id}: incomplete property {match.group(1)}"
        field = block[match.start() : end]
        field_type = re.search(r'\btype:\s*"([^"]+)"', field)
        assert field_type is not None, f"{step_id}: {match.group(1)} has no catalog type"
        fields[match.group(1)] = (field_type.group(1), field)

    properties = component["properties"]
    assert set(properties) <= set(fields), (
        f"{step_id}: unsupported {component['componentType']} properties "
        f"{sorted(set(properties) - set(fields))}"
    )
    for key, value in properties.items():
        kind, field = fields[key]
        if kind in {"text", "textarea"}:
            assert isinstance(value, str), f"{step_id}/{key} must be text"
        elif kind == "boolean":
            assert type(value) is bool, f"{step_id}/{key} must be boolean"
        elif kind == "number":
            assert type(value) in {int, float}, f"{step_id}/{key} must be numeric"
        elif kind == "select":
            options = re.search(r'\boptions:\s*\[([^\]]*)\]', field, re.DOTALL)
            assert options is not None, f"{step_id}/{key}: catalog options are missing"
            allowed = set(re.findall(r'"([^"]+)"', options.group(1)))
            assert value in allowed, f"{step_id}/{key}: unsupported option {value!r}"


def test_exact_frozen_brief_schema_and_phase_ranges():
    raw, guide, problem = load_guide()

    assert {key: problem[key] for key in FROZEN_BRIEF} == FROZEN_BRIEF
    assert problem["has_guided_walkthrough"] is False
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert set(raw) == {"problem_id", "version", "totalSteps", "phases", "steps", "requirementRevision"}
    assert guide.totalSteps == len(guide.steps) == 51
    assert raw["totalSteps"] == len(raw["steps"])
    assert [(phase.name, *phase.stepRange) for phase in guide.phases] == EXPECTED_PHASES
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES for step in guide.steps)
    assert all(step.title.strip() and step.content.strip() for step in guide.steps)

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end <= guide.totalSteps
        assert all(step.phase == phase.name for step in guide.steps[start - 1 : end])
        next_step = end + 1
    assert next_step == guide.totalSteps + 1


def test_every_requirement_and_constraint_anchor_is_on_a_design_action():
    _, guide, _ = load_guide()
    expected = {
        *(f"legacy-requirement:{index}" for index in range(1, 9)),
        *(f"legacy-constraint:{index}" for index in range(1, 6)),
    }
    all_anchors = set()
    action_anchors = set()

    for step in guide.steps:
        anchors = set(step.requirementIds)
        assert len(anchors) == len(step.requirementIds), f"{step.id}: repeated anchor"
        assert anchors <= expected, f"{step.id}: unknown anchors {sorted(anchors - expected)}"
        all_anchors.update(anchors)
        if step.type in ACTION_TYPES:
            action_anchors.update(anchors)

    assert all_anchors == expected
    assert action_anchors == expected


def test_actions_are_unique_ordered_and_use_supported_connection_types():
    _, guide, _ = load_guide()
    node_ids = set()
    edge_ids = set()
    action_ids = []
    edge_pairs = []

    for step in guide.steps:
        if step.type == "add_component":
            component = step.component
            assert component is not None
            assert component.nodeId not in node_ids
            assert set(component.position) == {"x", "y"}
            assert all(type(value) in {int, float} for value in component.position.values())
            node_ids.add(component.nodeId)
            action_ids.append(step.id)
        elif step.type == "add_connection":
            connection = step.connection
            assert connection is not None
            assert connection.edgeId not in edge_ids
            assert connection.sourceNodeId in node_ids, f"{step.id}: source added after edge"
            assert connection.targetNodeId in node_ids, f"{step.id}: target added after edge"
            assert connection.connectionType in CONNECTION_TYPES
            assert connection.label.strip() and connection.description.strip()
            edge_ids.add(connection.edgeId)
            edge_pairs.append((connection.sourceNodeId, connection.targetNodeId))
            action_ids.append(step.id)

    assert len(action_ids) == len(set(action_ids))
    assert len(node_ids) == 14
    assert len(edge_ids) == 19


def test_replay_applies_every_action_and_builds_one_connected_graph():
    raw, guide, _ = load_guide()
    action_ids = [step.id for step in guide.steps if step.type in ACTION_TYPES]
    expected_nodes = {
        step.component.nodeId
        for step in guide.steps
        if step.type == "add_component" and step.component is not None
    }
    expected_edges = {
        step.connection.edgeId
        for step in guide.steps
        if step.type == "add_connection" and step.connection is not None
    }

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    components = architecture["components"]
    connections = architecture["connections"]
    replay_nodes = {component["id"] for component in components}

    assert replay["appliedStepIds"] == action_ids
    assert replay["explanationOnlyStepIds"] == [
        step.id for step in guide.steps if step.type not in ACTION_TYPES
    ]
    assert replay["provenance"]["problemId"] == PROBLEM_ID
    assert replay["provenance"]["walkthroughVersion"] == guide.version
    assert replay_nodes == expected_nodes
    assert {connection["id"] for connection in connections} == expected_edges

    neighbors = {node_id: set() for node_id in replay_nodes}
    for connection in connections:
        assert connection["source"] in replay_nodes
        assert connection["target"] in replay_nodes
        assert connection["type"] in CONNECTION_TYPES
        neighbors[connection["source"]].add(connection["target"])
        neighbors[connection["target"]].add(connection["source"])

    reached = set()
    pending = deque(["ab_admin"])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    assert reached == replay_nodes


def test_components_use_current_catalog_ids_and_supported_properties():
    raw, _, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = [
        (step["id"], step["component"])
        for step in raw["steps"]
        if step.get("type") == "add_component"
    ]

    # Existing catalog concepts cover each role in this graph; no custom node is needed.
    assert len(components) == 14
    assert all(component["componentType"] != "custom-component" for _, component in components)
    by_type = {component["componentType"] for _, component in components}
    assert {
        "admin-console",
        "api-gateway",
        "experiment-tracking",
        "deployment-pipeline",
        "web-app",
        "backend-server",
        "cache",
        "database",
        "message-broker",
        "stream-processor",
        "data-warehouse",
        "analytics",
        "monitoring",
    } <= by_type

    for step_id, component in components:
        assert component["properties"]["componentName"] == component["label"]
        assert len(component["properties"]["purpose"]) >= 70
        assert component["highlightReason"].strip()
        assert_supported_properties(catalog, component, step_id)

    rollout = next(component for _, component in components if component["componentType"] == "deployment-pipeline")
    assert rollout["properties"]["strategy"] == "Feature Flag"


def test_assignment_decisions_preserve_stickiness_and_reduce_bias():
    raw, _, _ = load_guide()
    text = json.dumps(raw, ensure_ascii=True).casefold()

    for phrase in (
        "deterministic pseudorandom bucket",
        "experiment identifier",
        "stable user identifier",
        "persist the result",
        "cache miss",
        "durable assignment",
        "versioned segment predicate",
        "sample-ratio mismatch",
        "pre-register",
        "confirmed exposure",
        "overlapping targeting",
    ):
        assert phrase in text, f"missing A/B assignment or validity decision: {phrase}"

    assert "do not prove that every experiment is unbiased" in text
    assert "no numerical targets are inferred" in text


def test_assignment_exposure_and_outcomes_keep_the_analysis_population_explicit():
    raw, _, _ = load_guide()
    by_id = {step["id"]: step for step in raw["steps"]}
    exposure = by_id["ab_03_exposure_boundary"]
    event_contract = by_id["ab_28_event_contract"]
    client_events = by_id["ab_34_client_event_request"]
    validity = by_id["ab_46_validity_review"]
    text = json.dumps(
        [exposure, event_contract, client_events, validity], ensure_ascii=True
    ).casefold()

    assert "intention-to-treat" in text
    assert "not an automatic analysis denominator" in exposure["content"].casefold()
    assert "conditioning on post-assignment exposure can introduce selection bias" in text
    assert "do not require a render-confirmation event" in event_contract["content"].casefold()
    assert "including when a separate render confirmation is missing" in client_events["content"].casefold()
    assert "silently excluding randomized users" in validity["content"].casefold()


def test_metrics_and_statistical_decisions_require_predeclared_policy_not_invented_targets():
    raw, _, _ = load_guide()
    by_id = {step["id"]: step for step in raw["steps"]}
    design = by_id["ab_27_bias_controls"]["content"].casefold()
    significance = by_id["ab_45_significance_policy"]["content"].casefold()
    brief_and_open_inputs = " ".join(
        by_id[step_id]["content"].casefold()
        for step_id in ("ab_01_brief_facts", "ab_04_open_inputs", "ab_50_review_assumptions")
    )

    for phrase in (
        "estimand",
        "analysis population",
        "numerator, denominator, and outcome window",
        "minimum detectable effect",
        "power",
        "sample-size",
    ):
        assert phrase in design or phrase in significance or phrase in brief_and_open_inputs

    for phrase in (
        "not by itself a product win",
        "declare a winner only when pre-specified validity checks",
        "practical-effect criterion",
        "guardrail policy",
        "brief supplies no test family",
        "owners must choose experiment-specific values",
    ):
        assert phrase in significance

    prose = " ".join(
        f"{step.get('title', '')} {step.get('content', '')} "
        f"{json.dumps(step.get('decision', {}), ensure_ascii=True)} "
        f"{json.dumps(step.get('scaleTrigger', {}), ensure_ascii=True)}"
        for step in raw["steps"]
    )
    unsupported_numeric_target = re.compile(
        r"\b\d+(?:,\d{3})*(?:\.\d+)?\s*(?:%|ms|milliseconds?|seconds?|minutes?|hours?|days?|"
        r"users?|events?(?:\s*(?:/|per)\s*second)?|requests?(?:\s*(?:/|per)\s*second)?|samples?)\b",
        re.IGNORECASE,
    )
    assert unsupported_numeric_target.search(prose) is None


def test_event_scale_statistics_and_rollout_policies_are_problem_specific():
    raw, _, _ = load_guide()
    text = json.dumps(raw, ensure_ascii=True).casefold()

    for phrase in (
        "billions of events",
        "partition skew",
        "replay",
        "statistical significance",
        "uncertainty",
        "no test family",
        "does not define a freshness slo",
        "gradual rollout",
        "no percentage",
        "assignment creation as a rendered exposure",
    ):
        assert phrase in text, f"missing scale, analysis, or rollout treatment: {phrase}"

    assert "p-value cutoff" in text
    assert "no events-per-second target is inferred" in text
    assert "no rollout percentages" in text
    assert "significance threshold" in text
    assert "is supplied" in text
