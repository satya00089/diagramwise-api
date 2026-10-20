"""Focused structural and exact-brief checks for the ml_003 review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "ml_003"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

TITLE = "Design a Credit Scoring ML Pipeline"
DESCRIPTION = (
    "Design a credit scoring system that uses ML to assess creditworthiness, "
    "handles imbalanced data, provides explainable decisions, and complies "
    "with fair lending regulations."
)
REQUIREMENTS = [
    "Train credit scoring models on historical data",
    "Handle imbalanced classes (default vs non-default)",
    "Provide feature importance for each decision",
    "Detect and mitigate bias across protected groups",
    "Generate adverse action reason codes",
    "Support model versioning and comparison",
    "Validate model performance on holdout sets",
    "Produce regulatory compliance documentation",
]
CONSTRAINTS = [
    "AUC-ROC above 0.85",
    "Model must be explainable (regulatory requirement)",
    "Bias metrics within fair lending thresholds",
    "Scoring latency under 100ms",
    "Handle 100k+ scoring requests per day",
]
HINTS = [
    "Use gradient boosting (XGBoost, LightGBM) as baseline",
    "Implement SHAP values for model explainability",
    "Use SMOTE or class weights for imbalanced data",
    "Implement fairness-aware training with AIF360",
    "Create a champion-challenger framework for model comparison",
    "Use feature engineering on bureau and transaction data",
]
ANCHORS = {
    *(f"legacy-requirement:{index}" for index in range(1, len(REQUIREMENTS) + 1)),
    *(f"legacy-constraint:{index}" for index in range(1, len(CONSTRAINTS) + 1)),
}
ACTION_TYPES = {"add_component", "add_connection", "update_component"}
EXPECTED_COMPONENT_TYPES = {
    "api-gateway",
    "backend-server",
    "object-storage",
    "feature-store",
    "mlops-pipeline",
    "model-training",
    "ml-model",
    "custom-component",
    "model-registry",
    "model-serving",
    "database",
    "queue",
    "monitoring",
}
CUSTOM_COMPONENT_NAMES = {
    "Fair Lending & Holdout Validation Gate",
    "Regulatory Evidence & Decision Audit",
}
CONNECTION_TYPES = {
    "http",
    "tcp",
    "websocket",
    "message-queue",
    "database-connection",
    "api-call",
    "data-flow",
    "event-stream",
}


def load_guide_and_problem():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    return raw, problem


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"{step_id}: unknown catalog component {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), (
        f"{step_id}: incomplete catalog definition for {component_type}"
    )
    return catalog[match.start() : block_end]


def assert_catalog_properties(
    catalog: str, component_type: str, properties: dict, step_id: str
) -> None:
    block = catalog_block(catalog, component_type, step_id)
    supported = set(re.findall(r'\bkey:\s*"([^\"]+)"', block))
    assert set(properties) <= supported, (
        f"{step_id}: unsupported {component_type} properties "
        f"{sorted(set(properties) - supported)}"
    )

    for key, value in properties.items():
        field_start = re.search(rf'\{{\s*key:\s*"{re.escape(key)}"', block)
        assert field_start, f"{step_id}: missing {component_type}.{key} in catalog"
        field_end = block.find("},", field_start.start())
        assert field_end != -1, f"{step_id}: incomplete catalog property {key}"
        field = block[field_start.start() : field_end]
        field_type = re.search(r'\btype:\s*"([^\"]+)"', field)
        assert field_type, f"{step_id}: catalog property {key} has no type"

        kind = field_type.group(1)
        if kind == "boolean":
            assert type(value) is bool, f"{step_id}/{key} must be boolean"
        elif kind == "number":
            assert type(value) in (int, float), f"{step_id}/{key} must be numeric"
        elif kind in {"text", "textarea"}:
            assert isinstance(value, str), f"{step_id}/{key} must be text"
        elif kind == "select":
            options = re.search(r'\boptions:\s*\[([^\]]*)\]', field, re.DOTALL)
            assert options, f"{step_id}/{key}: select options are missing"
            allowed = set(re.findall(r'"([^\"]+)"', options.group(1)))
            assert value in allowed, (
                f"{step_id}/{key}: {value!r} is not one of {sorted(allowed)}"
            )


def test_exact_frozen_brief_and_pydantic_schema():
    raw, problem = load_guide_and_problem()

    expected_brief = {
        "id": PROBLEM_ID,
        "title": TITLE,
        "description": DESCRIPTION,
        "requirements": REQUIREMENTS,
        "constraints": CONSTRAINTS,
        "hints": HINTS,
    }
    for key, value in expected_brief.items():
        assert problem[key] == value
    assert problem["has_guided_walkthrough"] is False

    guide = GuidedWalkthrough.model_validate(raw)
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 54


def test_steps_phases_exact_brief_and_action_anchor_coverage():
    raw, _ = load_guide_and_problem()
    guide = GuidedWalkthrough.model_validate(raw)

    assert [step.stepNumber for step in guide.steps] == list(range(1, 55))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.id and step.title and step.content for step in guide.steps)

    next_expected = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert len(phase.stepRange) == 2
        assert start == next_expected
        assert start <= end <= guide.totalSteps
        assert all(step.phase == phase.name for step in guide.steps[start - 1 : end])
        next_expected = end + 1
    assert next_expected == guide.totalSteps + 1

    first_step = guide.steps[0].content
    for exact_fact in [TITLE, DESCRIPTION, *REQUIREMENTS, *CONSTRAINTS, *HINTS]:
        assert exact_fact in first_step, f"Supplied brief item missing verbatim: {exact_fact}"

    framing = guide.steps[1].content
    assert "Supplied facts:" in framing
    assert "Clarifying questions:" in framing
    assert "Architecture assumptions to validate:" in framing

    mapped_anchors = {
        anchor for step in guide.steps for anchor in step.requirementIds
    }
    action_anchors = {
        anchor
        for step in guide.steps
        if step.type in ACTION_TYPES
        for anchor in step.requirementIds
    }
    assert mapped_anchors == action_anchors == ANCHORS
    assert all(set(step.requirementIds) <= ANCHORS for step in guide.steps)

    for step in guide.steps:
        if step.type == "decision_point":
            assert step.decision is not None
            assert step.decision.question and step.decision.chosen
            assert step.decision.chosenReason
            assert len(step.decision.alternatives) >= 2
            assert all(item.option and item.tradeoff for item in step.decision.alternatives)
        elif step.type == "scale_trigger":
            assert step.scaleTrigger is not None
            assert step.scaleTrigger.metric
            assert step.scaleTrigger.action
            assert step.scaleTrigger.impact


def test_every_component_uses_a_real_catalog_type_and_supported_properties():
    raw, _ = load_guide_and_problem()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}

    for step in raw["steps"]:
        if step["type"] != "add_component":
            continue
        component = step["component"]
        assert component["nodeId"] not in components
        assert set(component["position"]) == {"x", "y"}
        assert all(type(value) in (int, float) for value in component["position"].values())
        assert component["properties"]["componentName"] == component["label"]
        assert component["properties"]["purpose"]
        assert_catalog_properties(
            catalog, component["componentType"], component["properties"], step["id"]
        )
        components[component["nodeId"]] = component

    actual_types = {component["componentType"] for component in components.values()}
    assert actual_types == EXPECTED_COMPONENT_TYPES
    for component_type in actual_types:
        catalog_block(catalog, component_type, "component type inventory")

    custom_names = {
        component["properties"]["componentName"]
        for component in components.values()
        if component["componentType"] == "custom-component"
    }
    assert custom_names == CUSTOM_COMPONENT_NAMES
    assert components["ml003_reason_mapper"]["componentType"] == "backend-server"


def test_connections_are_ordered_valid_and_form_one_semantic_graph():
    raw, _ = load_guide_and_problem()
    known_nodes = set()
    component_ids = []
    edge_ids = []

    for step in sorted(raw["steps"], key=lambda row: row["stepNumber"]):
        if step["type"] == "add_component":
            node_id = step["component"]["nodeId"]
            assert node_id not in known_nodes
            known_nodes.add(node_id)
            component_ids.append(node_id)
        elif step["type"] == "add_connection":
            connection = step["connection"]
            assert connection["sourceNodeId"] in known_nodes, step["id"]
            assert connection["targetNodeId"] in known_nodes, step["id"]
            assert connection["connectionType"] in CONNECTION_TYPES
            assert connection["label"] and connection["description"]
            edge_ids.append(connection["edgeId"])

    assert len(component_ids) == len(set(component_ids))
    assert len(edge_ids) == len(set(edge_ids))

    replay = build_architecture(raw)
    graph = replay["architecture"]
    nodes = {component["id"]: component for component in graph["components"]}
    edges = graph["connections"]
    assert set(nodes) == set(component_ids)
    assert len(edges) == len(edge_ids)
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in edges)
    assert all(edge["type"] in CONNECTION_TYPES for edge in edges)

    neighbors = {node_id: set() for node_id in nodes}
    directed = {node_id: set() for node_id in nodes}
    for edge in edges:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
        directed[edge["source"]].add(edge["target"])

    reached = set()
    pending = deque(["ml003_gateway"])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    assert reached == set(nodes)

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

    assert reaches("ml003_history_store", "ml003_training")
    assert reaches("ml003_training", "ml003_validation_gate")
    assert reaches("ml003_validation_gate", "ml003_registry")
    assert reaches("ml003_registry", "ml003_serving")
    assert reaches("ml003_gateway", "ml003_decision_service")
    assert reaches("ml003_decision_service", "ml003_serving")
    assert reaches("ml003_serving", "ml003_reason_mapper")
    assert reaches("ml003_decision_service", "ml003_decision_log")
    assert reaches("ml003_decision_service", "ml003_audit_queue")
    assert reaches("ml003_audit_queue", "ml003_decision_log")
    assert not any(
        edge["source"] == "ml003_decision_service"
        and edge["target"] == "ml003_decision_log"
        for edge in edges
    )
    assert reaches("ml003_audit_queue", "ml003_compliance_processor")
    assert reaches("ml003_compliance_processor", "ml003_evidence_archive")


def test_required_features_fail_closed_and_provenance_is_async():
    raw, _ = load_guide_and_problem()
    steps = {step["id"]: step for step in raw["steps"]}

    decision_service = steps["ml003_decision_service"]["component"]
    service_purpose = decision_service["properties"]["purpose"].casefold()
    assert "fail closed" in service_purpose
    assert "retryable unavailable response" in service_purpose
    assert "owner-approved freshness bound" in service_purpose

    provenance_step = steps["ml003_edge_decision_store"]
    assert provenance_step["connection"]["sourceNodeId"] == "ml003_audit_queue"
    assert provenance_step["connection"]["targetNodeId"] == "ml003_decision_log"
    assert "idempotent consumer" in provenance_step["content"].casefold()
    assert "off the latency-critical path" in provenance_step["content"].casefold()

    queue_step = steps["ml003_edge_decision_queue"]
    assert "durable queue acceptance" in queue_step["content"].casefold()
    assert "retryable unavailable response" in queue_step["content"].casefold()


def test_catalog_choices_and_walkthrough_keep_unspecified_targets_explicit():
    raw, _ = load_guide_and_problem()
    text = json.dumps(raw, ensure_ascii=False).casefold()

    for phrase in (
        "class weights",
        "smote",
        "xgboost",
        "shap",
        "aif360",
        "champion",
        "holdout",
        "protected-group",
        "adverse-action",
        "100k+",
        "under 100ms",
        "do not invent",
        "clarifying questions",
        "architecture assumptions to validate",
    ):
        assert phrase in text, f"Missing design detail or explicit caveat: {phrase}"

    assert "99.9%" not in text
    assert "50ms" not in text
    assert sum(
        step.get("component", {}).get("componentType") == "custom-component"
        for step in raw["steps"]
    ) == len(CUSTOM_COMPONENT_NAMES)
