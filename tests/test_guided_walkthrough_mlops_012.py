"""Focused checks for the GPU cluster management walkthrough candidate."""

import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / "mlops_012.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = (
    "Design a GPU Cluster Management System for ML Training",
    "Design a GPU cluster management system that handles job scheduling, resource allocation, multi-tenancy, preemption, and cost optimization for ML training workloads.",
    "Schedule training jobs across GPU nodes",
    "Implement fair-share resource allocation",
    "Support job preemption and priority queues",
    "Handle multi-tenancy with resource quotas",
    "Track GPU utilization and idle resources",
    "Implement gang scheduling for distributed training",
    "Support spot/preemptible instance integration",
    "Provide cost allocation and chargeback reports",
    "GPU utilization above 80% cluster-wide",
    "Job scheduling latency under 30 seconds",
    "Support 1000+ GPUs across multiple node types",
    "Handle heterogeneous GPU hardware (A100, H100, etc.)",
    "Fair resource allocation across 50+ teams",
    "Use Kubernetes with GPU operator for orchestration",
    "Implement Volcano or Kueue for batch scheduling",
    "Use topology-aware scheduling for NVLink/NVSwitch",
    "Implement bin-packing for efficient resource utilization",
    "Use autoscaler with cloud provider GPU pools",
    "Implement job-level monitoring with GPU metrics",
)
REQUIREMENT_IDS = {f"legacy-requirement:{number}" for number in range(1, 9)}
CONSTRAINT_IDS = {f"legacy-constraint:{number}" for number in range(1, 6)}
ACTION_TYPES = {"add_component", "add_connection", "update_component"}
CONNECTION_TYPES = {"api-call", "data-flow", "event-stream"}
EXPECTED_COMPONENT_IDS = {
    "mlops012_gateway",
    "mlops012_identity",
    "mlops012_queue",
    "mlops012_scheduler",
    "mlops012_a100_pool",
    "mlops012_h100_pool",
    "mlops012_job_state",
    "mlops012_checkpoint_store",
    "mlops012_monitoring",
    "mlops012_chargeback",
}
EXPECTED_EDGE_IDS = {
    "mlops012_gateway_identity",
    "mlops012_gateway_queue",
    "mlops012_gateway_job_state",
    "mlops012_identity_scheduler",
    "mlops012_queue_scheduler",
    "mlops012_state_scheduler",
    "mlops012_scheduler_a100",
    "mlops012_scheduler_h100",
    "mlops012_a100_scheduler_events",
    "mlops012_h100_scheduler_events",
    "mlops012_a100_checkpoint_store",
    "mlops012_h100_checkpoint_store",
    "mlops012_checkpoint_scheduler",
    "mlops012_scheduler_queue_requeue",
    "mlops012_a100_metrics",
    "mlops012_h100_metrics",
    "mlops012_scheduler_metrics",
    "mlops012_queue_metrics",
    "mlops012_metrics_chargeback",
    "mlops012_chargeback_state",
}


def load_guide() -> dict:
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def catalog_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'(?m)^\s*id:\s*"{re.escape(component_type)}"', catalog)
    assert match, f"unknown catalog component type {component_type!r}"
    end = catalog.find("\n  },", match.start())
    assert end != -1, f"could not find catalog block end for {component_type!r}"
    return catalog[match.start() : end]


def test_schema_version_step_numbering_and_phase_ranges_are_valid():
    raw = load_guide()
    guide = GuidedWalkthrough.model_validate(raw)

    assert guide.problem_id == "mlops_012"
    assert guide.version == "1.0"
    assert guide.totalSteps == len(guide.steps) == 42
    assert [step.stepNumber for step in guide.steps] == list(range(1, 43))
    assert len({step.id for step in guide.steps}) == guide.totalSteps

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(guide.steps[number - 1].phase == phase.name for number in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    serialized = json.dumps(raw).lower()
    assert "has_guided_walkthrough" not in serialized
    assert "unpublished" not in serialized
    assert "local draft" not in serialized


def test_scope_snapshot_preserves_the_exact_live_brief_and_hints():
    raw = load_guide()
    scope = next(step for step in raw["steps"] if step["id"] == "mlops012_scope_snapshot")

    assert "PROBLEM BRIEF" in scope["content"]
    assert "Requirements:" in scope["content"]
    assert "Constraints:" in scope["content"]
    assert "Supplied hints (implementation suggestions, not additional requirements):" in scope["content"]
    for exact_text in FROZEN_BRIEF:
        assert exact_text in scope["content"]


def test_components_and_updates_use_existing_catalog_properties():
    raw = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step["type"] == "add_component"
    }

    assert set(components) == EXPECTED_COMPONENT_IDS
    assert len({component["componentType"] for component in components.values()}) == 9
    assert all(component["componentType"] != "custom-component" for component in components.values())

    for step in raw["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            properties = component["properties"]
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            component = components[update["nodeId"]]
            properties = update["properties"]
        else:
            continue

        block = catalog_block(catalog, component["componentType"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert set(properties) <= supported, (
            f"{step['id']} uses unsupported properties: {sorted(set(properties) - supported)}"
        )
        if step["type"] == "add_component":
            assert {"componentName", "purpose"} <= set(properties)
            assert component["label"].strip()
            assert component["description"].strip()
            assert component["highlightReason"].strip()

    gpu_types = {
        component["properties"]["gpuType"]
        for component in components.values()
        if component["componentType"] == "gpu-cluster"
    }
    assert gpu_types == {"NVIDIA A100", "NVIDIA H100"}
    gpu_catalog = catalog_block(catalog, "gpu-cluster")
    for gpu_type in gpu_types:
        assert f'"{gpu_type}"' in gpu_catalog


def test_every_requirement_and_constraint_is_anchored_to_a_replayable_graph_action():
    raw = load_guide()
    anchors = {
        anchor
        for step in raw["steps"]
        if step["type"] in ACTION_TYPES
        for anchor in step["requirementIds"]
    }

    assert anchors == REQUIREMENT_IDS | CONSTRAINT_IDS
    for anchor in REQUIREMENT_IDS | CONSTRAINT_IDS:
        assert any(
            step["type"] in ACTION_TYPES and anchor in step["requirementIds"]
            for step in raw["steps"]
        ), f"{anchor} has no accepted graph action"


def test_actions_replay_to_the_expected_connected_architecture():
    raw = load_guide()
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {component["id"] for component in architecture["components"]}
    edges = architecture["connections"]

    assert nodes == EXPECTED_COMPONENT_IDS
    assert {edge["id"] for edge in edges} == EXPECTED_EDGE_IDS
    assert len(edges) == len(EXPECTED_EDGE_IDS)
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in edges)
    assert all(edge["type"] in CONNECTION_TYPES for edge in edges)

    adjacency = {node_id: set() for node_id in nodes}
    for edge in edges:
        adjacency[edge["source"]].add(edge["target"])
        adjacency[edge["target"]].add(edge["source"])
    visited = set()
    pending = [next(iter(nodes))]
    while pending:
        node_id = pending.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        pending.extend(adjacency[node_id] - visited)
    assert visited == nodes

    replayed_nodes = {component["id"]: component for component in architecture["components"]}
    assert "80%" in replayed_nodes["mlops012_monitoring"]["properties"]["purpose"]
    assert "under 30 seconds" in replayed_nodes["mlops012_scheduler"]["properties"]["purpose"]
    assert "1,000+ GPUs" in replayed_nodes["mlops012_h100_pool"]["properties"]["purpose"]
    assert "50+ teams" in replayed_nodes["mlops012_scheduler"]["properties"]["purpose"]
