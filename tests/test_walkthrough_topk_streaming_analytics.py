"""Contract checks for the Top-K streaming analytics walkthrough draft."""

import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca863"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
COMPONENT_CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

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


def load_problem():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def test_topk_walkthrough_matches_runner_schema_and_covers_brief():
    guide = GuidedWalkthrough.model_validate_json(GUIDE_PATH.read_text(encoding="utf-8"))
    problem = load_problem()

    assert guide.problem_id == PROBLEM_ID
    assert guide.totalSteps == len(guide.steps)
    assert [step.stepNumber for step in guide.steps] == list(
        range(1, guide.totalSteps + 1)
    )
    assert all(step.type in STEP_TYPES for step in guide.steps)

    mapped_ids = {
        requirement_id
        for step in guide.steps
        for requirement_id in step.requirementIds
    }
    expected_ids = {
        *(f"legacy-requirement:{index}" for index in range(1, len(problem["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(problem["constraints"]) + 1)),
    }
    assert mapped_ids == expected_ids

    phase_numbers = [
        number
        for phase in guide.phases
        for number in range(phase.stepRange[0], phase.stepRange[1] + 1)
    ]
    assert phase_numbers == list(range(1, guide.totalSteps + 1))


def test_topk_actions_form_a_connected_catalog_valid_canvas():
    guide = GuidedWalkthrough.model_validate_json(GUIDE_PATH.read_text(encoding="utf-8"))
    catalog = COMPONENT_CATALOG_PATH.read_text(encoding="utf-8")
    components = {}
    edges = []

    for step in guide.steps:
        if step.component:
            component = step.component
            assert component.nodeId not in components
            match = re.search(rf'\bid:\s*"{re.escape(component.componentType)}"', catalog)
            assert match, f"unknown palette component {component.componentType}"
            block_end = catalog.find("\n  },", match.start())
            component_block = catalog[match.start() : block_end]
            supported_properties = set(re.findall(r'\bkey:\s*"([^"]+)"', component_block))
            assert {"componentName", "purpose"} <= set(component.properties)
            assert set(component.properties) <= supported_properties
            components[component.nodeId] = component

        if step.connection:
            edge = step.connection
            assert edge.sourceNodeId in components
            assert edge.targetNodeId in components
            assert edge.connectionType in CONNECTION_TYPES
            edges.append((edge.sourceNodeId, edge.targetNodeId))

        if step.componentUpdate:
            assert step.componentUpdate.nodeId in components
            assert step.componentUpdate.properties

    assert len(edges) == len({step.connection.edgeId for step in guide.steps if step.connection})
    neighbors = {node_id: set() for node_id in components}
    for source, target in edges:
        neighbors[source].add(target)
        neighbors[target].add(source)

    reached = set()
    pending = [next(iter(components))]
    while pending:
        node_id = pending.pop()
        if node_id in reached:
            continue
        reached.add(node_id)
        pending.extend(neighbors[node_id] - reached)
    assert reached == set(components)


def test_topk_lessons_preserve_exactness_and_window_semantics():
    guide = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    lesson = json.dumps(guide, ensure_ascii=False).casefold()

    for window in ("5-minute", "1-hour", "24-hour"):
        assert window in lesson
    assert "exact" in lesson
    assert "count-min sketch estimates as final scores" in lesson
    assert "sliding-window boundary" in lesson
    assert "viral" in lesson and "stripe" in lesson
    assert "min-heap" in lesson and "event-expiry decrements" in lesson
    assert "historical" in lesson and "as-of" in lesson
    assert "billions" in lesson and "active articles" in lesson
    assert "near-real-time" in lesson


def test_topk_does_not_invent_freshness_or_retention_guarantees():
    guide = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    lesson = json.dumps(guide, ensure_ascii=False).casefold()

    unsupported_targets = (
        "p95",
        "<=5 seconds",
        "five seconds",
        "60-second",
        "<=60 seconds",
        "<=60s",
        "30 days",
        "one-minute",
        "day 31-365",
        "day 365",
        "365 days",
        "minute-aligned",
    )
    for target in unsupported_targets:
        assert target not in lesson

    assert "not a numeric freshness threshold" in lesson
    assert "does not specify a retention horizon" in lesson
    assert "product owners" in lesson


def test_topk_requirement_anchors_stay_specific_to_each_action():
    guide = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    steps = {step["id"]: step for step in guide["steps"]}
    expected_anchors = {
        "topk_10": {"legacy-requirement:5", "legacy-constraint:4"},
        "topk_11": {
            "legacy-requirement:5",
            "legacy-constraint:2",
            "legacy-constraint:4",
        },
        "topk_14": {
            "legacy-requirement:5",
            "legacy-constraint:4",
            "legacy-constraint:5",
        },
        "topk_20": {
            "legacy-requirement:2",
            "legacy-requirement:4",
            "legacy-constraint:1",
        },
        "topk_27": {
            "legacy-requirement:1",
            "legacy-constraint:4",
            "legacy-constraint:5",
        },
        "topk_28": {
            "legacy-requirement:4",
            "legacy-requirement:5",
            "legacy-constraint:5",
        },
        "topk_31": {
            "legacy-requirement:5",
            "legacy-constraint:4",
            "legacy-constraint:5",
        },
    }

    for step_id, expected in expected_anchors.items():
        assert set(steps[step_id]["requirementIds"]) == expected
