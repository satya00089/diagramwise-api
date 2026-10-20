"""Structural, frozen-brief, catalog, and replay checks for cloud_aws_003."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / "cloud_aws_003.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": "cloud_aws_003",
    "slug": "build-a-real-time-data-streaming-pipeline",
    "title": "Build a Real-time Data Streaming Pipeline",
    "description": "Design a real-time data pipeline that can ingest, process, and analyze millions of events per second with sub-second latency.",
    "category": "AWS - Data Streaming",
    "domain": "infra",
    "difficulty": "Hard",
    "estimated_time": "60-90 minutes",
    "requirements": [
        "Ingest millions of events per second",
        "Process data in real-time",
        "Perform streaming analytics",
        "Store processed data for queries",
        "Visualize real-time dashboards",
        "Handle data transformation",
        "Support replay of events",
        "Monitor pipeline health",
    ],
    "constraints": [
        "Sub-second processing latency",
        "Handle burst traffic up to 100k events/sec",
        "Ensure exactly-once processing",
        "Scale horizontally automatically",
        "Support data retention for 7 days",
    ],
}
STEP_TYPES = {
    "explanation", "add_component", "add_connection", "decision_point", "scale_trigger"
}
ACTION_TYPES = {"add_component", "add_connection", "update_component"}
CONNECTION_TYPES = {"api-call", "data-flow", "database-connection", "message-queue"}
EXPECTED_NODES = 10
EXPECTED_EDGES = 14


def load_problem() -> dict:
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == FROZEN_BRIEF["id"])


def load_guide() -> dict:
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"{step_id}: unknown palette component {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), f"{step_id}: incomplete catalog entry {component_type}"
    return catalog[match.start() : block_end]


def test_schema_and_frozen_problem_row_are_preserved():
    problem = load_problem()
    for field, expected in FROZEN_BRIEF.items():
        assert problem.get(field) == expected
    assert problem["has_guided_walkthrough"] is False

    raw = load_guide()
    guide = GuidedWalkthrough.model_validate(raw)
    assert guide.problem_id == FROZEN_BRIEF["id"]
    assert guide.version == "1.0"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 28
    assert "has_guided_walkthrough" not in raw

    opening = guide.steps[0].content
    for field in ("title", "slug", "description", "category", "domain", "difficulty", "estimated_time"):
        assert FROZEN_BRIEF[field] in opening
    for supplied_fact in (*FROZEN_BRIEF["requirements"], *FROZEN_BRIEF["constraints"]):
        assert supplied_fact in opening
    assumptions = load_guide()["steps"][1]["content"]
    for phrase in ("millions of events per second", "100k events per second", "partition-key skew", "seven days"):
        assert phrase in assumptions


def test_steps_phases_and_every_frozen_anchor_are_actionable():
    guide = load_guide()
    assert [step["stepNumber"] for step in guide["steps"]] == list(range(1, guide["totalSteps"] + 1))
    assert len({step["id"] for step in guide["steps"]}) == guide["totalSteps"]
    assert all(step["type"] in STEP_TYPES and step["title"].strip() and step["content"].strip() for step in guide["steps"])

    expected = {
        *(f"legacy-requirement:{index}" for index in range(1, 9)),
        *(f"legacy-constraint:{index}" for index in range(1, 6)),
    }
    mapped = {anchor for step in guide["steps"] for anchor in step.get("requirementIds", [])}
    actionable = {
        anchor for step in guide["steps"] if step["type"] in ACTION_TYPES
        for anchor in step.get("requirementIds", [])
    }
    assert mapped == actionable == expected

    next_step = 1
    for phase in guide["phases"]:
        start, end = phase["stepRange"]
        assert start == next_step
        assert start <= end <= guide["totalSteps"]
        assert all(step["phase"] == phase["name"] for step in guide["steps"][start - 1 : end])
        next_step = end + 1
    assert next_step == guide["totalSteps"] + 1


def test_catalog_properties_and_ordered_replay_form_one_connected_architecture():
    guide = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    nodes = {}
    edges = []
    edge_ids = set()

    for step in sorted(guide["steps"], key=lambda row: row["stepNumber"]):
        if step["type"] == "add_component":
            component = step["component"]
            assert component["componentType"] != "custom-component"
            assert component["nodeId"] not in nodes
            assert set(component["position"]) == {"x", "y"}
            assert component["properties"]["componentName"] == component["label"]
            assert component["properties"]["purpose"].strip()
            block = catalog_block(catalog, component["componentType"], step["id"])
            supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
            assert set(component["properties"]) <= supported
            for name, value in component["properties"].items():
                schema = re.search(
                    rf'\{{\s*key:\s*"{re.escape(name)}"(?P<body>.*?)(?=\n\s*\{{|\n\s*\],)',
                    block,
                    re.DOTALL,
                )
                if schema and re.search(r'\btype:\s*"select"', schema["body"]):
                    options = re.search(r'options:\s*\[([^\]]*)\]', schema["body"], re.DOTALL)
                    if options:
                        allowed = set(re.findall(r'"([^"]+)"', options[1]))
                        assert value in allowed, f"{step['id']}: invalid {component['componentType']}.{name}={value!r}"
            nodes[component["nodeId"]] = component
        elif step["type"] == "add_connection":
            connection = step["connection"]
            assert connection["edgeId"] not in edge_ids
            assert connection["sourceNodeId"] in nodes
            assert connection["targetNodeId"] in nodes
            assert connection["connectionType"] in CONNECTION_TYPES
            assert connection["label"].strip() and connection["description"].strip()
            edge_ids.add(connection["edgeId"])
            edges.append((connection["sourceNodeId"], connection["targetNodeId"]))

    replay = build_architecture(guide)
    architecture = replay["architecture"]
    assert len(nodes) == EXPECTED_NODES
    assert len(edge_ids) == EXPECTED_EDGES
    assert {component["id"] for component in architecture["components"]} == set(nodes)
    assert len(architecture["connections"]) == EXPECTED_EDGES
    assert len(replay["appliedStepIds"]) == EXPECTED_NODES + EXPECTED_EDGES

    neighbors = {node_id: set() for node_id in nodes}
    for source, target in edges:
        neighbors[source].add(target)
        neighbors[target].add(source)
    reached = set()
    pending = deque(["streaming_pipeline_producers"])
    while pending:
        node_id = pending.popleft()
        if node_id in reached:
            continue
        reached.add(node_id)
        pending.extend(neighbors[node_id] - reached)
    assert reached == set(nodes)
