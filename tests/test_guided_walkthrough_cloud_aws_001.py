"""Structural and catalog contract for the AWS serverless e-commerce draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_aws_001"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

STEP_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "decision_point",
    "scale_trigger",
    "update_component",
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


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def test_walkthrough_matches_problem_and_covers_every_requirement_and_constraint():
    raw, guide = load_guide()
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)

    assert problem["title"] == "Design a Scalable E-commerce Backend"
    assert guide.problem_id == PROBLEM_ID
    assert guide.totalSteps == len(guide.steps)
    assert [step.stepNumber for step in guide.steps] == list(
        range(1, guide.totalSteps + 1)
    )
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES for step in guide.steps)

    expected_ids = {
        *(f"legacy-requirement:{index}" for index in range(1, len(problem["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(problem["constraints"]) + 1)),
    }
    mapped_ids = {key for step in guide.steps for key in step.requirementIds}
    assert mapped_ids == expected_ids

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step
        assert start <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1


def test_walkthrough_actions_replay_to_one_connected_graph():
    raw, _ = load_guide()
    applied = build_architecture(raw)
    architecture = applied["architecture"]
    components = {component["id"] for component in architecture["components"]}
    connections = architecture["connections"]

    assert len(components) >= 20
    assert len(connections) >= 25
    assert len(applied["appliedStepIds"]) > len(applied["explanationOnlyStepIds"])

    neighbors = {component_id: set() for component_id in components}
    for edge in connections:
        assert edge["type"] in CONNECTION_TYPES
        assert edge["source"] in components
        assert edge["target"] in components
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])

    visited = set()
    pending = deque([next(iter(components))])
    while pending:
        component_id = pending.popleft()
        if component_id in visited:
            continue
        visited.add(component_id)
        pending.extend(neighbors[component_id] - visited)
    assert visited == components


def test_every_component_and_update_uses_catalog_ids_and_supported_properties():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step.component.nodeId: step.component
        for step in GuidedWalkthrough.model_validate(raw).steps
        if step.component
    }

    assert additions["ecom_order_workflow"].componentType == "custom-component"
    assert additions["ecom_order_workflow"].properties["componentType"] == (
        "AWS Step Functions Standard Workflow"
    )

    for step in raw["steps"]:
        if step.get("component"):
            component_type = step["component"]["componentType"]
            properties = step["component"].get("properties", {})
        elif step.get("componentUpdate"):
            node_id = step["componentUpdate"]["nodeId"]
            component_type = additions[node_id].componentType
            properties = step["componentUpdate"].get("properties", {})
        else:
            continue

        match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
        assert match is not None, f"{step['id']} uses unknown palette ID {component_type!r}"
        block_end = catalog.find("\n  },", match.start())
        component_block = catalog[match.start() : block_end]
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', component_block))
        assert {"componentName", "purpose"} <= set(properties) if step.get("component") else True
        assert set(properties) <= supported, (
            f"{step['id']} has unsupported properties "
            f"{sorted(set(properties) - supported)}"
        )


def test_payment_and_inventory_lessons_do_not_overclaim_consistency_or_delivery():
    raw, _ = load_guide()
    searchable = json.dumps(raw, ensure_ascii=False).casefold()

    for signal in (
        "idempotency key",
        "transactwriteitems",
        "outbox",
        "compensation",
        "never stores pan/cvv",
        "10,000",
        "<1s",
        "websocket",
        "oldest-message",
        "do not claim the target is met until measured",
    ):
        assert signal in searchable, f"Walkthrough does not explicitly cover {signal!r}"

