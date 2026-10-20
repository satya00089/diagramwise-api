"""Frozen-brief, catalog-action, and architecture checks for mlops_006."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "mlops_006"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / "mlops_006.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
CONNECTION_TYPES = {
    "api-call",
    "data-flow",
    "database-connection",
    "event-stream",
    "message-queue",
}
FROZEN_BRIEF = {
    "id": "mlops_006",
    "title": "Design a Distributed Model Training Platform",
    "slug": "design-a-distributed-model-training-platform",
    "description": "Design a platform that enables distributed training of large ML models across multiple GPUs and nodes, handles data parallelism and model parallelism, and optimizes training throughput and cost.",
    "difficulty": "Very Hard",
    "category": "MLOps - Distributed Training",
    "domain": "aiml",
    "estimated_time": "90+ minutes",
    "has_guided_walkthrough": False,
    "requirements": [
        "Support data-parallel and model-parallel training",
        "Manage multi-node GPU clusters dynamically",
        "Handle gradient synchronization across nodes",
        "Implement checkpointing and fault tolerance",
        "Optimize data loading to avoid GPU starvation",
        "Support mixed-precision training",
        "Track training metrics and resource utilization",
        "Manage training job queues and priorities",
    ],
    "constraints": [
        "Linear scaling efficiency above 80%",
        "Support training on 100+ GPUs",
        "Recover from node failures within 5 minutes",
        "GPU utilization above 85% during training",
        "Support models up to 100B+ parameters",
    ],
    "hints": [
        "Use PyTorch FSDP or DeepSpeed for distributed training",
        "Implement ZeRO optimization for memory efficiency",
        "Use NCCL for high-performance GPU communication",
        "Implement elastic training for dynamic cluster resizing",
        "Use gradient compression for bandwidth optimization",
        "Implement async checkpointing to avoid training pauses",
    ],
    "tags": [
        "mlops",
        "distributed-training",
        "gpu-cluster",
        "deep-learning",
        "data-parallelism",
        "model-parallelism",
    ],
    "companies": ["Meta", "Google", "NVIDIA", "Microsoft"],
}


EXPECTED_STEP_ANCHORS = {
    "mlops006_frozen_scope": set(),
    "mlops006_unknown_workload": {"legacy-constraint:1", "legacy-constraint:2", "legacy-constraint:3", "legacy-constraint:4", "legacy-constraint:5"},
    "mlops006_parallelism_choice": {"legacy-requirement:1", "legacy-constraint:5"},
    "mlops006_training_api": {"legacy-requirement:8"},
    "mlops006_priority_queue": {"legacy-requirement:8"},
    "mlops006_cluster_scheduler": {"legacy-requirement:2", "legacy-requirement:8", "legacy-constraint:2"},
    "mlops006_run_state": {"legacy-requirement:4", "legacy-requirement:8", "legacy-constraint:3"},
    "mlops006_gpu_fleet": {"legacy-requirement:2", "legacy-constraint:2"},
    "mlops006_dataset_store": {"legacy-requirement:5"},
    "mlops006_input_pipeline": {"legacy-requirement:5", "legacy-constraint:4"},
    "mlops006_training_runtime": {"legacy-requirement:1", "legacy-requirement:3", "legacy-requirement:6", "legacy-requirement:7", "legacy-constraint:1", "legacy-constraint:5"},
    "mlops006_checkpoint_store": {"legacy-requirement:4", "legacy-constraint:3"},
    "mlops006_observability": {"legacy-requirement:7", "legacy-constraint:1", "legacy-constraint:3", "legacy-constraint:4"},
    "mlops006_edge_api_queue": {"legacy-requirement:8"},
    "mlops006_edge_api_state": {"legacy-requirement:8"},
    "mlops006_edge_queue_scheduler": {"legacy-requirement:8"},
    "mlops006_edge_state_scheduler": {"legacy-requirement:2", "legacy-requirement:4", "legacy-constraint:3"},
    "mlops006_edge_scheduler_gpu": {"legacy-requirement:2", "legacy-constraint:2"},
    "mlops006_edge_scheduler_input": {"legacy-requirement:2", "legacy-requirement:5"},
    "mlops006_edge_dataset_input": {"legacy-requirement:5"},
    "mlops006_edge_input_training": {"legacy-requirement:1", "legacy-requirement:5", "legacy-constraint:4"},
    "mlops006_edge_gpu_training": {"legacy-requirement:1", "legacy-requirement:3", "legacy-constraint:2"},
    "mlops006_edge_state_runtime": {"legacy-requirement:1", "legacy-requirement:4", "legacy-requirement:6"},
    "mlops006_edge_runtime_checkpoint": {"legacy-requirement:4", "legacy-constraint:3"},
    "mlops006_edge_runtime_state": {"legacy-requirement:4"},
    "mlops006_edge_checkpoint_runtime": {"legacy-requirement:4", "legacy-constraint:3"},
    "mlops006_edge_runtime_metrics": {"legacy-requirement:7", "legacy-constraint:1", "legacy-constraint:4"},
    "mlops006_edge_gpu_metrics": {"legacy-requirement:7", "legacy-constraint:4"},
    "mlops006_edge_scheduler_metrics": {"legacy-requirement:2", "legacy-requirement:7"},
    "mlops006_edge_queue_metrics": {"legacy-requirement:8", "legacy-requirement:7"},
    "mlops006_priority_policy": {"legacy-requirement:8"},
    "mlops006_gpu_capacity_check": {"legacy-requirement:2", "legacy-constraint:2"},
    "mlops006_collective_decision": {"legacy-requirement:3", "legacy-constraint:1", "legacy-constraint:2"},
    "mlops006_input_throughput_check": {"legacy-requirement:5", "legacy-requirement:7", "legacy-constraint:4"},
    "mlops006_mixed_precision_decision": {"legacy-requirement:6"},
    "mlops006_checkpoint_policy": {"legacy-requirement:4", "legacy-constraint:3"},
    "mlops006_recovery_check": {"legacy-requirement:4", "legacy-constraint:3"},
    "mlops006_scaling_efficiency_check": {"legacy-requirement:1", "legacy-requirement:3", "legacy-constraint:1"},
    "mlops006_model_size_check": {"legacy-requirement:1", "legacy-requirement:4", "legacy-constraint:5"},
    "mlops006_elastic_cost_decision": {"legacy-requirement:2", "legacy-requirement:8", "legacy-constraint:2", "legacy-constraint:4"},
    "mlops006_local_review_conclusion": set(),
}


def load_problem() -> dict:
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def load_guide() -> dict:
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def expected_anchors() -> set[str]:
    return {
        *(f"legacy-requirement:{number}" for number in range(1, len(FROZEN_BRIEF["requirements"]) + 1)),
        *(f"legacy-constraint:{number}" for number in range(1, len(FROZEN_BRIEF["constraints"]) + 1)),
    }


def catalog_component_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'(?m)^\s*id:\s*"{re.escape(component_type)}"', catalog)
    assert match, f"unknown component type {component_type!r}"
    end = catalog.find("\n  },", match.start())
    assert end != -1, f"could not find catalog block end for {component_type!r}"
    return catalog[match.start() : end]


def test_frozen_snapshot_and_exact_brief_content_are_preserved():
    problem = load_problem()
    raw = load_guide()
    text = json.dumps(raw, ensure_ascii=False).casefold()

    assert problem == FROZEN_BRIEF
    assert raw["problem_id"] == PROBLEM_ID
    assert raw["version"].endswith("review-draft")
    assert raw["totalSteps"] == len(raw["steps"])
    assert FROZEN_BRIEF["title"].casefold() in text
    assert FROZEN_BRIEF["description"].casefold() in text
    for field in ("requirements", "constraints", "hints"):
        for statement in FROZEN_BRIEF[field]:
            assert statement.casefold() in text, f"frozen {field} statement missing: {statement}"
    assert problem["has_guided_walkthrough"] is False


def test_schema_order_phases_and_exact_requirement_constraint_action_coverage():
    raw = load_guide()
    guide = GuidedWalkthrough.model_validate(raw)

    assert guide.problem_id == PROBLEM_ID
    assert guide.version.endswith("review-draft")
    assert guide.totalSteps == len(guide.steps) == 41
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(
        step.type
        in {
            "explanation",
            "add_component",
            "add_connection",
            "decision_point",
            "scale_trigger",
            "conclusion",
        }
        for step in guide.steps
    )

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(guide.steps[number - 1].phase == phase.name for number in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    expected = expected_anchors()
    actual = {anchor for step in raw["steps"] for anchor in step["requirementIds"]}
    assert actual == expected
    graph_actions = {"add_component", "add_connection", "update_component"}
    for anchor in expected:
        assert any(
            step["type"] in graph_actions and anchor in step["requirementIds"]
            for step in raw["steps"]
        ), f"{anchor} appears only on prose/decision steps, not an applied graph action"


def test_requirement_and_constraint_anchors_match_each_specific_step():
    raw = load_guide()
    actual = {step["id"]: set(step["requirementIds"]) for step in raw["steps"]}
    assert actual == EXPECTED_STEP_ANCHORS


def test_components_and_action_targets_use_supported_catalog_types_and_properties():
    raw = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = [step["component"] for step in raw["steps"] if step["type"] == "add_component"]
    assert len(additions) == 10
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

    components = {component["nodeId"]: component for component in additions}
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
        elif step["type"] == "update_component":
            update = step["componentUpdate"]
            assert update["nodeId"] in components
            assert update["properties"]


def test_ordered_replay_has_valid_edges_and_one_connected_architecture():
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


def test_training_fault_tolerance_and_throughput_decisions_are_explicit():
    raw = load_guide()
    text = json.dumps(raw, ensure_ascii=False).casefold()
    decisions = {step["id"]: step["decision"] for step in raw["steps"] if step["type"] == "decision_point"}
    triggers = {step["id"]: step["scaleTrigger"] for step in raw["steps"] if step["type"] == "scale_trigger"}

    for step_id in (
        "mlops006_parallelism_choice",
        "mlops006_collective_decision",
        "mlops006_mixed_precision_decision",
        "mlops006_checkpoint_policy",
        "mlops006_priority_policy",
        "mlops006_elastic_cost_decision",
    ):
        assert decisions[step_id]["chosen"].strip()
        assert decisions[step_id]["chosenReason"].strip()
        assert decisions[step_id]["alternatives"]

    assert "tensor or pipeline parallelism" in text
    assert "fsdp" in text and "deepspeed" in text and "zero" in text
    assert "nccl" in text and "gradient" in text and "synchron" in text
    assert "mixed-precision" in text and "precision-scaler" in text
    assert "all-rank checkpoint manifest" in text
    assert "only a complete manifest" in text
    assert "input wait" in text and "collective duration" in text

    expected_triggers = {
        "mlops006_gpu_capacity_check": "100+ gpus",
        "mlops006_input_throughput_check": "above-85%",
        "mlops006_recovery_check": "within five minutes",
        "mlops006_scaling_efficiency_check": "above-80%",
        "mlops006_model_size_check": "100b+",
    }
    for step_id, phrase in expected_triggers.items():
        assert phrase in triggers[step_id]["metric"].casefold()
        assert triggers[step_id]["action"].strip()
        assert triggers[step_id]["impact"].strip()

    assert "does not claim this target is achieved" in text
    assert "browser persistence, ai assessment, and publication gates" in text
    assert "have not been run or passed" in text


def test_unspecified_hardware_throughput_and_quality_targets_are_assumptions():
    raw = load_guide()
    steps = {step["id"]: step for step in raw["steps"]}

    workload = steps["mlops006_unknown_workload"]["content"].casefold()
    assert "assumption" in workload
    assert "gpu sku or memory" in workload
    assert "interconnect bandwidth" in workload
    assert "storage/input throughput" in workload
    assert "end-to-end throughput target" in workload
    assert "availability slo" in workload
    assert "model-quality metric" in workload

    fleet = steps["mlops006_gpu_fleet"]["content"].casefold()
    assert "assumption" in fleet
    assert "gpu sku and memory" in fleet
    assert "interconnect" in fleet


def test_scheduling_capacity_utilization_and_training_quality_are_separate():
    steps = {step["id"]: step for step in load_guide()["steps"]}
    placement = steps["mlops006_edge_scheduler_gpu"]["content"].casefold()
    fleet_gate = steps["mlops006_gpu_capacity_check"]["content"].casefold()
    utilization_gate = steps["mlops006_input_throughput_check"]["content"].casefold()
    size_gate = steps["mlops006_model_size_check"]["content"].casefold()
    scaling_gate = steps["mlops006_scaling_efficiency_check"]["content"].casefold()

    assert "scheduling and worker-capacity action only" in placement
    assert "does not prove model convergence or acceptable model quality" in fleet_gate
    assert "not proof of useful throughput, convergence, or model quality" in utilization_gate
    assert "does not establish convergence or final model quality" in size_gate
    assert "does not by itself show faster convergence or better model quality" in scaling_gate
