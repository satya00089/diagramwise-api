"""Structural, frozen-brief, catalog, and replay checks for aiops_007."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / "aiops_007.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": "aiops_007",
    "slug": "design-an-intelligent-capacity-planning-system",
    "title": "Design an Intelligent Capacity Planning System",
    "description": "Design an AI-driven capacity planning system that forecasts future resource needs, models growth scenarios, optimizes cloud spending, and provides procurement recommendations.",
    "category": "AIOps - Capacity Planning",
    "domain": "aiml",
    "difficulty": "Hard",
    "estimated_time": "60-90 minutes",
    "requirements": [
        "Forecast resource utilization trends",
        "Model multiple growth scenarios (base, high, low)",
        "Identify capacity bottlenecks before they occur",
        "Optimize instance types and sizing",
        "Support reserved instance and savings plan planning",
        "Generate capacity reports for leadership",
        "Handle multi-cloud capacity views",
        "Alert on resources approaching capacity limits",
    ],
    "constraints": [
        "Forecast accuracy within 10% for 90-day horizon",
        "Support 1000+ resource types across services",
        "Update forecasts daily",
        "Reduce over-provisioning by 25%",
        "Handle seasonal and event-driven patterns",
    ],
}
STEP_TYPES = {
    "explanation", "add_component", "add_connection", "decision_point", "scale_trigger"
}
ACTION_TYPES = {"add_component", "add_connection", "update_component"}
CONNECTION_TYPES = {"api-call", "data-flow", "database-connection", "message-queue"}
EXPECTED_NODES = 13
EXPECTED_EDGES = 20


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
    assert guide.totalSteps == len(guide.steps) == 38
    assert "has_guided_walkthrough" not in raw

    opening = guide.steps[0].content
    for field in ("title", "slug", "description", "category", "domain", "difficulty", "estimated_time"):
        assert FROZEN_BRIEF[field] in opening
    for supplied_fact in (*FROZEN_BRIEF["requirements"], *FROZEN_BRIEF["constraints"]):
        assert supplied_fact in opening
    assumptions = load_guide()["steps"][1]["content"]
    for phrase in ("history length", "sampling interval", "25% over-provisioning reduction", "not an exact schedule guarantee"):
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
                    options = re.search(r'options:\s*\[([^\]]*)\]', schema[1], re.DOTALL)
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
    pending = deque(["capacity_planning_console"])
    while pending:
        node_id = pending.popleft()
        if node_id in reached:
            continue
        reached.add(node_id)
        pending.extend(neighbors[node_id] - reached)
    assert reached == set(nodes)
