"""Frozen-brief, catalog, and connected replay checks for the metrics walkthrough."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca880"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
FROZEN_PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
STEP_TYPES = {"explanation", "add_component", "add_connection", "decision_point", "scale_trigger"}
CONNECTION_TYPES = {"http", "api-call", "database-connection", "message-queue", "data-flow"}
ACTION_TYPES = {"add_component", "add_connection", "decision_point"}
EXPECTED_COMPONENT_TYPES = {
    "api-gateway",
    "backend-server",
    "cache",
    "database",
    "loadbalancer",
    "monitoring",
    "notification-service",
    "processing-worker",
    "queue",
    "web-app",
}
ANCHOR_SIGNALS = {
    "legacy-requirement:1": "thousands of servers",
    "legacy-requirement:2": "cpu, memory, disk, and network",
    "legacy-requirement:3": "real-time",
    "legacy-requirement:4": "threshold",
    "legacy-requirement:5": "historical",
    "legacy-requirement:6": "custom metric",
    "legacy-requirement:7": "billions of data points per day",
    "legacy-requirement:8": "dashboard",
    "legacy-constraint:1": "overhead",
    "legacy-constraint:2": "failure",
    "legacy-constraint:3": "scalable",
    "legacy-constraint:4": "real-time",
    "legacy-constraint:5": "time-series",
}


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def load_frozen_brief():
    # Read the checked-in frozen catalog record so this validation stays offline and source-backed.
    problems = json.loads(FROZEN_PROBLEMS_PATH.read_text(encoding="utf-8"))
    matches = [problem for problem in problems if problem.get("id") == PROBLEM_ID]
    assert len(matches) == 1, f"expected one frozen problem record for {PROBLEM_ID}"
    return matches[0]


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
            assert options is not None, f"{step_id}/{key}: catalog select has no options"
            assert value in re.findall(r'"([^"]+)"', options.group(1)), (
                f"{step_id}/{key} is not a supported catalog option"
            )
        elif kind in {"text", "textarea"}:
            assert isinstance(value, str), f"{step_id}/{key} must be text"


def test_schema_and_all_frozen_live_fields_are_preserved_verbatim():
    frozen_brief = load_frozen_brief()
    raw, guide = load_guide()
    assert guide.problem_id == frozen_brief["id"]
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 33
    assert set(raw) == {"problem_id", "version", "requirementRevision", "totalSteps", "phases", "steps"}
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES and step.content.strip() for step in guide.steps)

    frozen_content = guide.steps[0].content
    display_names = {"id": "ID", "slug": "Slug", "title": "Title", "description": "Description"}
    for field, display_name in display_names.items():
        assert f"{display_name}: {frozen_brief[field]}" in frozen_content
    for field in ("requirements", "constraints", "hints"):
        heading = f"{field.title()}:\n"
        assert heading in frozen_content
        values = frozen_brief[field]
        rendered = [f"- {value}" for value in values]
        positions = [frozen_content.index(value, frozen_content.index(heading)) for value in values]
        assert positions == sorted(positions), f"{field} changed order in the frozen brief"
        assert all(value in frozen_content for value in rendered), f"{field} must remain verbatim"


def test_every_requirement_and_constraint_has_action_backed_observable_coverage():
    frozen_brief = load_frozen_brief()
    raw, guide = load_guide()
    expected = {
        *(f"legacy-requirement:{index}" for index in range(1, len(frozen_brief["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(frozen_brief["constraints"]) + 1)),
    }
    actual = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert actual == expected

    replay = build_architecture(raw)
    applied_step_ids = set(replay["appliedStepIds"])
    steps_by_anchor = {
        anchor: [step for step in guide.steps if anchor in step.requirementIds]
        for anchor in expected
    }
    for anchor, anchored_steps in steps_by_anchor.items():
        backed_actions = [
            step for step in anchored_steps
            if step.type in ACTION_TYPES and step.id in applied_step_ids
        ]
        assert backed_actions, f"{anchor} is not tied to an applied design action"
        observable_text = " ".join(
            [step.content for step in backed_actions]
            + [
                text
                for step in backed_actions
                for component in ([step.component] if step.component else [])
                for text in (component.label, component.description or "", component.properties.get("purpose", ""))
            ]
        ).casefold()
        assert ANCHOR_SIGNALS[anchor] in observable_text, (
            f"{anchor} action does not visibly cover {ANCHOR_SIGNALS[anchor]!r}"
        )

    request = make_request(
        {**frozen_brief, "category": "Monitoring", "difficulty": "Hard"},
        raw,
        replay,
    )
    assert request["problem"]["id"] == frozen_brief["id"]
    assert request["problem"]["title"] == frozen_brief["title"]
    assert request["problem"]["description"] == frozen_brief["description"]
    assert request["problem"]["requirements"].splitlines() == frozen_brief["requirements"]
    assert request["problem"]["constraints"].splitlines() == frozen_brief["constraints"]


def test_phase_ranges_and_replayed_architecture_are_well_formed_and_connected():
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
            assert not saw_connection, "All components must precede replayed connection actions"
            assert step.component is not None and step.component.position.keys() >= {"x", "y"}
            assert step.component.nodeId not in node_ids
            node_ids.add(step.component.nodeId)
        elif step.type == "add_connection":
            saw_connection = True
            assert step.connection is not None
            assert step.connection.edgeId not in edge_ids
            assert step.connection.connectionType in CONNECTION_TYPES
            assert {step.connection.sourceNodeId, step.connection.targetNodeId} <= node_ids
            edge_ids.add(step.connection.edgeId)
        elif step.type == "decision_point":
            assert step.decision is not None and step.decision.alternatives
        elif step.type == "scale_trigger":
            assert step.scaleTrigger is not None

    assert len(node_ids) == 11
    assert len(edge_ids) == 14
    assert {step.component.componentType for step in guide.steps if step.component} == EXPECTED_COMPONENT_TYPES

    architecture = build_architecture(raw)["architecture"]
    neighbors = {node["id"]: set() for node in architecture["components"]}
    for edge in architecture["connections"]:
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["pm_hosts"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == set(neighbors)


def test_component_ids_and_property_options_match_the_existing_catalog():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step.get("type") == "add_component"
    }
    assert {component["componentType"] for component in additions.values()} == EXPECTED_COMPONENT_TYPES

    for step in raw["steps"]:
        component = step.get("component")
        if component:
            component_type = component["componentType"]
            properties = component["properties"]
            assert properties["componentName"] == component["label"]
            assert len(properties["purpose"]) >= 70
            assert component["highlightReason"]
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            component_type = additions[update["nodeId"]]["componentType"]
            properties = update["properties"]
        else:
            continue
        assert_catalog_properties(catalog, component_type, properties, step["id"])

