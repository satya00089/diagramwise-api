"""Frozen-brief, catalog, and local graph checks for the AWS ML pipeline draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_aws_006"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEM_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = next(
    problem
    for problem in json.loads(PROBLEM_FIXTURE_PATH.read_text(encoding="utf-8"))
    if problem["id"] == PROBLEM_ID
)
STEP_TYPES = {"explanation", "add_component", "add_connection", "decision_point", "scale_trigger"}
CONNECTION_TYPES = {"api-call", "data-flow", "event-stream", "message-queue"}
EXPECTED_COMPONENT_TYPES = {
    "mlpipe_s3": "object-storage",
    "mlpipe_preprocess": "serverless-function",
    "mlpipe_workflow": "custom-component",
    "mlpipe_training": "model-training",
    "mlpipe_experiments": "database",
    "mlpipe_registry": "model-registry",
    "mlpipe_endpoint": "model-serving",
    "mlpipe_api": "api-gateway",
    "mlpipe_monitoring": "monitoring",
}
EXPECTED_COMPONENT_PROPERTY_KEYS = {
    "mlpipe_s3": {"componentName", "purpose"},
    "mlpipe_preprocess": {"componentName", "purpose"},
    "mlpipe_workflow": {"componentName", "purpose", "componentType", "technology"},
    "mlpipe_training": {"componentName", "purpose"},
    "mlpipe_experiments": {"componentName", "purpose"},
    "mlpipe_registry": {"componentName", "purpose"},
    "mlpipe_endpoint": {"componentName", "purpose"},
    "mlpipe_api": {"componentName", "purpose"},
    "mlpipe_monitoring": {"componentName", "purpose"},
}
EXPECTED_ACTION_ANCHORS = {
    "mlpipe_data": {"legacy-requirement:1", "legacy-requirement:2", "legacy-constraint:4", "legacy-constraint:5"},
    "mlpipe_preprocess": {"legacy-requirement:1", "legacy-constraint:4", "legacy-constraint:5"},
    "mlpipe_workflow": {"legacy-requirement:6", "legacy-constraint:3", "legacy-constraint:4"},
    "mlpipe_training": {"legacy-requirement:1", "legacy-requirement:8", "legacy-constraint:5"},
    "mlpipe_experiments": {"legacy-requirement:8", "legacy-constraint:4"},
    "mlpipe_registry": {"legacy-requirement:2", "legacy-constraint:4"},
    "mlpipe_endpoint": {"legacy-requirement:3", "legacy-requirement:4", "legacy-requirement:7", "legacy-constraint:1", "legacy-constraint:2", "legacy-constraint:5"},
    "mlpipe_api": {"legacy-requirement:3", "legacy-constraint:1", "legacy-constraint:2"},
    "mlpipe_monitoring": {"legacy-requirement:5", "legacy-requirement:6", "legacy-constraint:2", "legacy-constraint:3"},
    "mlpipe_data_preprocess_edge": {"legacy-requirement:1", "legacy-constraint:4"},
    "mlpipe_workflow_preprocess_edge": {"legacy-requirement:1"},
    "mlpipe_preprocess_data_edge": {"legacy-requirement:1", "legacy-constraint:4"},
    "mlpipe_training_edge": {"legacy-requirement:1", "legacy-constraint:4"},
    "mlpipe_training_artifact_edge": {"legacy-requirement:2", "legacy-constraint:4"},
    "mlpipe_experiment_edge": {"legacy-requirement:8", "legacy-constraint:4", "legacy-constraint:5"},
    "mlpipe_register_edge": {"legacy-requirement:2", "legacy-constraint:4"},
    "mlpipe_registry_workflow_edge": {"legacy-requirement:6", "legacy-constraint:3", "legacy-constraint:4"},
    "mlpipe_workflow_endpoint_edge": {"legacy-requirement:3", "legacy-constraint:3"},
    "mlpipe_registry_endpoint_edge": {"legacy-requirement:2", "legacy-requirement:3", "legacy-constraint:4"},
    "mlpipe_api_endpoint_edge": {"legacy-requirement:3", "legacy-constraint:1", "legacy-constraint:2"},
    "mlpipe_endpoint_api_edge": {"legacy-requirement:3", "legacy-constraint:1"},
    "mlpipe_endpoint_monitor_edge": {"legacy-requirement:7", "legacy-constraint:1", "legacy-constraint:2"},
    "mlpipe_monitor_workflow_edge": {"legacy-requirement:6", "legacy-constraint:3"},
}


def load_guide() -> tuple[dict, GuidedWalkthrough]:
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def catalog_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'(?m)^    id:\s*"{re.escape(component_type)}"\s*,', catalog)
    assert match, f"Unknown component catalog ID {component_type!r}"
    end = re.search(r"(?m)^  \},\s*$", catalog[match.end() :])
    assert end, f"Could not delimit component catalog ID {component_type!r}"
    return catalog[match.start() : match.end() + end.start()]


def expected_anchors() -> set[str]:
    return {
        *(f"legacy-requirement:{index}" for index in range(1, len(FROZEN_BRIEF["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(FROZEN_BRIEF["constraints"]) + 1)),
    }


def test_frozen_brief_identity_requirements_and_constraints_are_covered_exactly():
    raw, guide = load_guide()
    assert guide.problem_id == FROZEN_BRIEF["id"]
    assert raw["version"].endswith("review-draft")

    serialized = json.dumps(raw, ensure_ascii=False)
    for field in ("title", "description", "difficulty", "category", "estimated_time"):
        assert FROZEN_BRIEF[field] in serialized
    for field in ("requirements", "constraints", "hints"):
        for brief_item in FROZEN_BRIEF[field]:
            assert brief_item in serialized, f"Missing frozen {field[:-1]}: {brief_item}"

    all_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    graph_action_anchors = {
        anchor
        for step in guide.steps
        if step.type in {"add_component", "add_connection"}
        for anchor in step.requirementIds
    }
    assert all_anchors == expected_anchors()
    assert graph_action_anchors == expected_anchors()


def test_steps_phases_and_connection_actions_are_ordered_and_valid():
    raw, guide = load_guide()
    assert guide.totalSteps == len(guide.steps) == 31
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES for step in guide.steps)

    existing_nodes: set[str] = set()
    edge_ids: set[str] = set()
    for step in raw["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            assert component["nodeId"] not in existing_nodes
            existing_nodes.add(component["nodeId"])
        elif step["type"] == "add_connection":
            connection = step["connection"]
            assert connection["edgeId"] not in edge_ids
            edge_ids.add(connection["edgeId"])
            assert connection["sourceNodeId"] in existing_nodes
            assert connection["targetNodeId"] in existing_nodes
            assert connection["connectionType"] in CONNECTION_TYPES
        elif step["type"] == "decision_point":
            assert step["decision"]["question"] and step["decision"]["chosen"]
        elif step["type"] == "scale_trigger":
            assert all(step["scaleTrigger"][key] for key in ("metric", "action", "impact"))

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1


def test_catalog_components_properties_and_replay_form_one_connected_graph():
    raw, guide = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step.component.nodeId: step.component
        for step in guide.steps
        if step.type == "add_component" and step.component is not None
    }
    assert {node_id: component.componentType for node_id, component in additions.items()} == EXPECTED_COMPONENT_TYPES

    for node_id, component in additions.items():
        block = catalog_block(catalog, component.componentType)
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert component.properties
        assert set(component.properties) == EXPECTED_COMPONENT_PROPERTY_KEYS[node_id]
        assert set(component.properties) <= supported, (
            f"{node_id} has unsupported {component.componentType} properties: "
            f"{sorted(set(component.properties) - supported)}"
        )

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    components = {component["id"] for component in architecture["components"]}
    edges = architecture["connections"]
    assert len(components) == 9
    assert len(edges) == 14
    assert components == set(EXPECTED_COMPONENT_TYPES)
    neighbors = {component_id: set() for component_id in components}
    for edge in edges:
        assert edge["type"] in CONNECTION_TYPES
        assert edge["source"] in components and edge["target"] in components
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])

    reached: set[str] = set()
    pending = deque([next(iter(components))])
    while pending:
        current = pending.popleft()
        if current in reached:
            continue
        reached.add(current)
        pending.extend(neighbors[current] - reached)
    assert reached == components
    assert len(replay["appliedStepIds"]) > len(replay["explanationOnlyStepIds"])


def test_aws_pipeline_choices_cover_ab_lineage_retraining_and_capacity_targets():
    raw, _ = load_guide()
    serialized = json.dumps(raw, ensure_ascii=False).casefold()
    for phrase in (
        "sagemaker",
        "step functions",
        "lambda",
        "api gateway",
        "cloudwatch",
        "s3",
        "1000+ predictions per second",
        "under 100ms",
        "lineage",
        "checkpoint",
    ):
        assert phrase in serialized

    decisions = [step["decision"]["chosen"].casefold() for step in raw["steps"] if step["type"] == "decision_point"]
    assert any("a/b" in choice and "90/10" in choice for choice in decisions)
    assert any("automatically create and evaluate" in choice for choice in decisions)
    assert any("approved, already-loaded versions" in choice for choice in decisions)


def test_each_architecture_action_has_only_its_direct_frozen_brief_anchors():
    _, guide = load_guide()
    actual = {
        step.id: set(step.requirementIds)
        for step in guide.steps
        if step.type in {"add_component", "add_connection"}
    }
    assert actual == EXPECTED_ACTION_ANCHORS


def test_model_quality_packaging_and_serving_rollout_use_separate_evidence_gates():
    _, guide = load_guide()
    steps = {step.id: step for step in guide.steps}

    assert "offline evaluation outputs" in steps["mlpipe_training"].content
    assert "separate from serving-package readiness" in steps["mlpipe_training"].content
    assert "offline model-quality evidence" in steps["mlpipe_experiments"].content
    assert "does not prove serving-package compatibility" in steps["mlpipe_experiments"].content
    assert "serving-package manifest" in steps["mlpipe_registry"].content
    assert "distinct from package compatibility/readiness" in steps["mlpipe_registry"].content
    assert "two independent statuses" in steps["mlpipe_registry_workflow_edge"].content
    assert "model-quality gate and serving-package preflight" in steps["mlpipe_workflow_endpoint_edge"].content
    assert "does not establish predictive correctness or model quality" in steps["mlpipe_endpoint_monitor_edge"].content
    assert "A/B assignment and a healthy endpoint do not prove model quality" in steps["mlpipe_ab_policy"].content
    assert "independent model-quality and serving-package readiness policies" in steps["mlpipe_retrain_gate"].decision.chosen
    assert "Operational latency/error success is not proof of model quality" in steps["mlpipe_acceptance"].content


def test_unstated_capacity_latency_and_ab_values_are_explicit_assumptions():
    _, guide = load_guide()
    steps = {step.id: step for step in guide.steps}
    sizing = steps["mlpipe_assumptions"].content.casefold()
    assert "per-instance capacity" in sizing
    assert "latency percentile" in sizing
    assert "measurement boundary" in sizing
    assert "as an assumption" in sizing

    scale = steps["mlpipe_scale_trigger"].scaleTrigger
    assert "1000+ predictions-per-second" in scale.metric
    assert "under-100ms" in scale.metric
    assert "no instance count" in scale.action
    assert "any selected values are assumptions" in scale.action

    ab = steps["mlpipe_ab_policy"]
    assert "90/10 split is only an illustrative rollout assumption" in ab.content
    assert "illustrative 90/10 A/B traffic split" in ab.decision.chosen
