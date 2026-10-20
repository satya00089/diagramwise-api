"""Frozen-brief, schema, catalog, and connected-replay checks for the marketplace draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca872"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

# These fields are copied exactly from the repository's frozen fixture snapshot.
# The fixture's false flag is snapshot evidence only, not a fresh AWS observation.
FROZEN_BRIEF = {
    "id": "6901ef1b9420d83630aca872",
    "title": "Build a Marketplace Feature for Facebook",
    "description": "Design an online marketplace for buying and selling goods locally.",
    "requirements": [
        "List items for sale",
        "Search and browse listings",
        "Location-based results",
        "Messaging between buyers and sellers",
        "Categories and filters",
        "User ratings and reviews",
        "Handle millions of listings",
        "Image upload and gallery",
    ],
    "constraints": [
        "Efficient search and filtering",
        "Prevent fraud and scams",
        "Handle image storage",
        "Support location-based queries",
        "Real-time messaging",
    ],
    "hints": [
        "Elasticsearch for search",
        "Geospatial indexing for location",
        "CDN for images",
        "Message queue for notifications",
        "Recommendation engine",
    ],
}
ANCHORS = {
    *(f"legacy-requirement:{index}" for index in range(1, 9)),
    *(f"legacy-constraint:{index}" for index in range(1, 6)),
}
GRAPH_ACTION_TYPES = {"add_component", "add_connection", "update_component"}
CONNECTION_TYPES = {"http", "api-call", "database-connection", "message-queue", "data-flow"}
EXPECTED_PHASES = [
    ("Frame user goals, assumptions, and scope", 1, 3),
    ("Place the client, entry, and listing/search components", 4, 12),
    ("Complete delivery, communication, and operations components", 13, 19),
    ("Wire listing, search, location, and trust paths", 20, 32),
    ("Wire images and conversations, then review scale and open questions", 33, 47),
]
EXPECTED_COMPONENTS = {
    "marketplace_web_client": "web-app",
    "marketplace_api_gateway": "api-gateway",
    "marketplace_rate_limiter": "rate-limiter",
    "marketplace_identity": "auth-service",
    "marketplace_listing_service": "backend-server",
    "marketplace_listing_store": "database",
    "marketplace_search_index": "search-engine",
    "marketplace_browse_cache": "cache",
    "marketplace_image_store": "object-storage",
    "marketplace_cdn": "cdn",
    "marketplace_messaging_service": "backend-server",
    "marketplace_conversation_store": "database",
    "marketplace_event_broker": "message-broker",
    "marketplace_notifications": "notification-service",
    "marketplace_reviews_service": "backend-server",
    "marketplace_monitoring": "monitoring",
}
EXPECTED_EDGES = {
    ("marketplace_web_client", "marketplace_api_gateway"),
    ("marketplace_api_gateway", "marketplace_rate_limiter"),
    ("marketplace_rate_limiter", "marketplace_identity"),
    ("marketplace_identity", "marketplace_listing_service"),
    ("marketplace_api_gateway", "marketplace_listing_service"),
    ("marketplace_listing_service", "marketplace_listing_store"),
    ("marketplace_listing_service", "marketplace_event_broker"),
    ("marketplace_event_broker", "marketplace_search_index"),
    ("marketplace_api_gateway", "marketplace_browse_cache"),
    ("marketplace_browse_cache", "marketplace_search_index"),
    ("marketplace_search_index", "marketplace_api_gateway"),
    ("marketplace_api_gateway", "marketplace_reviews_service"),
    ("marketplace_reviews_service", "marketplace_listing_store"),
    ("marketplace_listing_service", "marketplace_image_store"),
    ("marketplace_web_client", "marketplace_image_store"),
    ("marketplace_image_store", "marketplace_cdn"),
    ("marketplace_cdn", "marketplace_web_client"),
    ("marketplace_api_gateway", "marketplace_messaging_service"),
    ("marketplace_identity", "marketplace_messaging_service"),
    ("marketplace_messaging_service", "marketplace_conversation_store"),
    ("marketplace_messaging_service", "marketplace_event_broker"),
    ("marketplace_event_broker", "marketplace_notifications"),
    ("marketplace_listing_service", "marketplace_monitoring"),
    ("marketplace_search_index", "marketplace_monitoring"),
    ("marketplace_event_broker", "marketplace_monitoring"),
}


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


def assert_supported_catalog_properties(catalog: str, component_type: str, properties: dict, step_id: str):
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


def test_frozen_brief_schema_and_review_draft_identity():
    raw, guide, problem = load_guide()

    assert {key: problem[key] for key in FROZEN_BRIEF} == FROZEN_BRIEF
    assert problem["has_guided_walkthrough"] is False
    assert set(raw) == {"problem_id", "version", "totalSteps", "phases", "steps"}
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 47
    assert [(phase.name, *phase.stepRange) for phase in guide.phases] == EXPECTED_PHASES
    assert all(step.title.strip() and step.content.strip() for step in guide.steps)
    all_content = "\n".join(step.content for step in guide.steps).casefold()
    assert "assumptions:" in all_content
    assert "open questions:" in all_content


def test_steps_are_sequential_and_every_frozen_anchor_reaches_a_graph_action():
    _, guide, _ = load_guide()

    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end <= guide.totalSteps
        assert all(step.phase == phase.name for step in guide.steps[start - 1 : end])
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    seen_anchors = set()
    action_anchors = set()
    for step in guide.steps:
        anchors = set(step.requirementIds)
        assert len(anchors) == len(step.requirementIds), f"{step.id}: repeated anchor"
        assert anchors <= ANCHORS, f"{step.id}: unknown anchors {sorted(anchors - ANCHORS)}"
        seen_anchors.update(anchors)
        if step.type in GRAPH_ACTION_TYPES:
            action_anchors.update(anchors)
    assert seen_anchors == ANCHORS
    assert action_anchors == ANCHORS


def test_catalog_components_properties_and_ordered_replay_form_one_connected_graph():
    raw, guide, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}
    edge_pairs = set()
    edge_ids = set()

    for step in guide.steps:
        if step.type == "add_component":
            component = step.component
            assert component is not None
            assert component.nodeId not in components
            assert set(component.position) == {"x", "y"}
            assert all(type(value) in {int, float} for value in component.position.values())
            assert component.componentType == EXPECTED_COMPONENTS[component.nodeId]
            assert component.componentType != "custom-component"
            assert component.properties["componentName"] == component.label
            assert len(component.properties["purpose"]) >= 70
            assert component.highlightReason
            components[component.nodeId] = component
            assert_supported_catalog_properties(catalog, component.componentType, component.properties, step.id)
        elif step.type == "add_connection":
            connection = step.connection
            assert connection is not None
            assert connection.edgeId not in edge_ids
            assert connection.sourceNodeId in components, f"{step.id}: source component added later"
            assert connection.targetNodeId in components, f"{step.id}: target component added later"
            assert connection.connectionType in CONNECTION_TYPES
            assert connection.label and connection.description
            edge_ids.add(connection.edgeId)
            edge_pairs.add((connection.sourceNodeId, connection.targetNodeId))
        if step.componentUpdate is not None:
            update = step.componentUpdate
            assert update.nodeId in components, f"{step.id}: update precedes its component"
            assert_supported_catalog_properties(
                catalog, components[update.nodeId].componentType, update.properties, step.id
            )

    assert set(components) == set(EXPECTED_COMPONENTS)
    assert edge_pairs == EXPECTED_EDGES

    replay = build_architecture(raw)
    nodes = {component["id"] for component in replay["architecture"]["components"]}
    edges = replay["architecture"]["connections"]
    assert nodes == set(EXPECTED_COMPONENTS)
    assert len(edges) == len(EXPECTED_EDGES) == 25
    assert len(replay["appliedStepIds"]) + len(replay["explanationOnlyStepIds"]) == guide.totalSteps
    replay_pairs = {(edge["source"], edge["target"]) for edge in edges}
    assert replay_pairs == EXPECTED_EDGES

    neighbors = {node_id: set() for node_id in nodes}
    for source, target in replay_pairs:
        neighbors[source].add(target)
        neighbors[target].add(source)
    reached = set()
    pending = deque(["marketplace_web_client"])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    assert reached == nodes
