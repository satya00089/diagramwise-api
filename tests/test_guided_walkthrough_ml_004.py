"""Focused contract and architecture checks for the ml_004 review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "ml_004"
GUIDE_PATH = ROOT / "data/guided-walkthroughs/ml_004.json"
PROBLEMS_PATH = ROOT / "tests/fixtures/walkthroughs/problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic/src/config/components.ts"
CONNECTION_TYPES = {
    "api-call",
    "data-flow",
    "database-connection",
    "http",
    "message-queue",
}
ACTION_TYPES = {"add_component", "add_connection"}
EXPECTED_COMPONENT_TYPES = {
    "admin-console",
    "analytics",
    "api-gateway",
    "backend-server",
    "custom-component",
    "data-warehouse",
    "feature-store",
    "mlops-pipeline",
    "model-registry",
    "model-serving",
    "model-training",
    "monitoring",
    "object-storage",
    "queue",
}
CUSTOM_COMPONENT_NAMES = {
    "CRM, Billing & Product Usage Systems",
    "CRM & Marketing Automation Adapter",
}


def load_problem() -> dict:
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def load_guide() -> dict:
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def catalog_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"unknown palette component {component_type!r}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), f"incomplete palette entry for {component_type}"
    return catalog[match.start() : block_end]


def test_schema_phases_and_frozen_live_brief_are_exact():
    raw = load_guide()
    guide = GuidedWalkthrough.model_validate(raw)
    problem = load_problem()

    assert problem["title"] == "Design a Customer Churn Prediction System"
    assert problem["description"] == (
        "Design an ML system that predicts customer churn probability, identifies "
        "at-risk segments, determines churn drivers, and integrates with retention "
        "campaign tools for proactive engagement."
    )
    assert problem["requirements"] == [
        "Predict churn probability for each customer",
        "Identify key drivers of churn",
        "Segment customers by churn risk level",
        "Integrate with CRM and marketing automation",
        "Track model predictions vs actual outcomes",
        "Generate customer lifetime value estimates",
        "Trigger automated retention workflows",
        "Provide dashboards for business stakeholders",
    ]
    assert problem["constraints"] == [
        "Predict churn 30 days in advance",
        "Precision above 75% at top decile",
        "Process daily batch scoring for 10M+ customers",
        "Model retraining weekly with new data",
        "Explainable predictions for business users",
    ]
    assert problem["hints"] == [
        "Use survival analysis for time-to-churn modeling",
        "Engineer behavioral features from usage patterns",
        "Implement SHAP for feature attribution",
        "Use cohort analysis for segment-level insights",
        "Build a feature pipeline from CRM, billing, and usage data",
        "Implement propensity scoring with uplift modeling",
    ]
    assert problem["companies"] == ["Salesforce", "HubSpot", "Spotify", "Telcos"]
    assert problem["has_guided_walkthrough"] is False

    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 52
    assert [step.stepNumber for step in guide.steps] == list(range(1, 53))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.title and step.content for step in guide.steps)

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert len(phase.stepRange) == 2
        assert start == next_step <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    first_step = guide.steps[0].content
    for exact_fact in [
        problem["title"],
        problem["description"],
        *problem["requirements"],
        *problem["constraints"],
        *problem["hints"],
        *problem["companies"],
    ]:
        assert exact_fact in first_step


def test_every_requirement_and_constraint_has_an_explicit_design_action():
    raw = load_guide()
    expected_anchors = {
        *(f"legacy-requirement:{index}" for index in range(1, 9)),
        *(f"legacy-constraint:{index}" for index in range(1, 6)),
    }
    all_anchors = {
        anchor for step in raw["steps"] for anchor in step.get("requirementIds", [])
    }
    action_anchors = {
        anchor
        for step in raw["steps"]
        if step["type"] in ACTION_TYPES
        for anchor in step.get("requirementIds", [])
    }

    assert all_anchors == expected_anchors
    assert action_anchors == expected_anchors
    assert all(
        set(step.get("requirementIds", [])) <= expected_anchors
        for step in raw["steps"]
    )


def test_churn_source_step_only_anchors_work_done_by_source_systems():
    steps = {step["id"]: step for step in load_guide()["steps"]}

    assert steps["churn_sources"]["requirementIds"] == []

    downstream_action_by_anchor = {
        "legacy-requirement:1": "churn_serving",
        "legacy-requirement:2": "churn_serving",
        "legacy-requirement:5": "churn_analytics",
        "legacy-requirement:6": "churn_serving",
        "legacy-constraint:3": "churn_workflow_to_serving",
    }
    for anchor, action_id in downstream_action_by_anchor.items():
        assert anchor in steps[action_id]["requirementIds"], (
            f"{anchor} must be anchored to the action that implements it: {action_id}"
        )


def test_replay_is_a_connected_supported_architecture_with_required_flows():
    raw = load_guide()
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {component["id"] for component in architecture["components"]}
    edges = architecture["connections"]

    assert len(nodes) == 15
    assert len(edges) == 24
    assert len(replay["appliedStepIds"]) == 39
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in edges)
    assert all(edge["type"] in CONNECTION_TYPES for edge in edges)

    undirected = {node_id: set() for node_id in nodes}
    directed = {node_id: set() for node_id in nodes}
    for edge in edges:
        undirected[edge["source"]].add(edge["target"])
        undirected[edge["target"]].add(edge["source"])
        directed[edge["source"]].add(edge["target"])

    reached = set()
    pending = deque(["churn_sources"])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(undirected[current] - reached)
    assert reached == nodes

    def reaches(source: str, target: str) -> bool:
        seen = set()
        pending_nodes = [source]
        while pending_nodes:
            current = pending_nodes.pop()
            if current == target:
                return True
            if current not in seen:
                seen.add(current)
                pending_nodes.extend(directed[current] - seen)
        return False

    for source, target in (
        ("churn_sources", "churn_warehouse"),
        ("churn_warehouse", "churn_features"),
        ("churn_workflow", "churn_training"),
        ("churn_training", "churn_registry"),
        ("churn_registry", "churn_serving"),
        ("churn_features", "churn_serving"),
        ("churn_workflow", "churn_serving"),
        ("churn_serving", "churn_campaign_queue"),
        ("churn_campaign_queue", "churn_retention_adapter"),
        ("churn_retention_adapter", "churn_sources"),
        ("churn_serving", "churn_warehouse"),
        ("churn_retention_adapter", "churn_warehouse"),
        ("churn_warehouse", "churn_analytics"),
        ("churn_analytics", "churn_api"),
        ("churn_dashboard", "churn_api"),
        ("churn_serving", "churn_monitoring"),
    ):
        assert reaches(source, target), f"missing required path: {source} -> {target}"


def test_components_reuse_palette_definitions_and_only_customize_missing_systems():
    raw = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = [step["component"] for step in raw["steps"] if step["type"] == "add_component"]

    assert len(additions) == 15
    assert {component["componentType"] for component in additions} == EXPECTED_COMPONENT_TYPES
    custom_names = set()

    for component in additions:
        component_type = component["componentType"]
        block = catalog_block(catalog, component_type)
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert component["properties"]["componentName"] == component["label"]
        assert component["properties"]["purpose"]
        assert set(component["properties"]) <= supported
        assert set(component["position"]) == {"x", "y"}
        assert all(type(value) in (int, float) for value in component["position"].values())
        if component_type == "custom-component":
            custom_names.add(component["label"])

    assert custom_names == CUSTOM_COMPONENT_NAMES


def test_unprovided_numeric_targets_and_customer_counts_are_not_invented():
    raw = load_guide()
    prose = " ".join(
        [step["content"] for step in raw["steps"]]
        + [
            step["component"]["properties"]["purpose"]
            for step in raw["steps"]
            if step["type"] == "add_component"
        ]
    )

    stated_customer_counts = re.findall(
        r"\b(?:10M\+|\d[\d,.]*|\d+(?:\.\d+)?\s*(?:million|billion))\s*\+?\s*(?:customers|users|accounts)\b",
        prose,
        flags=re.IGNORECASE,
    )
    assert stated_customer_counts
    assert set(stated_customer_counts) == {"10M+ customers"}
    assert "30 days" in prose
    assert "above 75%" in prose
    assert "10M+" in prose
    assert "weekly" in prose.casefold()
    assert "completion window" in prose
    assert "do not invent" in prose.casefold()
    numeric_targets = re.findall(r"(?<!\w)\d+(?:\.\d+)?\s?(?:ms|%)", prose)
    assert set(numeric_targets) == {"75%"}


def test_survival_explainability_cohorts_and_uplift_are_distinguished():
    prose = json.dumps(load_guide(), ensure_ascii=False).casefold()
    for phrase in (
        "survival analysis",
        "right-censoring",
        "point-in-time",
        "precision at the top decile",
        "shap",
        "cohort",
        "propensity scoring",
        "uplift modeling",
        "not proof of causal drivers",
        "label maturity",
        "idempotent",
        "rollback",
    ):
        assert phrase in prose
