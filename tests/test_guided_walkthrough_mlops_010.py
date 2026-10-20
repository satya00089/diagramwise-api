"""Focused frozen-brief, palette, and replay checks for the mlops_010 draft."""

import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "mlops_010"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / "mlops_010.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_ROW_TEXT = (
    "Design a Model Serving Infrastructure with Canary Deployments",
    "Design a model serving infrastructure that deploys ML models as scalable APIs with support for canary deployments, traffic splitting, auto-scaling, and multi-framework model support.",
    "Serve models as REST/gRPC endpoints",
    "Support canary deployments with gradual rollout",
    "Auto-scale based on request volume and latency",
    "Support multiple ML frameworks (PyTorch, TF, ONNX)",
    "Implement request batching for throughput",
    "Handle model warm-up and pre-loading",
    "Provide request logging and latency monitoring",
    "Support A/B testing between model versions",
    "P99 inference latency under 100ms",
    "Support 50k+ requests per second",
    "Zero-downtime deployments",
    "Scale to zero for cost optimization",
    "Model loading time under 30 seconds",
    "Use KServe, Seldon, or Triton Inference Server",
    "Implement Istio or Envoy for traffic management",
    "Use Kubernetes HPA with custom metrics",
    "Implement model caching with warm standby replicas",
    "Use async prediction pipelines for batch optimization",
    "Implement health checks and readiness probes",
)

EXPECTED_COMPONENT_IDS = {
    "mlops010_api",
    "mlops010_router",
    "mlops010_stable_runtime",
    "mlops010_candidate_runtime",
    "mlops010_registry",
    "mlops010_artifacts",
    "mlops010_orchestrator",
    "mlops010_monitoring",
}
EXPECTED_CONNECTIONS = {
    ("mlops010_api_to_router", "mlops010_api", "mlops010_router"),
    ("mlops010_router_to_stable", "mlops010_router", "mlops010_stable_runtime"),
    ("mlops010_router_to_candidate", "mlops010_router", "mlops010_candidate_runtime"),
    ("mlops010_registry_to_stable", "mlops010_registry", "mlops010_stable_runtime"),
    ("mlops010_registry_to_candidate", "mlops010_registry", "mlops010_candidate_runtime"),
    ("mlops010_artifact_to_stable", "mlops010_artifacts", "mlops010_stable_runtime"),
    ("mlops010_artifact_to_candidate", "mlops010_artifacts", "mlops010_candidate_runtime"),
    ("mlops010_orchestrator_to_stable", "mlops010_orchestrator", "mlops010_stable_runtime"),
    ("mlops010_orchestrator_to_candidate", "mlops010_orchestrator", "mlops010_candidate_runtime"),
    ("mlops010_stable_to_monitoring", "mlops010_stable_runtime", "mlops010_monitoring"),
    ("mlops010_candidate_to_monitoring", "mlops010_candidate_runtime", "mlops010_monitoring"),
    ("mlops010_monitoring_to_orchestrator", "mlops010_monitoring", "mlops010_orchestrator"),
}
CONNECTION_TYPES = {"api-call", "data-flow", "event-stream"}
EXPECTED_REQUIREMENT_IDS = {
    *(f"legacy-requirement:{number}" for number in range(1, 9)),
    *(f"legacy-constraint:{number}" for number in range(1, 6)),
}
APPLIED_ACTION_TYPES = {"add_component", "add_connection", "update_component"}
EXPECTED_ACTION_ANCHORS = {
    "mlops010_api": {"legacy-requirement:1"},
    "mlops010_router": {"legacy-requirement:2", "legacy-requirement:8", "legacy-constraint:3"},
    "mlops010_stable_runtime": {
        "legacy-requirement:4", "legacy-requirement:5", "legacy-requirement:6",
        "legacy-constraint:1", "legacy-constraint:2", "legacy-constraint:5",
    },
    "mlops010_candidate_runtime": {
        "legacy-requirement:2", "legacy-requirement:4", "legacy-requirement:5",
        "legacy-requirement:6", "legacy-requirement:8", "legacy-constraint:2",
        "legacy-constraint:5",
    },
    "mlops010_registry": {
        "legacy-requirement:2", "legacy-requirement:4", "legacy-requirement:6",
        "legacy-requirement:8",
    },
    "mlops010_artifacts": {"legacy-requirement:6", "legacy-constraint:5"},
    "mlops010_orchestrator": {
        "legacy-requirement:2", "legacy-requirement:3", "legacy-requirement:6",
        "legacy-constraint:3", "legacy-constraint:4", "legacy-constraint:5",
    },
    "mlops010_monitoring": {
        "legacy-requirement:3", "legacy-requirement:7", "legacy-requirement:8",
        "legacy-constraint:1",
    },
    "mlops010_api_to_router": {"legacy-requirement:1"},
    "mlops010_router_to_stable": {
        "legacy-requirement:2", "legacy-requirement:8", "legacy-constraint:3",
    },
    "mlops010_router_to_candidate": {
        "legacy-requirement:2", "legacy-requirement:8", "legacy-constraint:3",
    },
    "mlops010_registry_to_stable": {"legacy-requirement:4", "legacy-requirement:6"},
    "mlops010_registry_to_candidate": {
        "legacy-requirement:2", "legacy-requirement:4", "legacy-requirement:8",
    },
    "mlops010_artifact_to_stable": {"legacy-requirement:6", "legacy-constraint:5"},
    "mlops010_artifact_to_candidate": {"legacy-requirement:6", "legacy-constraint:5"},
    "mlops010_orchestrator_to_stable": {
        "legacy-requirement:3", "legacy-requirement:6", "legacy-constraint:3",
        "legacy-constraint:4",
    },
    "mlops010_orchestrator_to_candidate": {
        "legacy-requirement:2", "legacy-requirement:3", "legacy-requirement:6",
        "legacy-constraint:3", "legacy-constraint:4", "legacy-constraint:5",
    },
    "mlops010_stable_to_monitoring": {"legacy-requirement:7", "legacy-constraint:1"},
    "mlops010_candidate_to_monitoring": {
        "legacy-requirement:7", "legacy-requirement:8", "legacy-constraint:1",
    },
    "mlops010_monitoring_to_orchestrator": {
        "legacy-requirement:3", "legacy-requirement:7",
    },
    "mlops010_scale_trigger": {"legacy-requirement:3", "legacy-constraint:4"},
}


