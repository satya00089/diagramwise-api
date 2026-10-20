"""Focused contract checks for the Flickr/Google Photos walkthrough review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca877"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": "6901ef1b9420d83630aca877",
    "title": "Develop a Photo Sharing Platform like Flickr or Google Photos",
    "description": "Design a platform for uploading, organizing, and sharing photos with albums and search.",
    "requirements": [
        "Upload and store photos",
        "Organize photos in albums",
        "Search photos by tags, location, date",
        "Share albums with users",
        "Auto-backup from devices",
        "Face detection and recognition",
        "Handle billions of photos",
        "Support different resolutions",
    ],
    "constraints": [
        "Efficient storage for large photos",
        "Fast photo retrieval and thumbnails",
        "Support high upload volume",
        "Image processing pipeline",
        "Privacy and permission controls",
    ],
    "hints": [
        "Object storage (S3) for photos",
        "Image processing for thumbnails",
        "Metadata database for search",
        "CDN for photo delivery",
        "Machine learning for tagging",
    ],
    "category": "Media Sharing",
    "difficulty": "Medium",
    "domain": "application",
    "estimatedTime": "45-60 minutes",
    "slug": "develop-a-photo-sharing-platform-like-flickr-or-google-photos",
    "tags": ["photo-sharing", "storage", "cdn", "image-processing", "search"],
    "companies": ["Google", "Doordash", "Amazon", "Uber", "Flickr"],
    # This is the frozen fixture value, not a fresh AWS check.
    "has_guided_walkthrough": False,
}

PHASES = [
    ("Clients, identity, and upload control", 1, 11),
    ("Durable originals and ownership metadata", 12, 18),
    ("Async media processing, index, and delivery", 19, 35),
    ("Scale, privacy, and unresolved decisions", 36, 39),
]
ACTION_TYPES = {"add_component", "add_connection", "update_component"}
CONNECTION_TYPES = {
    "https",
    "http",
    "api-call",
    "database-connection",
    "data-flow",
    "event-stream",
    "message-queue",
}
EXPECTED_COMPONENTS = {
    "photo_mobile_app": "mobile-app",
    "photo_web_app": "web-app",
    "photo_api_gateway": "api-gateway",
    "photo_auth": "auth-service",
    "photo_metadata_api": "backend-server",
    "photo_object_store": "object-storage",
    "photo_metadata_db": "database",
    "photo_media_events": "message-broker",
    "photo_media_worker": "processing-worker",
    "photo_search_index": "search-engine",
    "photo_cdn": "cdn",
    "photo_monitoring": "monitoring",
}


def load_candidate():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    matches = [problem for problem in problems if problem["id"] == PROBLEM_ID]
    assert len(matches) == 1
    return raw, GuidedWalkthrough.model_validate(raw), matches[0]


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"{step_id}: unknown catalog component {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), f"{step_id}: incomplete catalog component"
    return catalog[match.start() : block_end]


def assert_supported_properties(catalog: str, component_type: str, properties: dict, step_id: str):
    block = catalog_block(catalog, component_type, step_id)
    supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
    assert set(properties) <= supported, (
        f"{step_id}: unsupported {component_type} properties "
        f"{sorted(set(properties) - supported)}"
    )

    for key, value in properties.items():
        start = re.search(rf'\{{\s*key:\s*"{re.escape(key)}"', block)
        assert start, f"{step_id}: missing property {component_type}.{key}"
        end = block.find("},", start.start())
        assert end > start.start(), f"{step_id}: incomplete property {key}"
        field = block[start.start() : end]
        kind = re.search(r'\btype:\s*"([^"]+)"', field)
        assert kind, f"{step_id}: missing type for {component_type}.{key}"
        property_type = kind.group(1)
        if property_type in {"text", "textarea"}:
            assert isinstance(value, str), f"{step_id}/{key} must be text"
        elif property_type == "boolean":
            assert type(value) is bool, f"{step_id}/{key} must be boolean"
        elif property_type == "number":
            assert type(value) in {int, float}, f"{step_id}/{key} must be numeric"
        elif property_type == "select":
            options = re.search(r'\boptions:\s*\[([^\]]*)\]', field, re.DOTALL)
            assert options, f"{step_id}/{key}: catalog options are missing"
            allowed = set(re.findall(r'"([^"]+)"', options.group(1)))
            assert value in allowed, f"{step_id}/{key}: unsupported option {value!r}"


def reachable(start: str, neighbors: dict[str, set[str]]) -> set[str]:
    seen = set()
    pending = deque([start])
    while pending:
        current = pending.popleft()
        if current not in seen:
            seen.add(current)
            pending.extend(neighbors[current] - seen)
    return seen


def test_frozen_brief_schema_and_phase_order_are_exact():
    raw, guide, problem = load_candidate()

    assert {key: problem[key] for key in FROZEN_BRIEF} == FROZEN_BRIEF
    assert set(raw) == {
        "problem_id",
        "version",
        "requirementRevision",
        "totalSteps",
        "phases",
        "steps",
    }
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 39
    assert [(phase.name, *phase.stepRange) for phase in guide.phases] == PHASES
    assert [step.stepNumber for step in guide.steps] == list(range(1, 40))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.title.strip() and step.content.strip() for step in guide.steps)

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end <= guide.totalSteps
        assert all(step.phase == phase.name for step in guide.steps[start - 1 : end])
        next_step = end + 1
    assert next_step == guide.totalSteps + 1


def test_every_frozen_requirement_and_constraint_has_an_ordered_action():
    _, guide, problem = load_candidate()
    # The one-based legacy anchor suffix refers to the actual frozen fixture arrays.
    frozen_anchor_text = {
        **{
            f"legacy-requirement:{index}": requirement
            for index, requirement in enumerate(problem["requirements"], start=1)
        },
        **{
            f"legacy-constraint:{index}": constraint
            for index, constraint in enumerate(problem["constraints"], start=1)
        },
    }
    expected = set(frozen_anchor_text)
    seen = set()
    on_actions = set()

    for step in guide.steps:
        anchors = set(step.requirementIds)
        assert len(anchors) == len(step.requirementIds), f"{step.id}: duplicate anchor"
        assert anchors <= expected, (
            f"{step.id}: anchor is not present in the frozen brief "
            f"{anchors - expected}; known anchors: {frozen_anchor_text}"
        )
        seen.update(anchors)
        if step.type in ACTION_TYPES:
            on_actions.update(anchors)

    assert seen == on_actions == expected


def test_tag_search_and_processing_tradeoffs_trace_to_the_frozen_brief():
    raw, _, problem = load_candidate()
    assert problem["requirements"][2] == "Search photos by tags, location, date"
    steps = {step["id"]: step for step in raw["steps"]}
    metadata = steps["photo_13"]
    assumptions = steps["photo_37"]["content"].casefold()
    open_questions = steps["photo_38"]["content"].casefold()

    assert "legacy-requirement:3" in metadata["requirementIds"]
    assert "user-supplied tags" in metadata["content"].casefold()
    assert "machine-learning tagging hint" in metadata["content"].casefold()
    assert "postgresql is a replaceable reference database engine" in assumptions
    assert "model, tag taxonomy, and quality bar" in open_questions


def test_catalog_components_and_properties_replay_as_one_connected_graph():
    raw, guide, _ = load_candidate()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    nodes = {}
    edges = []

    for step in guide.steps:
        if step.type == "add_component":
            component = step.component
            assert component is not None
            assert component.componentType != "custom-component"
            assert component.nodeId not in nodes
            assert set(component.position) == {"x", "y"}
            assert component.properties["componentName"] == component.label
            assert len(component.properties["purpose"]) >= 70
            assert component.highlightReason
            assert component.data["originalComponentId"] == component.componentType
            assert_supported_properties(catalog, component.componentType, component.properties, step.id)
            nodes[component.nodeId] = component
        elif step.type == "add_connection":
            connection = step.connection
            assert connection is not None
            assert connection.sourceNodeId in nodes, f"{step.id}: source must precede edge"
            assert connection.targetNodeId in nodes, f"{step.id}: target must precede edge"
            assert connection.connectionType in CONNECTION_TYPES
            assert connection.label and connection.description
            edges.append(connection)
        elif step.componentUpdate:
            update = step.componentUpdate
            assert update.nodeId in nodes, f"{step.id}: update must follow component"
            assert_supported_properties(
                catalog, nodes[update.nodeId].componentType, update.properties, step.id
            )

    assert {node_id: node.componentType for node_id, node in nodes.items()} == EXPECTED_COMPONENTS
    assert len(edges) == 19
    assert len({edge.edgeId for edge in edges}) == len(edges)
    assert [step.id for step in guide.steps if step.type in ACTION_TYPES] == [
        step["id"] for step in raw["steps"] if step["type"] in ACTION_TYPES
    ]

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    replay_nodes = {component["id"]: component for component in architecture["components"]}
    replay_edges = architecture["connections"]
    assert set(replay_nodes) == set(EXPECTED_COMPONENTS)
    assert len(replay_edges) == len(edges)
    assert replay["appliedStepIds"] == [step.id for step in guide.steps if step.type in ACTION_TYPES]
    assert all(edge["type"] in CONNECTION_TYPES for edge in replay_edges)

    neighbors = {node_id: set() for node_id in replay_nodes}
    pairs = set()
    for edge in replay_edges:
        assert edge["source"] in replay_nodes and edge["target"] in replay_nodes
        pair = frozenset((edge["source"], edge["target"]))
        assert pair not in pairs, "parallel duplicate topology obscures the replay graph"
        pairs.add(pair)
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    assert reachable("photo_mobile_app", neighbors) == set(replay_nodes)
    assert replay_nodes["photo_object_store"]["type"] == "storage"
    assert replay_nodes["photo_metadata_db"]["type"] == "database"


def test_assumptions_and_open_questions_are_explicit_not_frozen_facts():
    raw, _, _ = load_candidate()
    content = "\n".join(step["content"] for step in raw["steps"]).casefold()
    assert "assumptions:" in content
    assert "open questions:" in content
    assert "does not specify dau" in content
    assert "not facts supplied by the problem" in content
