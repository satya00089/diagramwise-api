"""Structural, frozen-brief, and catalog checks for the IoC framework draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca886"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

STEP_TYPES = {"explanation", "add_component", "add_connection", "decision_point", "scale_trigger"}
ACTION_TYPES = {"add_component", "add_connection", "decision_point", "scale_trigger"}
CONNECTION_TYPES = {"http", "api-call", "database-connection", "message-queue", "data-flow"}
EXPECTED_COMPONENTS = {"uml-class", "uml-interface"}
ANCHOR_ACTIONS = {
    "legacy-requirement:1": ("di_04",),
    "legacy-requirement:2": ("di_08",),
    "legacy-requirement:3": ("di_11",),
    "legacy-requirement:4": ("di_09",),
    "legacy-requirement:5": ("di_05",),
    "legacy-requirement:6": ("di_08",),
    "legacy-requirement:7": ("di_05", "di_06"),
    "legacy-requirement:8": ("di_07",),
    "legacy-constraint:1": ("di_10",),
    "legacy-constraint:2": ("di_03",),
    "legacy-constraint:3": ("di_13",),
    "legacy-constraint:4": ("di_11",),
    "legacy-constraint:5": ("di_12",),
}


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def frozen_problem():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"{step_id}: unknown catalog ID {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), f"{step_id}: incomplete catalog block for {component_type}"
    return catalog[match.start() : block_end]


def assert_catalog_properties(catalog: str, component_type: str, properties: dict, step_id: str):
    block = catalog_block(catalog, component_type, step_id)
    supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
    assert set(properties) <= supported, (
        f"{step_id}: unsupported {component_type} properties "
        f"{sorted(set(properties) - supported)}"
    )

    for key, value in properties.items():
        field_start = block.index(f'key: "{key}"')
        field_end = block.find("},", field_start)
        assert field_end != -1, f"{step_id}/{key}: catalog property field is incomplete"
        field = block[field_start:field_end]
        field_type = re.search(r'\btype:\s*"([^"]+)"', field)
        assert field_type is not None, f"{step_id}/{key}: catalog property has no type"
        kind = field_type.group(1)
        if kind == "boolean":
            assert type(value) is bool, f"{step_id}/{key} must be boolean"
        elif kind == "number":
            assert type(value) in (int, float), f"{step_id}/{key} must be numeric"
        elif kind == "select":
            options = re.search(r'\boptions:\s*\[([^\]]+)\]', field)
            assert options is not None, f"{step_id}/{key}: select has no options"
            assert value in re.findall(r'"([^"]+)"', options.group(1)), (
                f"{step_id}/{key} is not a catalog select option"
            )
        elif kind in {"text", "textarea"}:
            assert isinstance(value, str), f"{step_id}/{key} must be text"


def test_frozen_brief_step_contract_and_requirement_anchor_coverage():
    problem = frozen_problem()
    raw, guide = load_guide()

    assert problem["id"] == PROBLEM_ID
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 32
    assert set(raw) == {"problem_id", "version", "requirementRevision", "totalSteps", "phases", "steps"}
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES and step.content.strip() for step in guide.steps)

    expected = {
        *(f"legacy-requirement:{index}" for index in range(1, len(problem["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(problem["constraints"]) + 1)),
    }
    actions = {step.id: step for step in guide.steps if step.type in ACTION_TYPES}
    actual = {anchor for step in actions.values() for anchor in step.requirementIds}
    assert actual == expected
    for anchor, step_ids in ANCHOR_ACTIONS.items():
        for step_id in step_ids:
            assert step_id in actions and anchor in actions[step_id].requirementIds

    replay = build_architecture(raw)
    applied = set(replay["appliedStepIds"])
    assert all(step_id in applied for step_ids in ANCHOR_ACTIONS.values() for step_id in step_ids)
    request = make_request(problem, raw, replay)
    assert request["problem"]["id"] == problem["id"]
    assert request["problem"]["title"] == problem["title"]
    assert request["problem"]["description"] == problem["description"]
    assert request["problem"]["requirements"].splitlines() == problem["requirements"]
    assert request["problem"]["constraints"].splitlines() == problem["constraints"]


def test_interface_and_abstract_class_requirement_has_explicit_registration_evidence():
    problem = frozen_problem()
    raw, _ = load_guide()
    requirement_index = next(
        index
        for index, requirement in enumerate(problem["requirements"], start=1)
        if "interface" in requirement.lower() and "abstract class" in requirement.lower()
    )
    anchor = f"legacy-requirement:{requirement_index}"
    evidence = []
    for step in raw["steps"]:
        if step["type"] != "add_component" or anchor not in step["requirementIds"]:
            continue
        component = step.get("component", {})
        properties = component.get("properties", {})
        evidence.append(
            " ".join(
                str(value)
                for value in (
                    step["title"],
                    step["content"],
                    component.get("label", ""),
                    component.get("description", ""),
                    properties.get("purpose", ""),
                )
            ).lower()
        )

    assert any("interface" in text and "abstract" in text for text in evidence)


def test_ordered_actions_form_one_connected_replay_graph():
    raw, guide = load_guide()
    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    node_ids = set()
    edge_ids = set()
    saw_connection = False
    for step in guide.steps:
        if step.type == "add_component":
            assert not saw_connection
            assert step.component is not None
            assert step.component.nodeId not in node_ids
            assert step.component.position.keys() >= {"x", "y"}
            node_ids.add(step.component.nodeId)
        elif step.type == "add_connection":
            saw_connection = True
            assert step.connection is not None
            assert step.connection.edgeId not in edge_ids
            assert step.connection.connectionType in CONNECTION_TYPES
            assert {step.connection.sourceNodeId, step.connection.targetNodeId} <= node_ids
            edge_ids.add(step.connection.edgeId)

    assert len(node_ids) == 12
    assert len(edge_ids) == 16
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    replayed_nodes = {node["id"] for node in architecture["components"]}
    neighbors = {node_id: set() for node_id in replayed_nodes}
    for edge in architecture["connections"]:
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["di_consumer"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == replayed_nodes


def test_uml_catalog_components_and_supported_properties_are_used():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = [step["component"] for step in raw["steps"] if step.get("component")]
    assert {component["componentType"] for component in components} == EXPECTED_COMPONENTS
    assert sum(component["componentType"] == "uml-interface" for component in components) == 2
    for step in raw["steps"]:
        component = step.get("component")
        if component is None:
            continue
        assert component["properties"]["componentName"] == component["label"]
        assert len(component["properties"]["purpose"]) >= 70
        assert component["highlightReason"]
        assert_catalog_properties(catalog, component["componentType"], component["properties"], step["id"])
