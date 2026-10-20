"""Structural review of the ml_007 computer-vision walkthrough draft.

These tests do not establish browser apply/save/reload parity or live AI quality.
"""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "ml_007"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
TITLE = "Design a Computer Vision Quality Inspection System"
DESCRIPTION = (
    "Design a computer vision system for automated quality inspection in manufacturing "
    "that detects defects on production lines, classifies defect types, and integrates "
    "with factory automation systems."
)
PROBLEM_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
STEP_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "decision_point",
    "scale_trigger",
}
CONNECTION_TYPES = {
    "api-call",
    "data-flow",
    "database-connection",
    "event-stream",
    "grpc",
}


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def load_problem_fixture():
    problems = json.loads(PROBLEM_FIXTURE_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def catalog_block(catalog: str, component_type: str) -> str:
    match = re.search(
        rf'(?ms)^  \{{\r?\n    id: "{re.escape(component_type)}"(?P<body>.*?)^  \}},',
        catalog,
    )
    assert match, f"unknown catalog component type {component_type}"
    return match.group("body")


def test_schema_phases_and_exact_brief_anchor_coverage():
    raw, guide = load_guide()
    problem = load_problem_fixture()
    first_step = next(step for step in guide.steps if step.id == "cv_01")
    assert TITLE in first_step.content
    assert DESCRIPTION in first_step.content
    assert problem["title"] == TITLE
    assert problem["description"] == DESCRIPTION
    assert guide.problem_id == PROBLEM_ID
    assert guide.version.endswith("review-draft")
    assert guide.totalSteps == len(guide.steps) == 58
    assert [step.stepNumber for step in guide.steps] == list(range(1, 59))
    assert len({step.id for step in guide.steps}) == 58
    assert all(step.type in STEP_TYPES for step in guide.steps)

    expected_anchors = {
        *(
            f"legacy-requirement:{index}"
            for index in range(1, len(problem["requirements"]) + 1)
        ),
        *(
            f"legacy-constraint:{index}"
            for index in range(1, len(problem["constraints"]) + 1)
        ),
    }
    mapped_anchors = {
        anchor for step in guide.steps for anchor in step.requirementIds
    }
    assert mapped_anchors == expected_anchors
    action_steps = [
        step for step in guide.steps
        if step.type in {"add_component", "add_connection", "decision_point"}
    ]
    for anchor in expected_anchors:
        assert any(anchor in step.requirementIds for step in action_steps), (
            f"{anchor} must have at least one explicit architecture/decision action"
        )

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end
        assert all(
            guide.steps[number - 1].phase == phase.name
            for number in range(start, end + 1)
        )
        next_step = end + 1
    assert next_step == guide.totalSteps + 1
    assert raw["phases"][-1]["stepRange"] == [47, 58]


def test_catalog_component_types_properties_and_select_values_are_supported():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}
    custom_labels = []

    for step in raw["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            assert component["nodeId"] not in components
            assert component["properties"]["componentName"] == component["label"]
            assert len(component["properties"]["purpose"]) >= 70
            assert component["highlightReason"]
            components[component["nodeId"]] = component
            if component["componentType"] == "custom-component":
                custom_labels.append(component["label"])
            properties = component["properties"]
            component_type = component["componentType"]
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            assert update["nodeId"] in components
            assert update["properties"]
            properties = update["properties"]
            component_type = components[update["nodeId"]]["componentType"]
        else:
            continue

        block = catalog_block(catalog, component_type)
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert set(properties) <= supported, (
            f"{step['id']}: unsupported {component_type} properties "
            f"{sorted(set(properties) - supported)}"
        )
        for key, value in properties.items():
            field_start = block.find(f'key: "{key}"')
            field_end = block.find("\n      },", field_start)
            field = block[field_start:field_end if field_end >= 0 else len(block)]
            field_type = re.search(r'\btype:\s*"([^"]+)"', field)
            assert field_type, f"{step['id']}: missing catalog type for {key}"
            if field_type.group(1) == "boolean":
                assert type(value) is bool, f"{step['id']}/{key} must be boolean"
            if field_type.group(1) == "select":
                options = re.search(r'\boptions:\s*\[([^\]]+)\]', field, re.DOTALL)
                assert options, f"{step['id']}/{key} has no catalog select options"
                allowed = re.findall(r'"([^"]+)"', options.group(1))
                assert value in allowed, (
                    f"{step['id']}/{key} value {value!r} is not in {allowed}"
                )

    # The catalog has no camera, PLC, industrial-controller, or machine-vision
    # palette item. These are existing plant endpoints, so the generic type is
    # justified only for these two nodes; no new component type is introduced.
    assert custom_labels == [
        "Production-Line Vision Camera",
        "PLC & Factory Control Adapter",
    ]
    assert components["cv_model"]["properties"]["modelType"] == "Computer Vision"
    assert components["cv_edge"]["properties"]["scope"] == "Local"
    assert components["cv_images"]["properties"]["provider"] == "MinIO"
    assert "ONNX Runtime or TensorRT" in components["cv_serving"]["properties"]["purpose"]


def test_ordered_actions_build_one_complete_connected_graph():
    raw, _ = load_guide()
    nodes = {}
    edge_ids = set()
    pairs = []
    for step in raw["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            assert component["nodeId"] not in nodes
            assert set(component["position"]) >= {"x", "y"}
            nodes[component["nodeId"]] = component
        elif step["type"] == "add_connection":
            connection = step["connection"]
            assert connection["edgeId"] not in edge_ids
            assert connection["connectionType"] in CONNECTION_TYPES
            assert connection["sourceNodeId"] in nodes
            assert connection["targetNodeId"] in nodes
            edge_ids.add(connection["edgeId"])
            pairs.append((connection["sourceNodeId"], connection["targetNodeId"]))
        if step.get("componentUpdate"):
            assert step["componentUpdate"]["nodeId"] in nodes

    assert len(nodes) == 15
    assert len(edge_ids) == 20
    adjacency = {node_id: set() for node_id in nodes}
    for source, target in pairs:
        adjacency[source].add(target)
        adjacency[target].add(source)
    reached = set()
    pending = deque(["cv_camera"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(adjacency[node_id] - reached)
    assert reached == set(nodes)
    assert all(adjacency.values())

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    assert len(architecture["components"]) == len(nodes)
    assert len(architecture["connections"]) == len(edge_ids)
    assert all(
        edge["source"] in nodes and edge["target"] in nodes
        for edge in architecture["connections"]
    )
    assert len(replay["acceptedDecisions"]) == 8


def test_domain_content_distinguishes_targets_assumptions_and_failure_modes():
    raw, _ = load_guide()
    text = json.dumps(raw, ensure_ascii=False).casefold()
    steps = {step["id"]: step for step in raw["steps"]}
    assert "supplied brief facts:" in steps["cv_01"]["content"].casefold()
    assert "provisional design assumptions" in steps["cv_01"]["content"].casefold()
    for phrase in (
        ">99.5% detection accuracy",
        "<200ms/item",
        "<0.1% false rejection",
        "100+ items/minute",
        "edge hardware",
        "scratches, dents, and cracks",
        "lighting and position variation",
        "false-reject",
        "item_sequence",
        "idempotent",
        "acknowledgment",
        "safe hold",
        "checkpointed",
        "human-adjudicated",
        "last-known-good",
        "rollback",
        "active-learning",
        "synthetic defect",
    ):
        assert phrase.casefold() in text, f"missing domain concern: {phrase}"
    assert "not achieved results" in steps["cv_01"]["content"].casefold()
    assert "no browser apply/save/reload" in steps["cv_58"]["content"].casefold()
    assert "live ai assessment" in steps["cv_58"]["content"].casefold()
    assert "claimed complete" in steps["cv_58"]["content"].casefold()


def test_frozen_brief_targets_stay_distinct_and_image_scope_is_explicit():
    problem = load_problem_fixture()
    steps = {step["id"]: step for step in load_guide()[0]["steps"]}
    constraints = problem["constraints"]

    assert len(constraints) == 5
    assert "99.5%" in constraints[0] and "accuracy" in constraints[0].casefold()
    assert "200ms" in constraints[1]
    assert "0.1%" in constraints[2] and "false rejection" in constraints[2].casefold()
    assert "edge hardware" in constraints[3].casefold()
    assert "100+" in constraints[4] and "items per minute" in constraints[4].casefold()

    overview = steps["cv_01"]["content"].casefold()
    throughput = steps["cv_03"]["content"].casefold()
    camera = steps["cv_04"]["content"].casefold()
    rate_sizing = steps["cv_08"]["content"].casefold()
    quality = steps["cv_14"]["content"].casefold()
    latency = steps["cv_18"]["content"].casefold()
    release_gate = steps["cv_56"]["content"].casefold()
    release_metric = steps["cv_56"]["scaleTrigger"]["metric"].casefold()
    closeout = steps["cv_58"]["content"].casefold()

    for target in (">99.5% detection accuracy", "<200ms/item", "<0.1% false rejection", "edge hardware", "100+ items/minute"):
        assert target in overview
    assert "approximately 1.67 items/second" in throughput
    assert "per line/lane or system-wide" in throughput
    assert "not a throughput guarantee" in throughput
    assert "start/end boundary" in throughput
    assert "which statistic" in throughput
    assert "without assuming a number of production lines, cameras, lanes, or inspection cells" in overview
    for image_measure in (
        "pixel dimensions",
        "bit depth",
        "smallest physical defect",
        "image width/height",
        "region of interest",
        "smallest-defect pixel footprint",
        "trigger cadence",
    ):
        assert image_measure in camera
    assert "does not define its observation window" in rate_sizing

    for quality_term in (">99.5% detection-accuracy", "<0.1% false-rejection", "separately"):
        assert quality_term in quality
    assert "definition and denominator need confirmation" in quality
    assert "does not identify which statistic must meet <200ms/item" in latency
    assert "agreed <200ms/item processing-time measure" in release_metric
    assert "latency statistic/boundary" in release_gate
    assert "<200ms/item at the agreed timing boundary and statistic" in closeout
    assert ">99.5% detection accuracy and <0.1% false rejection as separate measures" in closeout

    def anchors(step_id):
        return set(steps[step_id]["requirementIds"])

    assert {f"legacy-constraint:{index}" for index in range(1, 6)} <= anchors("cv_03")
    assert {"legacy-constraint:1", "legacy-constraint:3"} <= anchors("cv_14")
    assert not {"legacy-constraint:2", "legacy-constraint:4", "legacy-constraint:5"} & anchors("cv_14")
    assert {"legacy-constraint:2", "legacy-constraint:4", "legacy-constraint:5"} <= anchors("cv_08")
    assert not {"legacy-constraint:1", "legacy-constraint:3"} & anchors("cv_08")

