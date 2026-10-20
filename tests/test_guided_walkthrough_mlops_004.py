"""Frozen-brief, catalog-action, signal, and graph checks for mlops_004."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "mlops_004"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / "mlops_004.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
CONNECTION_TYPES = {
    "api-call",
    "data-flow",
    "database-connection",
    "event-stream",
    "message-queue",
}
ACTION_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "decision_point",
    "scale_trigger",
    "conclusion",
}
FROZEN_BRIEF = {
    "id": "mlops_004",
    "title": "Design a Real-time Model Monitoring and Drift Detection System",
    "slug": "design-a-real-time-model-monitoring-and-drift-detection-system",
    "description": "Design a monitoring system that detects data drift, concept drift, and model performance degradation in production ML models, triggering automated alerts and retraining workflows.",
    "difficulty": "Hard",
    "category": "MLOps - Model Monitoring",
    "domain": "aiml",
    "estimated_time": "60-90 minutes",
    "has_guided_walkthrough": False,
    "requirements": [
        "Monitor input data distribution for drift",
        "Detect concept drift and prediction quality degradation",
        "Track model performance metrics in real-time",
        "Compute statistical tests for drift detection",
        "Alert on significant drift or performance drops",
        "Trigger automated retraining pipelines",
        "Store prediction logs for analysis",
        "Provide monitoring dashboards with drill-down",
    ],
    "constraints": [
        "Drift detection within 1 hour of occurrence",
        "Handle 1M+ predictions per day",
        "Support numerical, categorical, and text features",
        "Minimize false drift alarms",
        "Efficient storage for prediction logging",
    ],
    "hints": [
        "Use KS-test, PSI, or Jensen-Shannon divergence for drift",
        "Implement reference-window vs sliding-window comparison",
        "Use Evidently AI or Whylogs for monitoring",
        "Track feature distributions with histograms/sketches",
        "Implement delayed ground-truth label joins",
        "Use time-windowed aggregations for metric tracking",
    ],
    "tags": [
        "mlops",
        "model-monitoring",
        "drift-detection",
        "observability",
        "alerting",
        "production-ml",
    ],
    "companies": ["Uber", "Netflix", "Fiddler AI", "Arize AI"],
}


def load_problem() -> dict:
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def load_guide() -> dict:
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def catalog_component_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'(?m)^\s*id:\s*"{re.escape(component_type)}"', catalog)
    assert match, f"unknown component type {component_type!r}"
    end = catalog.find("\n  },", match.start())
    assert end != -1, f"could not find catalog block end for {component_type!r}"
    return catalog[match.start() : end]


def all_text(raw: dict) -> str:
    return json.dumps(raw, ensure_ascii=False).casefold()


def expected_anchors() -> set[str]:
    return {
        *(f"legacy-requirement:{number}" for number in range(1, 9)),
        *(f"legacy-constraint:{number}" for number in range(1, 6)),
    }


def test_frozen_snapshot_and_exact_requirements_constraints_and_hints_are_preserved():
    problem = load_problem()
    raw = load_guide()
    text = all_text(raw)

    assert {key: problem.get(key) for key in FROZEN_BRIEF} == FROZEN_BRIEF
    assert raw["problem_id"] == PROBLEM_ID
    assert raw["version"].endswith("local-review-draft")
    assert raw["totalSteps"] == len(raw["steps"])
    assert FROZEN_BRIEF["title"].casefold() in text
    assert FROZEN_BRIEF["description"].casefold() in text
    for field in ("requirements", "constraints", "hints"):
        for statement in FROZEN_BRIEF[field]:
            assert statement.casefold() in text, f"frozen {field} statement missing: {statement}"
    assert problem["has_guided_walkthrough"] is False
    assert "no browser persistence, ai assessment, or publication gate has been run or passed" in text


def test_schema_order_phases_and_every_requirement_has_an_applied_graph_action():
    raw = load_guide()
    guide = GuidedWalkthrough.model_validate(raw)

    assert guide.problem_id == PROBLEM_ID
    assert guide.version.endswith("local-review-draft")
    assert guide.totalSteps == len(guide.steps) == 45
    assert [step.stepNumber for step in guide.steps] == list(range(1, 46))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in ACTION_TYPES for step in guide.steps)

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(guide.steps[number - 1].phase == phase.name for number in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    expected = expected_anchors()
    actual = {anchor for step in raw["steps"] for anchor in step.get("requirementIds", [])}
    assert actual == expected
    graph_actions = {"add_component", "add_connection", "update_component"}
    for anchor in expected:
        assert any(
            step["type"] in graph_actions and anchor in step.get("requirementIds", [])
            for step in raw["steps"]
        ), f"{anchor} appears only on prose or decision steps, not an applied graph action"


def test_components_and_action_targets_resolve_to_catalog_nodes_and_properties():
    raw = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = [step["component"] for step in raw["steps"] if step["type"] == "add_component"]
    assert len(additions) == 12
    assert len({component["nodeId"] for component in additions}) == len(additions)

    for component in additions:
        block = catalog_component_block(catalog, component["componentType"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        properties = set(component["properties"])
        assert {"componentName", "purpose"} <= properties
        assert properties <= supported, (
            f"{component['nodeId']} uses unsupported properties: {properties - supported}"
        )
        assert component["label"].strip()
        assert component["description"].strip()
        assert component["highlightReason"].strip()

    added_by_id = {component["nodeId"]: component for component in additions}
    seen_nodes: set[str] = set()
    seen_edges: set[str] = set()
    for step in sorted(raw["steps"], key=lambda row: row["stepNumber"]):
        if step["type"] == "add_component":
            node_id = step["component"]["nodeId"]
            assert node_id not in seen_nodes
            seen_nodes.add(node_id)
        elif step["type"] == "add_connection":
            edge = step["connection"]
            assert edge["sourceNodeId"] in seen_nodes
            assert edge["targetNodeId"] in seen_nodes
            assert edge["sourceNodeId"] != edge["targetNodeId"]
            assert edge["edgeId"] not in seen_edges
            assert edge["connectionType"] in CONNECTION_TYPES
            assert edge["label"].strip() and edge["description"].strip()
            seen_edges.add(edge["edgeId"])
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            assert update["nodeId"] in added_by_id
            component = added_by_id[update["nodeId"]]
            block = catalog_component_block(catalog, component["componentType"])
            supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
            assert set(update["properties"]) <= supported


def test_ordered_replay_produces_one_connected_architecture():
    raw = load_guide()
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    component_ids = {component["id"] for component in architecture["components"]}
    edges = architecture["connections"]
    expected_component_ids = {
        step["component"]["nodeId"]
        for step in raw["steps"]
        if step["type"] == "add_component"
    }

    assert component_ids == expected_component_ids
    assert len(edges) == sum(step["type"] == "add_connection" for step in raw["steps"])
    assert len(replay["appliedStepIds"]) == len(component_ids) + len(edges)
    assert all(edge["source"] in component_ids and edge["target"] in component_ids for edge in edges)
    assert all(edge["type"] in CONNECTION_TYPES for edge in edges)

    neighbors = {component_id: set() for component_id in component_ids}
    for edge in edges:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached: set[str] = set()
    pending = deque([next(iter(component_ids))])
    while pending:
        current = pending.popleft()
        if current in reached:
            continue
        reached.add(current)
        pending.extend(neighbors[current] - reached)
    assert reached == component_ids


def test_data_concept_and_performance_signals_are_separate_and_label_aware():
    raw = load_guide()
    steps = {step["id"]: step for step in raw["steps"]}

    data_signal = steps["mlops004_data_drift_signal"]["content"].casefold()
    concept_signal = steps["mlops004_concept_drift_signal"]["content"].casefold()
    performance_signal = steps["mlops004_performance_signal"]["content"].casefold()
    assert "input" in data_signal and "does not require labels" in data_signal
    assert "relationship between features and verified outcomes" in concept_signal
    assert "feature-distribution change alone is not proof" in concept_signal
    assert "labeled sliding windows" in performance_signal
    assert "distinct from both input data drift and concept drift" in performance_signal


def test_failure_scenarios_have_distinct_explicit_responses():
    raw = load_guide()
    steps = {step["id"]: step for step in raw["steps"]}
    scenarios = {
        "mlops004_log_failure": ("bounded durable buffer", "mark any prediction without a durable log as unlogged", "never report a healthy drift result"),
        "mlops004_label_delay_failure": ("pending-label coverage", "join a late outcome idempotently", "not incorrect predictions"),
        "mlops004_insufficient_evidence_failure": ("insufficient-data or schema-mismatch state", "do not emit a normal no-drift result", "operational signals"),
        "mlops004_stale_dashboard_failure": ("stale or unavailable state", "last evaluated-through timestamp", "into a zero-drift result"),
        "mlops004_retraining_rejection": ("failed stage", "leave the currently approved serving version active", "do not promote an invalid candidate"),
    }
    for step_id, expected_phrases in scenarios.items():
        step = steps[step_id]
        assert step["type"] == "explanation"
        content = step["content"].casefold()
        for phrase in expected_phrases:
            assert phrase in content, f"{step_id} lacks scenario response: {phrase}"
    assert len({steps[step_id]["content"] for step_id in scenarios}) == len(scenarios)


def test_timing_and_volume_claims_stay_anchored_to_the_frozen_constraints():
    raw = load_guide()
    text = all_text(raw)
    detection = next(step for step in raw["steps"] if step["id"] == "mlops004_detection_bound")
    volume = next(step for step in raw["steps"] if step["id"] == "mlops004_prediction_volume")

    assert "drift detection within 1 hour of occurrence" in detection["content"].casefold()
    assert "handle 1m+ predictions per day" in volume["content"].casefold()
    assert "does not specify a fixed window size or polling interval" in detection["content"].casefold()
    assert "no numeric significance, effect-size, or minimum-sample threshold" in text
    assert "no log-retention horizon" in text
    assert "does not specify an automatic promotion policy" in text


def test_dashboard_query_and_retraining_trigger_paths_are_in_the_graph():
    raw = load_guide()
    replay = build_architecture(raw)
    edges = {
        (edge["source"], edge["target"])
        for edge in replay["architecture"]["connections"]
    }
    assert ("mlops004_dashboard", "mlops004_gateway") in edges
    assert ("mlops004_gateway", "mlops004_monitoring") in edges
    assert ("mlops004_monitoring", "mlops004_metrics") in edges
    assert ("mlops004_monitoring", "mlops004_retraining") in edges
    assert ("mlops004_retraining", "mlops004_registry") in edges
    dashboard = next(step for step in raw["steps"] if step["id"] == "mlops004_dashboard_flow")
    assert "reference and sliding-window distributions" in dashboard["content"]
    assert "prediction IDs" in dashboard["content"]
    assert "evaluated-through timestamp" in dashboard["content"]
