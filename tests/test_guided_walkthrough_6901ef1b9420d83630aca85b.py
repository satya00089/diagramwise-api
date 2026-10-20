"""Frozen-brief, catalog, and replay checks for the Pastebin review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca85b"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": "6901ef1b9420d83630aca85b",
    "title": "Design Pastebin",
    "description": (
        "Design a web service where users can store plain text and share it "
        "with others via a generated URL."
    ),
    "requirements": [
        "Allow users to paste text content",
        "Generate unique URL for each paste",
        "Support custom URLs/aliases",
        "Set expiration time for pastes",
        "Support syntax highlighting for code",
        "Track view counts",
        "Handle millions of pastes per day",
    ],
    "constraints": [
        "URL should be short and unique",
        "Read heavy system (100:1 read/write ratio)",
        "Low latency for paste retrieval",
        "Support large text files (up to 10MB)",
        "Storage optimization for old/expired pastes",
    ],
    "hints": [
        "Similar to URL shortener design",
        "Use key generation service for unique IDs",
        "Cache popular pastes",
        "Background job for cleanup of expired pastes",
        "Object storage for paste content",
    ],
}
ANCHORS = {
    *(f"legacy-requirement:{index}" for index in range(1, 8)),
    *(f"legacy-constraint:{index}" for index in range(1, 6)),
}
ACTION_TYPES = {"add_component", "add_connection", "decision_point"}
STEP_TYPES = ACTION_TYPES | {"scale_trigger", "explanation"}
CONNECTION_TYPES = {
    "http",
    "api-call",
    "database-connection",
    "tcp",
    "message-queue",
    "data-flow",
}
EXPECTED_PHASES = [
    ("Establish the share contract and request paths", 1, 13),
    ("Reserve generated URLs and aliases safely", 14, 18),
    ("Serve hot pastes and render code safely", 19, 24),
    ("Count views and retire expired content", 25, 36),
    ("Operate and scale from measured behavior", 37, 43),
]


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    return raw, GuidedWalkthrough.model_validate(raw), problem


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"{step_id}: unknown catalog component {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), f"{step_id}: incomplete component catalog entry"
    return catalog[match.start() : block_end]


def assert_supported_catalog_properties(
    catalog: str, component_type: str, properties: dict, step_id: str
) -> None:
    block = catalog_block(catalog, component_type, step_id)
    supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
    assert set(properties) <= supported, (
        f"{step_id}: unsupported {component_type} properties "
        f"{sorted(set(properties) - supported)}"
    )
    for key, value in properties.items():
        field_start = re.search(rf'\{{\s*key:\s*"{re.escape(key)}"', block)
        assert field_start, f"{step_id}: missing catalog property {component_type}.{key}"
        field_end = block.find("},", field_start.start())
        assert field_end > field_start.start(), f"{step_id}: incomplete property {key}"
        field = block[field_start.start() : field_end]
        field_type = re.search(r'\btype:\s*"([^"]+)"', field)
        assert field_type, f"{step_id}: property {component_type}.{key} has no type"
        if field_type.group(1) in {"text", "textarea"}:
            assert isinstance(value, str), f"{step_id}/{key} must be text"
        elif field_type.group(1) == "boolean":
            assert type(value) is bool, f"{step_id}/{key} must be boolean"
        elif field_type.group(1) == "number":
            assert type(value) in {int, float}, f"{step_id}/{key} must be numeric"
        elif field_type.group(1) == "select":
            options = re.search(r'\boptions:\s*\[([^\]]*)\]', field, re.DOTALL)
            assert options, f"{step_id}/{key}: catalog select options are missing"
            allowed = set(re.findall(r'"([^"]+)"', options.group(1)))
            assert value in allowed, f"{step_id}/{key}: unsupported select option {value!r}"


def reachable(start: str, neighbors: dict[str, set[str]]) -> set[str]:
    reached = set()
    pending = deque([start])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    return reached


def test_frozen_brief_matches_repository_snapshot_and_model_schema():
    raw, guide, problem = load_guide()

    snapshot_brief = {key: problem[key] for key in FROZEN_BRIEF}
    assert snapshot_brief == FROZEN_BRIEF
    assert problem["has_guided_walkthrough"] is False
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 43
    assert raw["totalSteps"] == len(raw["steps"])
    assert {step.type for step in guide.steps} == STEP_TYPES
    assert all(step.title.strip() and step.content.strip() for step in guide.steps)


def test_phases_ordered_steps_and_every_anchor_has_an_action():
    _, guide, _ = load_guide()

    assert [(phase.name, *phase.stepRange) for phase in guide.phases] == EXPECTED_PHASES
    assert [step.stepNumber for step in guide.steps] == list(range(1, 44))
    assert len({step.id for step in guide.steps}) == guide.totalSteps

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end <= guide.totalSteps
        assert all(step.phase == phase.name for step in guide.steps[start - 1 : end])
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    all_anchors = set()
    action_anchors = set()
    for step in guide.steps:
        anchors = set(step.requirementIds)
        assert len(anchors) == len(step.requirementIds), f"{step.id}: repeated anchor"
        assert anchors <= ANCHORS, f"{step.id}: unknown anchor(s) {sorted(anchors - ANCHORS)}"
        all_anchors.update(anchors)
        if step.type in ACTION_TYPES:
            action_anchors.update(anchors)
    assert all_anchors == ANCHORS
    assert action_anchors == ANCHORS


def test_actions_use_catalog_components_and_replay_as_one_connected_graph():
    raw, guide, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}
    component_ids = []
    edge_ids = []
    seen_edges = set()

    for step in guide.steps:
        if step.type == "add_component":
            component = step.component
            assert component is not None
            assert component.nodeId not in components
            assert set(component.position) == {"x", "y"}
            assert all(type(value) in {int, float} for value in component.position.values())
            assert component.properties["componentName"] == component.label
            assert len(component.properties["purpose"]) >= 60
            assert component.highlightReason
            assert component.componentType != "custom-component"
            components[component.nodeId] = component
            component_ids.append(component.nodeId)
            assert_supported_catalog_properties(
                catalog, component.componentType, component.properties, step.id
            )
        elif step.type == "add_connection":
            connection = step.connection
            assert connection is not None
            assert connection.edgeId not in seen_edges
            assert connection.sourceNodeId in components
            assert connection.targetNodeId in components
            assert connection.connectionType in CONNECTION_TYPES
            assert connection.label and connection.description
            seen_edges.add(connection.edgeId)
            edge_ids.append(connection.edgeId)
        elif step.type == "decision_point":
            assert step.decision is not None
            assert step.decision.question and step.decision.chosen
            assert step.decision.chosenReason
            assert len(step.decision.alternatives) >= 2
            assert step.componentUpdate is not None

        if step.componentUpdate is not None:
            update = step.componentUpdate
            assert update.nodeId in components, f"{step.id}: update precedes its component"
            assert update.properties
            assert_supported_catalog_properties(
                catalog,
                components[update.nodeId].componentType,
                update.properties,
                step.id,
            )
        if step.type == "scale_trigger":
            assert step.scaleTrigger is not None
            assert step.scaleTrigger.metric and step.scaleTrigger.action and step.scaleTrigger.impact

    assert len(component_ids) == len(set(component_ids)) == 12
    assert len(edge_ids) == len(set(edge_ids)) == 20

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    edges = architecture["connections"]
    assert len(nodes) == 12
    assert len(edges) == 20
    assert len(replay["acceptedDecisions"]) == 7

    neighbors = {node_id: set() for node_id in nodes}
    edge_pairs = set()
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
        edge_pairs.add((edge["source"], edge["target"]))
    assert reachable("paste_client", neighbors) == set(nodes)
    assert {
        ("paste_client", "paste_objects"),
        ("paste_api", "paste_metadata"),
        ("paste_api", "paste_cache"),
        ("paste_edge", "paste_view_queue"),
        ("paste_worker", "paste_analytics_store"),
        ("paste_worker", "paste_objects"),
    } <= edge_pairs


def test_pastebin_quality_signals_cover_contract_and_tradeoffs():
    raw, _, _ = load_guide()
    authored = json.dumps(raw, ensure_ascii=False).casefold()

    for phrase in (
        *[value.casefold() for value in FROZEN_BRIEF["requirements"]],
        *[value.casefold() for value in FROZEN_BRIEF["constraints"]],
        "base36",
        "conditional unique",
        "custom alias",
        "collision",
        "conflict",
        "case-fold",
        "unlisted bearer link",
        "syntax highlighting",
        "escape all pasted text",
        "plain text",
        "cache hits",
        "eventually consistent",
        "deduplicate",
        "successful paste get",
        "expiresat",
        "tombstone",
        "idempotently",
        "older but unexpired",
        "does not define",
        "rather than inventing targets",
    ):
        assert phrase in authored, f"Missing Pastebin design signal: {phrase}"
