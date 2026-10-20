"""Focused contract tests for the AWS batch-processing walkthrough draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_aws_004"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "title": "Design a Cost-Optimized Architecture for Batch Processing",
    "description": (
        "Design a batch processing system that can process large datasets "
        "efficiently while minimizing compute costs and handling interruptions gracefully."
    ),
    "requirements": [
        "Process large datasets in batches",
        "Minimize compute costs",
        "Handle interruptions gracefully",
        "Schedule batch jobs",
        "Manage job dependencies",
        "Store input/output data efficiently",
        "Monitor job progress",
        "Retry failed jobs automatically",
    ],
    "constraints": [
        "Reduce costs by 70% compared to on-demand",
        "Handle spot instance interruptions",
        "Complete jobs within SLA timeframes",
        "Support parallel job execution",
        "Maintain job state across failures",
    ],
    "hints": [
        "Use EC2 Spot Instances for compute",
        "AWS Batch for job orchestration",
        "S3 for input/output storage",
        "Step Functions for workflow",
        "CloudWatch Events for scheduling",
        "SNS for job notifications",
    ],
}

STEP_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "decision_point",
    "scale_trigger",
    "update_component",
}
CONNECTION_TYPES = {"api-call", "data-flow", "event-stream", "message-queue"}
EXPECTED_COMPONENT_TYPES = {
    "batch_scheduler": "custom-component",
    "batch_workflow": "custom-component",
    "aws_batch": "custom-component",
    "input_data_s3": "object-storage",
    "spot_workers": "processing-worker",
    "checkpoint_output_s3": "object-storage",
    "job_monitoring": "monitoring",
    "job_notifications": "notification-service",
}
EXPECTED_STEP_ANCHORS = {
    "batch_08": {"legacy-requirement:4"},
    "batch_09": {"legacy-requirement:5", "legacy-constraint:5"},
    "batch_10": {"legacy-requirement:4"},
    "batch_14": {"legacy-requirement:1", "legacy-constraint:4"},
    "batch_15": {"legacy-requirement:5", "legacy-constraint:4"},
    "batch_16": {"legacy-requirement:8", "legacy-constraint:3"},
    "batch_17": {
        "legacy-requirement:1",
        "legacy-constraint:3",
        "legacy-constraint:4",
    },
    "batch_18": {"legacy-requirement:1", "legacy-requirement:6"},
    "batch_19": {"legacy-requirement:1", "legacy-requirement:6"},
    "batch_20": {
        "legacy-requirement:1",
        "legacy-requirement:2",
        "legacy-requirement:3",
        "legacy-constraint:2",
        "legacy-constraint:4",
    },
    "batch_21": {"legacy-requirement:1", "legacy-constraint:4"},
    "batch_22": {
        "legacy-requirement:1",
        "legacy-requirement:6",
        "legacy-constraint:4",
    },
    "batch_23": {"legacy-requirement:1", "legacy-constraint:4"},
    "batch_25": {
        "legacy-requirement:3",
        "legacy-requirement:6",
        "legacy-constraint:2",
        "legacy-constraint:5",
    },
    "batch_26": {
        "legacy-requirement:3",
        "legacy-requirement:6",
        "legacy-constraint:2",
        "legacy-constraint:5",
    },
    "batch_27": {"legacy-requirement:2", "legacy-constraint:4"},
    "batch_30": {
        "legacy-requirement:3",
        "legacy-requirement:8",
        "legacy-constraint:2",
    },
    "batch_31": {
        "legacy-requirement:3",
        "legacy-constraint:2",
        "legacy-constraint:5",
    },
    "batch_33": {
        "legacy-requirement:3",
        "legacy-requirement:8",
        "legacy-constraint:2",
    },
    "batch_34": {"legacy-requirement:7"},
    "batch_35": {"legacy-requirement:7"},
    "batch_36": {"legacy-requirement:7"},
    "batch_37": {"legacy-requirement:7", "legacy-constraint:3"},
    "batch_42": {
        "legacy-requirement:3",
        "legacy-constraint:2",
        "legacy-constraint:3",
        "legacy-constraint:5",
    },
    "batch_43": {
        "legacy-requirement:1",
        "legacy-constraint:3",
        "legacy-constraint:4",
    },
    "batch_44": {"legacy-requirement:2", "legacy-constraint:1"},
    "batch_45": {"legacy-requirement:5", "legacy-constraint:4"},
}


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def _catalog_component_block(catalog: str, component_type: str) -> str:
    match = re.search(
        rf'(?m)^    id:\s*"{re.escape(component_type)}"\s*,', catalog
    )
    assert match is not None, f"Unknown palette component type {component_type!r}"
    following = re.search(r"(?m)^  \},\s*$", catalog[match.end() :])
    assert following is not None, f"Could not delimit catalog entry {component_type!r}"
    return catalog[match.start() : match.end() + following.start()]


def test_frozen_live_brief_and_walkthrough_identity_match_exactly():
    rows = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in rows if row["id"] == PROBLEM_ID)
    actual_brief = {key: problem[key] for key in FROZEN_BRIEF}
    raw, guide = load_guide()

    assert actual_brief == FROZEN_BRIEF
    assert problem["has_guided_walkthrough"] is False
    assert guide.problem_id == PROBLEM_ID
    assert raw["problem_id"] == PROBLEM_ID


def test_walkthrough_has_valid_schema_steps_phases_and_exact_action_anchors():
    _, guide = load_guide()
    assert 35 <= guide.totalSteps <= 60
    assert guide.totalSteps == len(guide.steps)
    assert [step.stepNumber for step in guide.steps] == list(
        range(1, guide.totalSteps + 1)
    )
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES for step in guide.steps)

    expected_anchors = {
        *(f"legacy-requirement:{index}" for index in range(1, 9)),
        *(f"legacy-constraint:{index}" for index in range(1, 6)),
    }
    all_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    graph_action_types = {
        "add_component",
        "add_connection",
        "update_component",
        "scale_trigger",
    }
    action_anchors = {
        anchor
        for step in guide.steps
        if step.type in graph_action_types
        for anchor in step.requirementIds
    }
    assert all_anchors == expected_anchors
    assert action_anchors == expected_anchors

    for step in guide.steps:
        if step.type == "add_component":
            assert step.component is not None
        elif step.type == "add_connection":
            assert step.connection is not None
        elif step.type == "update_component":
            assert step.componentUpdate is not None
        elif step.type == "decision_point":
            assert step.decision is not None
        elif step.type == "scale_trigger":
            assert step.scaleTrigger is not None

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step
        assert start <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1


def test_requirement_anchors_match_the_action_that_directly_supports_them():
    _, guide = load_guide()
    actual = {
        step.id: set(step.requirementIds)
        for step in guide.steps
        if step.requirementIds
    }

    assert actual == EXPECTED_STEP_ANCHORS


def test_numeric_targets_are_limited_to_the_frozen_brief_cost_goal():
    raw, _ = load_guide()
    numeric_claim = re.compile(
        r"(?<![A-Za-z])\d+(?:\.\d+)?\s*(?:%|"
        r"ms\b|milliseconds?\b|seconds?\b|minutes?\b|hours?\b|"
        r"days?\b|weeks?\b|months?\b|years?\b|"
        r"[KMGTPE]?i?B\b|requests?\s*(?:/|per)\s*second\b)",
        re.IGNORECASE,
    )
    text = json.dumps(raw, ensure_ascii=False)
    claims = {match.group(0).strip() for match in numeric_claim.finditer(text)}

    assert claims == {"70%"}
    assert "70% compared to on-demand" in raw["steps"][0]["content"]


def test_components_use_only_real_catalog_types_and_supported_properties():
    raw, guide = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step.component.nodeId: step.component
        for step in guide.steps
        if step.type == "add_component" and step.component is not None
    }
    assert {node_id: component.componentType for node_id, component in additions.items()} == (
        EXPECTED_COMPONENT_TYPES
    )

    for step in raw["steps"]:
        if step.get("component"):
            component = step["component"]
            component_type = component["componentType"]
            properties = component.get("properties", {})
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            component_type = additions[update["nodeId"]].componentType
            properties = update.get("properties", {})
        else:
            continue

        block = _catalog_component_block(catalog, component_type)
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert properties
        assert set(properties) <= supported, (
            f"{step['id']} uses unsupported {component_type} properties: "
            f"{sorted(set(properties) - supported)}"
        )

    for node_id, component_type in EXPECTED_COMPONENT_TYPES.items():
        if component_type != "custom-component":
            continue
        component = additions[node_id]
        assert component.properties["componentName"]
        assert component.properties["technology"]
        assert component.properties["componentType"]


def test_ordered_replay_has_created_endpoints_and_one_connected_semantic_graph():
    raw, _ = load_guide()
    applied = build_architecture(raw)
    architecture = applied["architecture"]
    components = {component["id"] for component in architecture["components"]}
    connections = architecture["connections"]
    assert components == set(EXPECTED_COMPONENT_TYPES)
    assert len(connections) >= 10
    assert len(applied["appliedStepIds"]) > len(applied["explanationOnlyStepIds"])

    neighbors = {component_id: set() for component_id in components}
    for connection in connections:
        assert connection["type"] in CONNECTION_TYPES
        assert connection["source"] in components
        assert connection["target"] in components
        neighbors[connection["source"]].add(connection["target"])
        neighbors[connection["target"]].add(connection["source"])

    visited = set()
    pending = deque([next(iter(components))])
    while pending:
        component_id = pending.popleft()
        if component_id in visited:
            continue
        visited.add(component_id)
        pending.extend(neighbors[component_id] - visited)
    assert visited == components

