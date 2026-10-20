"""Frozen-live-brief, catalog, requirement-anchor, and replay checks for the draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca887"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
FROZEN_BRIEF_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

STEP_TYPES = {"explanation", "add_component", "add_connection", "decision_point", "scale_trigger"}
CONNECTION_TYPES = {"http", "api-call", "database-connection", "message-queue", "data-flow"}
ACTION_TYPES = {"add_component", "add_connection"}
EXPECTED_COMPONENT_TYPES = {
    "admin-console",
    "api-gateway",
    "auth-service",
    "backend-server",
    "database",
    "message-broker",
    "monitoring",
    "object-storage",
    "processing-worker",
    "queue",
}
ANCHOR_SIGNALS = {
    "legacy-requirement:1": "cluster provisioning and configuration",
    "legacy-requirement:2": "automatic failover and recovery",
    "legacy-requirement:3": "scaling (add/remove nodes)",
    "legacy-requirement:4": "health monitoring and diagnostics",
    "legacy-requirement:5": "data replication management",
    "legacy-requirement:6": "backup and restore operations",
    "legacy-requirement:7": "rolling upgrades",
    "legacy-requirement:8": "multi-tenancy support",
    "legacy-constraint:1": "minimize downtime",
    "legacy-constraint:2": "maintain data consistency",
    "legacy-constraint:3": "network partition",
    "legacy-constraint:4": "efficient resource utilization",
    "legacy-constraint:5": "thousands of clusters",
}


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def load_frozen_brief():
    # Keep expectations tied to the checked-in frozen problem snapshot, not a
    # second hand-copied brief embedded in this test.
    snapshot = json.loads(FROZEN_BRIEF_PATH.read_text(encoding="utf-8"))
    matches = [problem for problem in snapshot if problem.get("id") == PROBLEM_ID]
    assert len(matches) == 1, f"expected one frozen brief for {PROBLEM_ID}"
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


def test_schema_and_every_frozen_live_field_are_preserved():
    raw, guide = load_guide()
    frozen_brief = load_frozen_brief()
    assert guide.problem_id == frozen_brief["id"]
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 47
    assert set(raw) == {"problem_id", "version", "requirementRevision", "totalSteps", "phases", "steps"}
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES and step.content.strip() for step in guide.steps)

    brief = guide.steps[0].content
    display_fields = {
        "id": "ID",
        "slug": "Slug",
        "title": "Title",
        "description": "Description",
        "category": "Category",
        "domain": "Domain",
        "difficulty": "Difficulty",
        "estimatedTime": "Estimated time",
        "createdAt": "Created at",
        "updatedAt": "Updated at",
    }
    for field, label in display_fields.items():
        assert f"{label}: {frozen_brief[field]}" in brief
    for field in ("requirements", "constraints", "hints", "tags", "companies"):
        heading = f"{field.title()}:\n"
        assert heading in brief
        values = frozen_brief[field]
        rendered = [f"- {value}" for value in values]
        positions = [brief.index(value, brief.index(heading)) for value in values]
        assert positions == sorted(positions), f"{field} changed order in the frozen brief"
        assert all(value in brief for value in rendered), f"{field} must remain verbatim"


def test_every_requirement_and_constraint_is_anchored_to_a_replayed_action():
    raw, guide = load_guide()
    frozen_brief = load_frozen_brief()
    expected = {
        *(f"legacy-requirement:{index}" for index in range(1, len(frozen_brief["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(frozen_brief["constraints"]) + 1)),
    }
    assert set(ANCHOR_SIGNALS) == expected
    actual = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert actual == expected

    replay = build_architecture(raw)
    applied_step_ids = set(replay["appliedStepIds"])
    for anchor, signal in ANCHOR_SIGNALS.items():
        anchor_kind, anchor_index = anchor.split(":", maxsplit=1)
        brief_field = "requirements" if anchor_kind == "legacy-requirement" else "constraints"
        source_text = frozen_brief[brief_field][int(anchor_index) - 1].casefold()
        assert signal in source_text, f"{anchor} signal {signal!r} no longer matches the frozen brief"
        backed_steps = [
            step for step in guide.steps
            if anchor in step.requirementIds and step.type in ACTION_TYPES and step.id in applied_step_ids
        ]
        assert backed_steps, f"{anchor} is not tied to an applied graph action"
        observable = " ".join(
            [step.content for step in backed_steps]
            + [
                text
                for step in backed_steps
                for text in (
                    step.component.label if step.component else "",
                    step.component.description or "" if step.component else "",
                    step.component.properties.get("purpose", "") if step.component else "",
                    step.connection.label if step.connection else "",
                    step.connection.description if step.connection else "",
                )
            ]
        ).casefold()
        assert signal in observable, f"{anchor} action does not visibly cover {signal!r}"

    request = make_request(
        frozen_brief,
        raw,
        replay,
    )
    assert request["problem"]["id"] == frozen_brief["id"]
    assert request["problem"]["title"] == frozen_brief["title"]
    assert request["problem"]["description"] == frozen_brief["description"]
    assert request["problem"]["requirements"].splitlines() == frozen_brief["requirements"]
    assert request["problem"]["constraints"].splitlines() == frozen_brief["constraints"]


def test_phase_ranges_and_replayed_architecture_are_complete_and_connected():
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
            assert not saw_connection, "All component actions must precede connection actions"
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

    assert len(node_ids) == 16
    assert len(edge_ids) == 22
    assert {step.component.componentType for step in guide.steps if step.component} == EXPECTED_COMPONENT_TYPES

    architecture = build_architecture(raw)["architecture"]
    neighbors = {node["id"]: set() for node in architecture["components"]}
    for edge in architecture["connections"]:
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["cdb_admin_console"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == set(neighbors)


def test_all_nodes_and_properties_reuse_existing_component_catalog():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = [step["component"] for step in raw["steps"] if step.get("type") == "add_component"]
    assert {component["componentType"] for component in components} == EXPECTED_COMPONENT_TYPES

    for component in components:
        assert component["data"]["originalComponentId"] == component["componentType"]
        assert component["properties"]["componentName"] == component["label"]
        assert len(component["properties"]["purpose"]) >= 70
        assert component["highlightReason"].strip()
        assert_catalog_properties(catalog, component["componentType"], component["properties"], component["nodeId"])
