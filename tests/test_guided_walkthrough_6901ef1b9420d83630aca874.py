"""Contract checks for the local Uber rider-matching walkthrough draft."""

import json
from collections import defaultdict, deque
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / "6901ef1b9420d83630aca874.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
COMPONENT_CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
PROBLEM_ID = "6901ef1b9420d83630aca874"

EXPECTED_BRIEF_FIELDS = {
    "id": PROBLEM_ID,
    "slug": "uber-rider-matching",
    "title": "Find a Rider for Uber or Uber Eats",
    "description": "Design a matching algorithm to efficiently connect riders/customers with drivers in real-time.",
    "category": "Location-based Services",
    "difficulty": "Hard",
    "estimatedTime": "60-90 minutes",
    "has_guided_walkthrough": False,
    "requirements": [
        "Match riders with nearby drivers",
        "Optimize for wait time and distance",
        "Handle simultaneous requests",
        "Driver acceptance and timeout",
        "Prioritize based on ratings and surge",
        "Support different service types (pool, premium)",
        "Handle millions of matches per day",
        "Real-time location tracking",
    ],
    "constraints": [
        "Match within seconds",
        "Balance driver utilization",
        "Handle driver rejections",
        "Minimize rider wait time",
        "Fair matching algorithm",
    ],
}


def _read_guide():
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def _read_problem():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def _component_catalog_block(catalog, component_type):
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match, f"Unknown catalog component type: {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end >= 0, f"Could not determine catalog block for {component_type}"
    return catalog[match.start() : block_end]


def test_guide_matches_the_exact_frozen_problem_brief_fields():
    problem = _read_problem()
    assert {key: problem.get(key) for key in EXPECTED_BRIEF_FIELDS} == EXPECTED_BRIEF_FIELDS
    guide = _read_guide()
    assert guide["problem_id"] == problem["id"]
    opening = guide["steps"][0]["content"]
    assert problem["title"] in opening
    assert problem["description"] in opening
    assert all(item in opening for item in problem["requirements"] + problem["constraints"])


def test_guide_conforms_to_guided_walkthrough_schema_and_phase_order():
    guide = _read_guide()
    validated = GuidedWalkthrough.model_validate(guide)
    assert validated.problem_id == PROBLEM_ID
    assert validated.totalSteps == len(validated.steps) == 32
    assert [step.stepNumber for step in validated.steps] == list(range(1, 33))

    next_step = 1
    for phase in validated.phases:
        start, end = phase.stepRange
        assert start == next_step
        assert end >= start
        assert all(validated.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == validated.totalSteps + 1


def test_every_frozen_requirement_and_constraint_is_anchored_to_a_design_action():
    problem = _read_problem()
    guide = _read_guide()
    expected = {
        *(f"legacy-requirement:{index}" for index in range(1, len(problem["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(problem["constraints"]) + 1)),
    }
    action_types = {"add_component", "add_connection", "decision_point", "scale_trigger"}
    covered = {
        anchor
        for step in guide["steps"]
        if step["type"] in action_types
        for anchor in step["requirementIds"]
    }
    assert covered == expected


def test_reviewed_action_anchors_are_directly_supported_by_the_frozen_brief():
    problem = _read_problem()
    steps = {step["id"]: step for step in _read_guide()["steps"]}

    def anchor(field, item):
        index = problem[field].index(item) + 1
        kind = "requirement" if field == "requirements" else "constraint"
        return f"legacy-{kind}:{index}"

    requirements = problem["requirements"]
    constraints = problem["constraints"]
    expected = {
        "urm_13": {anchor("requirements", requirements[2]), anchor("requirements", requirements[5])},
        "urm_18": {
            *(anchor("requirements", requirements[index]) for index in (0, 2, 3, 5)),
            *(anchor("constraints", constraints[index]) for index in (2, 3)),
        },
        "urm_19": {
            anchor("requirements", requirements[2]),
            anchor("requirements", requirements[3]),
            anchor("constraints", constraints[0]),
        },
        "urm_20": {
            anchor("requirements", requirements[index]) for index in (0, 1, 5)
        } | {anchor("constraints", constraints[4])},
        "urm_21": {anchor("requirements", requirements[index]) for index in (2, 3)},
        "urm_22": {anchor("requirements", requirements[3]), anchor("constraints", constraints[0])},
        "urm_25": {anchor("requirements", requirements[index]) for index in (0, 3)},
        "urm_26": {anchor("requirements", requirements[3]), anchor("constraints", constraints[2])},
        "urm_27": {anchor("requirements", requirements[index]) for index in (2, 3)},
        "urm_29": {
            *(anchor("requirements", requirements[index]) for index in (1, 7)),
            *(anchor("constraints", constraints[index]) for index in (0, 1, 3, 4)),
        },
        "urm_30": {anchor("requirements", requirements[6]), anchor("constraints", constraints[0])},
        "urm_31": {
            anchor("requirements", requirements[1]),
            *(anchor("constraints", constraints[index]) for index in (0, 1, 3, 4)),
        },
    }

    for step_id, expected_anchors in expected.items():
        assert set(steps[step_id]["requirementIds"]) == expected_anchors, step_id


def test_component_ids_and_property_keys_exist_in_the_existing_catalog():
    guide = _read_guide()
    catalog = COMPONENT_CATALOG_PATH.read_text(encoding="utf-8")
    components = {
        step["component"]["nodeId"]: step["component"]
        for step in guide["steps"]
        if step["type"] == "add_component"
    }

    for step in guide["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            component_type = component["componentType"]
            properties = component.get("properties", {})
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            component = components[update["nodeId"]]
            component_type = component["componentType"]
            properties = update.get("properties", {})
        else:
            continue

        block = _component_catalog_block(catalog, component_type)
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert set(properties) <= supported
        if step["type"] == "add_component":
            assert {"componentName", "purpose"} <= set(properties)


def test_ordered_replay_produces_one_connected_architecture():
    guide = _read_guide()
    built = build_architecture(guide)
    architecture = built["architecture"]
    components = architecture["components"]
    connections = architecture["connections"]

    assert len(components) == 10
    assert len(connections) == 15
    adjacency = defaultdict(set)
    for connection in connections:
        adjacency[connection["source"]].add(connection["target"])
        adjacency[connection["target"]].add(connection["source"])

    start = components[0]["id"]
    reached = {start}
    pending = deque([start])
    while pending:
        for neighbor in adjacency[pending.popleft()] - reached:
            reached.add(neighbor)
            pending.append(neighbor)
    assert reached == {component["id"] for component in components}
