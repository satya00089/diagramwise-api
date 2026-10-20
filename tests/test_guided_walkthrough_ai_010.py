"""Focused frozen-brief, catalog, and replay checks for the ai_010 review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "ai_010"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

TITLE = "Design an Autonomous Vehicle Perception System"
SLUG = "design-an-autonomous-vehicle-perception-system"
DESCRIPTION = (
    "Design the perception stack for an autonomous vehicle that fuses data from "
    "cameras, LiDAR, and radar sensors, detects objects in 3D space, and tracks "
    "their movement in real-time."
)
REQUIREMENTS = [
    "Process multi-camera feeds in real-time",
    "Process LiDAR point clouds for 3D detection",
    "Fuse sensor data for unified world model",
    "Detect and classify objects (vehicles, pedestrians, signs)",
    "Track object trajectories over time",
    "Estimate depth and distance accurately",
    "Handle adverse weather and lighting conditions",
    "Predict object motion for path planning",
]
CONSTRAINTS = [
    "End-to-end perception latency under 100ms",
    "Object detection accuracy (mAP) above 90%",
    "Process 30+ frames per second",
    "Operate on edge hardware (automotive-grade GPUs)",
    "Handle 360-degree surround perception",
]
HINTS = [
    "Use BEV (Bird's Eye View) representations for fusion",
    "Implement PointPillars or CenterPoint for LiDAR detection",
    "Use temporal fusion for multi-frame tracking",
    "Deploy with TensorRT optimization for edge inference",
    "Implement data-parallel training on multi-GPU clusters",
    "Use synthetic data generation for training augmentation",
]
COMPANIES = ["Waymo", "Tesla", "Cruise", "NVIDIA"]
ANCHORS = {
    *(f"legacy-requirement:{number}" for number in range(1, 9)),
    *(f"legacy-constraint:{number}" for number in range(1, 6)),
}
ACTION_TYPES = {"add_component", "add_connection"}
CONNECTION_TYPES = {"api-call", "data-flow"}


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


def test_live_snapshot_fidelity_and_walkthrough_schema():
    raw, problem = load_guide_and_problem()
    guide = GuidedWalkthrough.model_validate(raw)

    assert problem["id"] == PROBLEM_ID
    assert problem["slug"] == SLUG
    assert problem["title"] == TITLE
    assert problem["description"] == DESCRIPTION
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert problem["hints"] == HINTS
    assert problem["companies"] == COMPANIES
    assert problem["has_guided_walkthrough"] is False

    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 21
    assert "has_guided_walkthrough" not in raw

    opening = guide.steps[0].content
    for supplied_fact in [TITLE, SLUG, DESCRIPTION, *REQUIREMENTS, *CONSTRAINTS, *HINTS, *COMPANIES]:
        assert supplied_fact in opening


def test_phases_and_every_brief_anchor_are_actionable():
    raw, _ = load_guide_and_problem()
    guide = GuidedWalkthrough.model_validate(raw)

    assert [step.stepNumber for step in guide.steps] == list(range(1, 22))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.id and step.title and step.content for step in guide.steps)

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert len(phase.stepRange) == 2
        assert start == next_step
        assert start <= end <= guide.totalSteps
        assert all(step.phase == phase.name for step in guide.steps[start - 1 : end])
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    mapped = {anchor for step in guide.steps for anchor in step.requirementIds}
    action_mapped = {
        anchor
        for step in guide.steps
        if step.type in ACTION_TYPES
        for anchor in step.requirementIds
    }
    assert mapped == action_mapped == ANCHORS
    assert all(set(step.requirementIds) <= ANCHORS for step in guide.steps)


def test_components_use_palette_schema_and_custom_only_for_sensor_gap():
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

        block = catalog_block(catalog, component["componentType"], step["id"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert set(component["properties"]) <= supported, (
            f"{step['id']}: unsupported properties "
            f"{sorted(set(component['properties']) - supported)}"
        )
        components[component["nodeId"]] = component

    assert {component["componentType"] for component in components.values()} == {
        "custom-component",
        "processing-worker",
        "edge-server",
        "model-serving",
        "ml-model",
        "backend-server",
        "model-training",
    }
    custom = [
        component
        for component in components.values()
        if component["componentType"] == "custom-component"
    ]
    assert len(custom) == 1
    assert custom[0]["nodeId"] == "av_sensor_inputs"
    assert "no dedicated camera, LiDAR, or radar sensor component" in raw["steps"][2]["content"]

    for component in components.values():
        if component["componentType"] == "ml-model":
            block = catalog_block(catalog, "ml-model", component["nodeId"])
            options = set(re.findall(r'"(Computer Vision|Forecasting)"', block))
            assert component["properties"]["modelType"] in options


def test_replayed_architecture_is_connected_and_keeps_target_path():
    raw, _ = load_guide_and_problem()
    known_nodes = set()
    edge_ids = set()

    for step in sorted(raw["steps"], key=lambda row: row["stepNumber"]):
        if step["type"] == "add_component":
            node_id = step["component"]["nodeId"]
            assert node_id not in known_nodes
            known_nodes.add(node_id)
        elif step["type"] == "add_connection":
            edge = step["connection"]
            assert edge["edgeId"] not in edge_ids
            edge_ids.add(edge["edgeId"])
            assert edge["sourceNodeId"] in known_nodes
            assert edge["targetNodeId"] in known_nodes
            assert edge["connectionType"] in CONNECTION_TYPES
            assert edge["label"] and edge["description"]

    graph = build_architecture(raw)["architecture"]
    nodes = {component["id"] for component in graph["components"]}
    assert nodes == known_nodes
    assert len(graph["connections"]) == len(edge_ids)

    neighbors = {node_id: set() for node_id in nodes}
    directed = {node_id: set() for node_id in nodes}
    for edge in graph["connections"]:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
        directed[edge["source"]].add(edge["target"])

    reached = set()
    pending = deque(["av_sensor_inputs"])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
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

    assert reaches("av_sensor_inputs", "av_sensor_alignment")
    assert reaches("av_sensor_alignment", "av_inference_runtime")
    assert reaches("av_vehicle_edge", "av_inference_runtime")
    assert reaches("av_inference_runtime", "av_bev_perception_model")
    assert reaches("av_bev_perception_model", "av_temporal_tracking_model")
    assert reaches("av_temporal_tracking_model", "av_path_planning_consumer")
    assert reaches("av_model_training", "av_bev_perception_model")


def test_training_provenance_evaluation_evidence_and_release_scope_are_explicit():
    raw, _ = load_guide_and_problem()
    steps = {step["id"]: step for step in raw["steps"]}

    training = steps["av_16_training_pipeline"]
    candidate_handoff = steps["av_17_training_to_model"]
    training_text = " ".join(
        [
            training["content"],
            training["component"]["properties"]["purpose"],
            candidate_handoff["content"],
        ]
    ).lower()
    assert "training-data revision" in training_text
    assert "synthetic-data inputs" in training_text
    assert "code/configuration" in training_text
    assert "resulting candidate model" in training_text
    assert "not a stated brief requirement" in training_text

    # Training or handing off a candidate is not evidence that the mAP target passed.
    assert "legacy-constraint:2" not in training["requirementIds"]
    assert "legacy-constraint:2" not in candidate_handoff["requirementIds"]

    latency_evaluation = steps["av_19_measure_end_to_end"]
    accuracy_evaluation = steps["av_20_measure_accuracy_and_coverage"]
    evaluation_text = " ".join(
        [latency_evaluation["content"], accuracy_evaluation["content"]]
    ).lower()
    assert "measured results" in evaluation_text
    assert "tested edge configuration" in evaluation_text
    assert "evaluation-set revision" in evaluation_text
    assert "mAP above 90%" in accuracy_evaluation["content"]
    assert "legacy-constraint:2" in accuracy_evaluation["requirementIds"]

    lifecycle_text = " ".join(
        [
            candidate_handoff["content"],
            candidate_handoff["connection"]["description"],
            steps["av_21_review_boundary"]["content"],
        ]
    ).lower()
    assert "does not define" in lifecycle_text
    assert "approval" in lifecycle_text
    assert "release" in lifecycle_text
    assert "promotion lifecycle" in lifecycle_text
    assert "not an approved or deployed model" in lifecycle_text
