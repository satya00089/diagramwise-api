"""Frozen-brief, catalog, and graph checks for the AWS microservices draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_aws_008"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
FROZEN_PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

STEP_TYPES = {"explanation", "add_component", "add_connection", "decision_point", "scale_trigger"}
CONNECTION_TYPES = {"api-call", "data-flow", "event-stream", "http", "tcp", "websocket"}
EXPECTED_COMPONENT_TYPES = {
    "aws008_clients": "web-app",
    "aws008_alb": "loadbalancer",
    "aws008_images": "docker",
    "aws008_runtime": "container-orchestrator",
    "aws008_services": "backend-server",
    "aws008_mesh": "service-mesh",
    "aws008_logs": "log-processing",
    "aws008_monitoring": "monitoring",
    "aws008_tracing": "tracing",
}
EXPECTED_ANCHORS = {
    *(f"legacy-requirement:{index}" for index in range(1, 9)),
    *(f"legacy-constraint:{index}" for index in range(1, 6)),
}
EXPECTED_STEP_ANCHORS = {
    "aws008_brief": set(),
    "aws008_load_shape": {"legacy-constraint:1", "legacy-constraint:2"},
    "aws008_runtime_choice": {"legacy-requirement:1", "legacy-requirement:3", "legacy-constraint:1"},
    "aws008_open_inputs": set(),
    "aws008_client": set(),
    "aws008_alb": {"legacy-requirement:2", "legacy-requirement:4"},
    "aws008_client_alb": {"legacy-requirement:2"},
    "aws008_edge_questions": {"legacy-requirement:2", "legacy-requirement:4"},
    "aws008_docker_ecr": {"legacy-requirement:5"},
    "aws008_orchestrator": {"legacy-requirement:1", "legacy-requirement:3"},
    "aws008_service_fleet": {"legacy-requirement:1"},
    "aws008_registry_pull": {"legacy-requirement:1", "legacy-requirement:5"},
    "aws008_runtime_deploys": {"legacy-requirement:1", "legacy-requirement:3"},
    "aws008_service_autoscaling": {"legacy-requirement:3"},
    "aws008_mesh": {
        "legacy-requirement:2", "legacy-requirement:6", "legacy-requirement:7",
        "legacy-requirement:8", "legacy-constraint:5",
    },
    "aws008_app_mesh_lifecycle": set(),
    "aws008_discovery": {"legacy-requirement:2"},
    "aws008_service_mesh_request": {"legacy-requirement:6"},
    "aws008_mesh_routing": {"legacy-requirement:2", "legacy-requirement:6"},
    "aws008_alb_services": {"legacy-requirement:2", "legacy-requirement:4"},
    "aws008_health_checks": {"legacy-requirement:4", "legacy-constraint:3"},
    "aws008_health_feedback": {"legacy-requirement:4", "legacy-constraint:3"},
    "aws008_mtls": {"legacy-requirement:6", "legacy-constraint:4", "legacy-constraint:5"},
    "aws008_circuit_breakers": {"legacy-requirement:6", "legacy-requirement:8"},
    "aws008_rollout_target": {"legacy-requirement:4", "legacy-constraint:3"},
    "aws008_approval_policy": {"legacy-constraint:3"},
    "aws008_logs": set(),
    "aws008_monitoring": {"legacy-requirement:3", "legacy-requirement:4"},
    "aws008_tracing": {"legacy-requirement:6", "legacy-requirement:7"},
    "aws008_services_to_logs": {"legacy-constraint:4"},
    "aws008_logs_to_monitoring": set(),
    "aws008_runtime_to_monitoring": {"legacy-requirement:3", "legacy-requirement:4"},
    "aws008_services_to_tracing": {"legacy-requirement:6", "legacy-requirement:7"},
    "aws008_mesh_to_tracing": {"legacy-requirement:6", "legacy-requirement:7", "legacy-requirement:8"},
    "aws008_scale_test": {"legacy-requirement:3", "legacy-requirement:4", "legacy-constraint:2"},
    "aws008_scale_services": {
        "legacy-requirement:1", "legacy-requirement:2", "legacy-requirement:3",
        "legacy-requirement:7", "legacy-constraint:1",
    },
}


def _load() -> tuple[dict, GuidedWalkthrough]:
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def _frozen_brief() -> dict:
    problems = json.loads(FROZEN_PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def _catalog_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'(?m)^    id:\s*"{re.escape(component_type)}"\s*,', catalog)
    assert match is not None, f"Unknown component catalog ID {component_type!r}"
    following = re.search(r"(?m)^  \},\s*$", catalog[match.end() :])
    assert following is not None, f"Could not delimit component catalog ID {component_type!r}"
    return catalog[match.start() : match.end() + following.start()]


def test_draft_preserves_the_frozen_problem_brief_and_availability_flag():
    raw, guide = _load()
    brief = _frozen_brief()
    assert raw["problem_id"] == guide.problem_id == brief["id"]
    assert raw["version"] == "1.0-review-draft"
    assert brief["has_guided_walkthrough"] is False
    intro = guide.steps[0].content
    for field in ("title", "slug", "description", "difficulty", "category", "domain", "estimated_time"):
        assert brief[field] in intro
    for field in ("requirements", "constraints", "hints", "tags", "companies"):
        assert all(value in intro for value in brief[field]), field
    assert "has_guided_walkthrough=false" in intro
    assert "local review draft" in intro
    assert guide.requirementRevision is None


def test_each_step_uses_only_its_direct_frozen_requirement_and_constraint_anchors():
    _, guide = _load()
    all_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    brief = _frozen_brief()
    expected_anchors = {
        *(f"legacy-requirement:{index}" for index in range(1, len(brief["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(brief["constraints"]) + 1)),
    }
    actual_step_anchors = {step.id: set(step.requirementIds) for step in guide.steps}
    assert actual_step_anchors == EXPECTED_STEP_ANCHORS
    assert all_anchors == expected_anchors == EXPECTED_ANCHORS

    graph_requirement_anchors = {
        anchor
        for step in guide.steps
        if step.type in {"add_component", "add_connection"}
        for anchor in step.requirementIds
        if anchor.startswith("legacy-requirement:")
    }
    assert graph_requirement_anchors == {
        f"legacy-requirement:{index}" for index in range(1, len(brief["requirements"]) + 1)
    }


def test_unspecified_traffic_shape_and_numeric_slos_are_explicit():
    _, guide = _load()
    by_id = {step.id: step for step in guide.steps}
    load_shape = by_id["aws008_load_shape"].content.casefold()
    for unknown in (
        "peak or sustained", "burst profile", "payload size", "request mix", "fan-out",
        "read/write mix", "arrival rate per service",
    ):
        assert unknown in load_shape

    open_inputs = by_id["aws008_open_inputs"].content.casefold()
    for unspecified in (
        "no numeric availability", "uptime objective", "latency target", "error-rate budget",
        "recovery-time objective (rto)", "recovery-point objective (rpo)", "not an availability slo",
    ):
        assert unspecified in open_inputs


def test_scaling_and_reliability_targets_are_not_presented_as_implementation_guarantees():
    _, guide = _load()
    by_id = {step.id: step for step in guide.steps}
    assert "replaceable walkthrough candidate" in by_id["aws008_runtime_choice"].decision.chosen.casefold()
    assert "not evidence that 100+ services or 50k requests per second are supported" in by_id[
        "aws008_orchestrator"
    ].content
    assert "candidate signals, not a selected policy" in by_id["aws008_service_autoscaling"].content
    assert "does not establish 100+ service capacity or zero-downtime rollout behavior" in by_id[
        "aws008_runtime_deploys"
    ].content
    assert "not a numeric availability slo or a zero-downtime guarantee" in by_id[
        "aws008_health_checks"
    ].content.casefold()
    assert "implementation options, not guarantees" in by_id["aws008_rollout_target"].content
    assert "prove 100+ service capacity" in by_id["aws008_runtime_to_monitoring"].content
    assert "does not supply an unstated latency, availability, or error-rate slo" in by_id[
        "aws008_scale_test"
    ].content.casefold()


def test_mesh_connections_represent_distinct_service_boundaries_not_a_self_call():
    _, guide = _load()
    by_id = {step.id: step for step in guide.steps}
    source = by_id["aws008_service_mesh_request"].content.casefold()
    destination = by_id["aws008_mesh_routing"].content.casefold()
    assert "distinct source and destination services" in source
    assert "not a claim that one service calls itself or that the mesh is a centralized network hop" in source
    assert "distinct destination service's proxy" in destination
    assert "not a self-call" in destination


def test_steps_phases_and_replayed_graph_are_ordered_valid_and_connected():
    raw, guide = _load()
    assert guide.totalSteps == len(guide.steps) == 36
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES for step in guide.steps)

    seen_nodes: set[str] = set()
    seen_edges: set[str] = set()
    for step in guide.steps:
        if step.type == "add_component":
            assert step.component is not None
            assert step.component.nodeId not in seen_nodes
            seen_nodes.add(step.component.nodeId)
        elif step.type == "add_connection":
            assert step.connection is not None
            edge = step.connection
            assert edge.edgeId not in seen_edges
            assert edge.sourceNodeId in seen_nodes
            assert edge.targetNodeId in seen_nodes
            assert edge.connectionType in CONNECTION_TYPES
            seen_edges.add(edge.edgeId)
        elif step.type == "decision_point":
            assert step.decision is not None and step.decision.question and step.decision.chosen
        elif step.type == "scale_trigger":
            assert step.scaleTrigger is not None
            assert all(getattr(step.scaleTrigger, field) for field in ("metric", "action", "impact"))

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {component["id"] for component in architecture["components"]}
    edges = architecture["connections"]
    assert nodes == set(EXPECTED_COMPONENT_TYPES)
    assert len(edges) == len(seen_edges) == 12
    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached: set[str] = set()
    pending = deque([next(iter(nodes))])
    while pending:
        current = pending.popleft()
        if current in reached:
            continue
        reached.add(current)
        pending.extend(neighbors[current] - reached)
    assert reached == nodes
    assert len(replay["appliedStepIds"]) > len(replay["explanationOnlyStepIds"])


def test_only_existing_catalog_components_and_supported_properties_are_used():
    raw, _ = _load()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step.get("component") is not None
    }
    assert {node_id: component["componentType"] for node_id, component in additions.items()} == EXPECTED_COMPONENT_TYPES

    for node_id, component in additions.items():
        block = _catalog_block(catalog, component["componentType"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        properties = set(component.get("properties", {}))
        assert {"componentName", "purpose"} <= properties, node_id
        assert properties <= supported, f"{node_id} has unsupported properties: {sorted(properties - supported)}"

    assert additions["aws008_images"]["properties"]["registry"] == "AWS ECR"
    assert additions["aws008_runtime"]["properties"]["platform"] == "Kubernetes"
    assert additions["aws008_mesh"]["properties"]["provider"] == "Istio"
    assert additions["aws008_mesh"]["properties"]["mtls"] is True
    assert additions["aws008_mesh"]["properties"]["circuitBreaker"] is True
    assert additions["aws008_tracing"]["properties"]["platform"] == "AWS X-Ray"


def test_open_operational_decisions_and_app_mesh_lifecycle_are_not_hidden():
    raw, _ = _load()
    text = json.dumps(raw, ensure_ascii=False).casefold()
    for open_question in ("availability", "topology", "retention", "slo", "approval policy"):
        assert open_question in text
    assert "support was discontinued on september 30, 2026" in text
    assert "does not configure app mesh" in text
    assert "app-mesh/latest/userguide/meshes.html" in text
    assert "replica count" in text

    additions = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step.get("component") is not None
    }
    assert "instances" not in additions["aws008_services"]["properties"]
    assert "retention" not in additions["aws008_monitoring"]["properties"]
    assert "retentionDays" not in additions["aws008_logs"]["properties"]
    assert "retention" not in additions["aws008_tracing"]["properties"]
