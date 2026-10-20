"""Frozen-brief and graph checks for the Distributed Tracing review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca875"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "category": "Observability",
    "companies": ["Uber", "Amazon", "Jaeger", "Zipkin"],
    "constraints": [
        "Low overhead on application performance",
        "Handle high trace volume",
        "Efficient storage for trace data",
        "Support trace context propagation",
        "Real-time trace analysis",
    ],
    "createdAt": "2025-10-29T10:40:27.393000",
    "description": "Design a system to trace requests across microservices for debugging and performance monitoring.",
    "difficulty": "Very Hard",
    "domain": "application",
    "estimatedTime": "60-90 minutes",
    "has_guided_walkthrough": False,
    "hints": [
        "Trace ID and span ID propagation",
        "Sampling strategies (head-based, tail-based)",
        "Time-series storage for spans",
        "Service mesh integration",
        "Distributed context propagation",
    ],
    "id": PROBLEM_ID,
    "requirements": [
        "Trace requests across distributed services",
        "Capture timing and latency information",
        "Visualize service dependencies",
        "Support trace sampling",
        "Store and query trace data",
        "Identify performance bottlenecks",
        "Handle billions of spans per day",
        "Integration with different frameworks",
    ],
    "slug": "design-a-distributed-tracing-system",
    "tags": ["tracing", "observability", "microservices", "performance", "debugging"],
    "title": "Design a Distributed Tracing System",
    "updatedAt": "2025-10-29T10:40:27.393000",
}

STEP_TYPES = {"explanation", "add_component", "add_connection"}
CONNECTION_TYPES = {
    "http",
    "api-call",
    "database-connection",
    "message-queue",
    "data-flow",
}


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def frozen_problem():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def test_exact_frozen_brief_and_walkthrough_schema():
    problem = frozen_problem()
    assert problem == FROZEN_BRIEF

    raw, guide = load_guide()
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 40
    assert raw["totalSteps"] == len(raw["steps"]) == 40

    request = make_request(problem, raw, build_architecture(raw))
    assert request["problem"]["requirements"].splitlines() == FROZEN_BRIEF["requirements"]
    assert request["problem"]["constraints"].splitlines() == FROZEN_BRIEF["constraints"]


def test_ordered_phases_and_every_brief_item_anchors_to_graph_actions():
    raw, guide = load_guide()
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step["type"] in STEP_TYPES and step["content"].strip() for step in raw["steps"])

    anchors = {
        *(f"legacy-requirement:{index}" for index in range(1, len(FROZEN_BRIEF["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(FROZEN_BRIEF["constraints"]) + 1)),
    }
    assert {anchor for step in raw["steps"] for anchor in step["requirementIds"]} == anchors
    for step in raw["steps"]:
        assert step["requirementIds"]
        assert set(step["requirementIds"]) <= anchors

    actions = [step for step in raw["steps"] if step["type"] in {"add_component", "add_connection"}]
    action_anchors = {anchor for step in actions for anchor in step["requirementIds"]}
    assert action_anchors == anchors

    expected_start = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == expected_start <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        expected_start = end + 1
    assert expected_start == guide.totalSteps + 1


def test_catalog_properties_and_connected_ordered_replay():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step["type"] == "add_component"
    }
    assert len(components) == 14

    for step in raw["steps"]:
        if step["type"] != "add_component":
            continue
        component = step["component"]
        component_type = component["componentType"]
        properties = component["properties"]
        assert properties["componentName"] == component["label"]
        assert len(properties["purpose"]) >= 70
        assert component["highlightReason"]

        match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
        assert match is not None, f"{step['id']}: unknown catalog component {component_type}"
        block_end = catalog.find("\n  },", match.start())
        assert block_end != -1
        block = catalog[match.start() : block_end]
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert set(properties) <= supported, (
            f"{step['id']}: unsupported properties {sorted(set(properties) - supported)}"
        )

    custom = [component for component in components.values() if component["componentType"] == "custom-component"]
    assert len(custom) == 1
    assert custom[0]["properties"]["componentType"] == "Trace Collector"
    assert "no trace collector" in custom[0]["properties"]["notes"].lower()

    replay = build_architecture(raw)
    nodes = {node["id"]: node for node in replay["architecture"]["components"]}
    edges = replay["architecture"]["connections"]
    assert len(nodes) == 14
    assert len(edges) == 20
    assert all(edge["type"] in CONNECTION_TYPES for edge in edges)
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in edges)

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["trace_query_ui"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == set(nodes)


def test_assumptions_and_open_questions_are_labeled():
    raw, _ = load_guide()
    text = json.dumps(raw, ensure_ascii=False).casefold()
    for phrase in (
        "design assumptions",
        "open questions",
        "not specify",
        "no numeric slo",
        "sampling policy",
        "retention",
        "frameworks",
        "real-time",
    ):
        assert phrase in text