def load_guide() -> dict:
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def load_frozen_problem() -> dict:
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def catalog_component_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'(?m)^\s*id:\s*"{re.escape(component_type)}"', catalog)
    assert match, f"unknown component type {component_type!r}"
    end = catalog.find("\n  },", match.start())
    assert end != -1, f"could not find catalog block end for {component_type!r}"
    return catalog[match.start() : end]


def test_draft_matches_the_guided_walkthrough_schema_and_phase_ranges():
    raw = load_guide()
    guide = GuidedWalkthrough.model_validate(raw)

    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.totalSteps == len(guide.steps) == 37
    assert [step.stepNumber for step in guide.steps] == list(range(1, 38))
    assert len({step.id for step in guide.steps}) == guide.totalSteps

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(guide.steps[number - 1].phase == phase.name for number in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1


def test_scope_step_preserves_the_live_frozen_row_verbatim():
    raw = load_guide()
    problem = load_frozen_problem()
    scope = next(step for step in raw["steps"] if step["id"] == "mlops010_scope_snapshot")

    assert "FROZEN PROBLEM ROW (verbatim)" in scope["content"]
    assert "Supplied hints (references, not additional acceptance criteria):" in scope["content"]
    assert f"Title: {problem['title']}" in scope["content"]
    assert f"Description: {problem['description']}" in scope["content"]
    for requirement in problem["requirements"]:
        assert f"- {requirement}" in scope["content"]
    for constraint in problem["constraints"]:
        assert f"- {constraint}" in scope["content"]
    for hint in problem["hints"]:
        assert f"- {hint}" in scope["content"]
    for frozen_text in FROZEN_ROW_TEXT:
        assert frozen_text in scope["content"]


def test_model_quality_canary_health_rollback_and_capacity_are_distinct():
    steps = {step["id"]: step for step in load_guide()["steps"]}

    health = steps["mlops010_canary_review"]
    quality = steps["mlops010_model_quality_evaluation"]
    rollback = steps["mlops010_rollback_policy"]
    capacity = steps["mlops010_latency_and_capacity_acceptance"]

    assert "not whether predictions are correct" in health["content"]
    assert "request outcomes and latency" in health["decision"]["chosen"]
    assert "quality" in quality["content"]
    assert "labels" in quality["content"]
    assert "distinct from autoscaling" in rollback["content"]
    assert "50k+ requests per second" in capacity["content"]
    assert "P99 inference latency under 100ms" in capacity["content"]
    assert "none is specified in the brief" in capacity["content"]

    assert set(health["requirementIds"]) == {
        "legacy-requirement:2", "legacy-requirement:7", "legacy-constraint:1",
    }
    assert quality["requirementIds"] == ["legacy-requirement:8"]
    assert set(rollback["requirementIds"]) == {
        "legacy-requirement:2", "legacy-constraint:3",
    }
    assert set(capacity["requirementIds"]) == {
        "legacy-requirement:3", "legacy-requirement:5", "legacy-requirement:7",
        "legacy-constraint:1", "legacy-constraint:2",
    }


def test_components_use_catalog_types_and_only_supported_properties():
    raw = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = [step["component"] for step in raw["steps"] if step["type"] == "add_component"]

    assert {component["nodeId"] for component in components} == EXPECTED_COMPONENT_IDS
    assert not any(component["componentType"] == "custom-component" for component in components)

    for component in components:
        block = catalog_component_block(catalog, component["componentType"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        properties = set(component["properties"])
        assert {"componentName", "purpose"} <= properties
        assert properties <= supported, (
            f"{component['nodeId']} has unsupported properties: {sorted(properties - supported)}"
        )
        assert component["label"].strip()
        assert component["description"].strip()
        assert component["highlightReason"].strip()


def test_applied_actions_cover_the_frozen_scope_and_replay_a_connected_graph():
    raw = load_guide()
    steps_by_id = {step["id"]: step for step in raw["steps"]}
    assert {
        step_id: set(steps_by_id[step_id]["requirementIds"])
        for step_id in EXPECTED_ACTION_ANCHORS
    } == EXPECTED_ACTION_ANCHORS

    connections = [
        (step["connection"]["edgeId"], step["connection"]["sourceNodeId"], step["connection"]["targetNodeId"])
        for step in raw["steps"]
        if step["type"] == "add_connection"
    ]
    assert set(connections) == EXPECTED_CONNECTIONS

    nodes_seen = set()
    edges_seen = set()
    for step in raw["steps"]:
        if step["type"] == "add_component":
            node_id = step["component"]["nodeId"]
            assert node_id not in nodes_seen
            nodes_seen.add(node_id)
        elif step["type"] == "add_connection":
            edge = step["connection"]
            assert edge["sourceNodeId"] in nodes_seen
            assert edge["targetNodeId"] in nodes_seen
            assert edge["sourceNodeId"] != edge["targetNodeId"]
            assert edge["edgeId"] not in edges_seen
            assert edge["connectionType"] in CONNECTION_TYPES
            edges_seen.add(edge["edgeId"])

    anchors = {anchor for step in raw["steps"] for anchor in step["requirementIds"]}
    assert anchors == EXPECTED_REQUIREMENT_IDS
    for anchor in EXPECTED_REQUIREMENT_IDS:
        assert any(
            step["type"] in APPLIED_ACTION_TYPES and anchor in step["requirementIds"]
            for step in raw["steps"]
        ), f"{anchor} has no applied graph action"

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    replay_nodes = {component["id"] for component in architecture["components"]}
    assert replay_nodes == EXPECTED_COMPONENT_IDS
    assert len(architecture["connections"]) == len(EXPECTED_CONNECTIONS)
    assert all(
        edge["source"] in replay_nodes and edge["target"] in replay_nodes
        for edge in architecture["connections"]
    )
    assert all(edge["type"] in CONNECTION_TYPES for edge in architecture["connections"])
