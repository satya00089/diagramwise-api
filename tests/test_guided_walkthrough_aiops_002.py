"""Local structural review for the predictive auto-scaling walkthrough draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / "aiops_002.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

DESCRIPTION = (
    "Design an AIOps system that predicts future resource demands using ML models "
    "and proactively scales infrastructure, reducing both over-provisioning costs "
    "and under-provisioning incidents."
)
REQUIREMENTS = [
    "Forecast resource demand using historical patterns",
    "Scale infrastructure proactively before demand spikes",
    "Handle multiple scaling dimensions (CPU, memory, network)",
    "Learn from seasonal patterns and special events",
    "Integrate with cloud auto-scaling APIs",
    "Implement scaling guardrails and limits",
    "Track cost savings from predictive scaling",
    "Handle multi-service scaling dependencies",
]
CONSTRAINTS = [
    "Forecast accuracy within 15% of actual demand",
    "Scale-up completed before demand spike arrival",
    "Reduce over-provisioning costs by 30%",
    "Zero missed SLAs due to late scaling",
    "Support scaling across 50+ services",
]
HINTS = [
    "Use time-series forecasting (Prophet, DeepAR) for demand prediction",
    "Implement multi-step forecasting for different horizons",
    "Use calendar features for event-driven scaling",
    "Implement cooldown periods to prevent oscillation",
    "Use reinforcement learning for optimal scaling policies",
    "Combine reactive and predictive scaling strategies",
]
ANCHORS = {
    *(f"legacy-requirement:{index}" for index in range(1, len(REQUIREMENTS) + 1)),
    *(f"legacy-constraint:{index}" for index in range(1, len(CONSTRAINTS) + 1)),
}
ACTION_TYPES = {"add_component", "add_connection", "decision_point"}
STEP_TYPES = ACTION_TYPES | {"explanation", "scale_trigger"}
CONNECTION_TYPES = {
    "api-call",
    "data-flow",
    "database-connection",
    "event-stream",
    "message-queue",
    "model-release",
}
EXPECTED_PHASES = [
    ("Observe and prepare demand signals", 1, 10),
    ("Train and serve demand forecasts", 11, 22),
    ("Apply guarded scaling across dependent services", 23, 41),
    ("Measure outcomes and prove safe operation", 42, 51),
]


def load_problem() -> dict:
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == "aiops_002")


def load_guide() -> dict:
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def test_frozen_problem_brief_and_review_draft_schema():
    problem = load_problem()
    guide = GuidedWalkthrough.model_validate(load_guide())

    assert problem["title"] == "Design a Predictive Auto-Scaling System"
    assert problem["description"] == DESCRIPTION
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert problem["hints"] == HINTS
    assert problem["companies"] == ["Netflix", "Amazon", "Google", "Spot.io"]
    assert guide.problem_id == "aiops_002"
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == 51


def test_steps_phases_and_all_brief_anchors_are_actionable():
    guide = load_guide()
    steps = guide["steps"]
    assert [step["stepNumber"] for step in steps] == list(range(1, 52))
    assert len({step["id"] for step in steps}) == len(steps)
    assert all(step["type"] in STEP_TYPES for step in steps)
    assert [
        (phase["name"], phase["stepRange"][0], phase["stepRange"][1])
        for phase in guide["phases"]
    ] == EXPECTED_PHASES

    next_step = 1
    for phase in guide["phases"]:
        start, end = phase["stepRange"]
        assert start == next_step and start <= end
        assert phase["description"].strip()
        assert all(steps[number - 1]["phase"] == phase["name"] for number in range(start, end + 1))
        next_step = end + 1
    assert next_step == 52

    counts = {kind: sum(step["type"] == kind for step in steps) for kind in STEP_TYPES}
    assert counts == {
        "explanation": 4,
        "add_component": 17,
        "add_connection": 22,
        "decision_point": 6,
        "scale_trigger": 2,
    }
    for step in steps:
        if step["type"] == "decision_point":
            assert step["decision"]["chosen"]
            assert step["decision"]["chosenReason"]
            assert len(step["decision"]["alternatives"]) >= 2
            assert step["componentUpdate"]["properties"]
        elif step["type"] == "scale_trigger":
            assert all(step["scaleTrigger"][key] for key in ("metric", "action", "impact"))

    observed = {
        anchor for step in steps for anchor in step.get("requirementIds", [])
    }
    actionable = {
        anchor
        for step in steps
        if step["type"] in ACTION_TYPES
        for anchor in step.get("requirementIds", [])
    }
    assert observed == ANCHORS
    assert actionable == ANCHORS


def test_components_and_updates_use_existing_catalog_properties():
    guide = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}

    for step in guide["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            assert component["nodeId"] not in components
            assert component["componentType"] != "custom-component"
            assert component["properties"]["componentName"] == component["label"]
            assert component["properties"]["purpose"].strip()
            assert component["description"].strip()
            components[component["nodeId"]] = component
            properties = component["properties"]
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            assert update["nodeId"] in components
            component = components[update["nodeId"]]
            properties = update["properties"]
            assert properties
        else:
            continue

        component_type = component["componentType"]
        match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
        assert match, f"{step['id']} uses unknown catalog ID {component_type}"
        block_end = catalog.find("\n  },", match.start())
        assert block_end > match.start()
        component_block = catalog[match.start():block_end]
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', component_block))
        assert set(properties) <= supported, (
            f"{step['id']} has unsupported {component_type} properties "
            f"{sorted(set(properties) - supported)}"
        )
        for key, value in properties.items():
            property_start = re.search(rf'\{{\s*key:\s*"{re.escape(key)}"', component_block)
            assert property_start is not None
            remainder = component_block[property_start.start():]
            next_property = re.search(r'\n\s*\{\s*key:', remainder[1:])
            property_block = remainder[:next_property.start() + 1] if next_property else remainder
            field_type = re.search(r'\btype:\s*"([^"]+)"', property_block)
            assert field_type is not None
            if field_type[1] == "boolean":
                assert type(value) is bool
            elif field_type[1] == "number":
                assert type(value) in (int, float)
            elif field_type[1] == "select":
                options = re.search(r'\boptions:\s*\[([^\]]*)\]', property_block, re.DOTALL)
                assert options is not None
                allowed = set(re.findall(r'"([^"]+)"', options[1]))
                assert value in allowed, f"Invalid {component_type}.{key}={value!r}"

    assert len(components) == 17
    assert components["pas_history"]["properties"]["type"] == "Time-Series"
    assert components["pas_topology"]["properties"]["type"] == "Graph"
    assert components["pas_serving"]["properties"]["platform"] == "Custom API"
    assert components["pas_adapter"]["componentType"] == "backend-server"
    assert components["pas_targets"]["componentType"] == "container-orchestrator"


def test_replay_creates_one_connected_catalog_architecture():
    guide = load_guide()
    built = build_architecture(guide)
    architecture = built["architecture"]
    nodes = {component["id"] for component in architecture["components"]}
    edges = architecture["connections"]

    assert len(nodes) == 17
    assert len(edges) == 22
    assert len(built["acceptedDecisions"]) == 6
    assert len(built["appliedStepIds"]) == 45
    assert len(built["explanationOnlyStepIds"]) == 6
    assert all(edge["type"] in CONNECTION_TYPES for edge in edges)
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in edges)

    neighbors = {node: set() for node in nodes}
    pairs = set()
    for edge in edges:
        pair = (edge["source"], edge["target"])
        assert pair not in pairs
        pairs.add(pair)
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["pas_metrics"])
    while pending:
        node = pending.popleft()
        if node in reached:
            continue
        reached.add(node)
        pending.extend(neighbors[node] - reached)
    assert reached == nodes
    assert {
        ("pas_serving", "pas_policy"),
        ("pas_metrics", "pas_policy"),
        ("pas_topology", "pas_policy"),
        ("pas_guardrails", "pas_policy"),
        ("pas_policy", "pas_queue"),
        ("pas_queue", "pas_workers"),
        ("pas_workers", "pas_adapter"),
        ("pas_adapter", "pas_targets"),
        ("pas_targets", "pas_metrics"),
        ("pas_targets", "pas_analytics"),
    } <= pairs

    request = make_request(load_problem(), guide, built)
    assert request["problem"]["requirements"] == "\n".join(REQUIREMENTS)
    assert request["problem"]["constraints"] == "\n".join(CONSTRAINTS)
    assert request["problem"]["requirementRevision"].startswith("legacy-")
    assert len(request["components"]) == 17


def test_unspecified_horizons_topology_limits_and_slas_remain_open():
    guide = load_guide()
    content = "\n".join(step["content"] for step in guide["steps"]).casefold()
    for phrase in (
        "does not define forecast horizons",
        "ask how far ahead",
        "service topology",
        "actual numeric limits",
        "sla definitions",
        "measurement windows",
        "target provider/workload types",
        "error statistic and aggregation undefined",
    ):
        assert phrase in content, phrase

    final_review = guide["steps"][-1]["content"]
    for target in ("within 15%", "before each relevant spike", "30%", "zero SLA misses", "50+ services"):
        assert target in final_review
    assert "do not prove those outcomes" in final_review


def step_by_id(guide: dict, step_id: str) -> dict:
    return next(step for step in guide["steps"] if step["id"] == step_id)


def nested_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from nested_strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from nested_strings(nested)


def test_forecasts_are_advisory_and_policy_owns_scaling_authority():
    guide = load_guide()
    forecast_quality = step_by_id(guide, "pas_18")
    policy = step_by_id(guide, "pas_19")
    forecast_edge = step_by_id(guide, "pas_20")

    assert "acceptance target, not evidence" in forecast_quality["content"]
    assert "never as an authorized scaling command" in forecast_quality["content"]
    assert "one advisory input" in policy["content"]
    assert "cannot authorize or call a provider API" in policy["content"]
    assert "auditable desired-state proposal" in policy["content"]
    assert "only as an advisory signal" in forecast_edge["content"]
    assert "no desired-state command or provider authority" in forecast_edge["content"]
    assert forecast_edge["connection"]["sourceNodeId"] == "pas_serving"
    assert forecast_edge["connection"]["targetNodeId"] == "pas_policy"


def test_reactive_fallback_is_guarded_and_fails_safe_when_inputs_are_unavailable():
    guide = load_guide()
    fallback = step_by_id(guide, "pas_21")["content"]
    combined_control = step_by_id(guide, "pas_22")["content"]
    guardrail = step_by_id(guide, "pas_27")["content"]
    failures = step_by_id(guide, "pas_41")["content"]

    assert "disable predictive adjustments" in fallback
    assert "same per-service limits" in fallback
    assert "If telemetry, policy, or observed target state is unavailable" in fallback
    assert "no predictive write or automatic scale-down" in fallback
    assert "same policy and serialized target-action boundary" in combined_control
    assert "must not wait for a prediction" in combined_control
    assert "only when fresh observations" in guardrail
    assert "same safeguards" in guardrail
    assert "prevent automated scale-down" in failures
    assert "alert and escalate" in failures


def test_hysteresis_requires_distinct_thresholds_and_sustained_scale_down_evidence():
    guide = load_guide()
    hysteresis = step_by_id(guide, "pas_39")
    content = hysteresis["content"]

    for phrase in (
        "separately reviewed scale-up and lower scale-down thresholds",
        "fresh observed demand crossing the reactive threshold must not wait",
        "remains below the lower threshold",
        "owner-approved dwell/cooldown",
        "prior operations have settled",
        "never reverse an in-flight change",
        "numeric thresholds and dwell times as service-owner decisions",
    ):
        assert phrase in content
    assert "healthy guarded reactive scale-up" in content


def test_accuracy_is_only_the_brief_target_and_no_numeric_latency_slo_is_invented():
    guide = load_guide()
    narrative = "\n".join(nested_strings(guide))
    percentages = set(re.findall(r"(?<![\w])\d+(?:\.\d+)?\s*%", narrative))

    assert percentages == {"15%", "30%"}
    assert "within 15%" in step_by_id(guide, "pas_18")["scaleTrigger"]["metric"]
    assert "gives no numeric latency target" in narrative
    assert not re.search(
        r"\b\d+(?:\.\d+)?\s*(?:ms|milliseconds?|seconds?|minutes?|hours?)\b",
        narrative,
        re.IGNORECASE,
    )

