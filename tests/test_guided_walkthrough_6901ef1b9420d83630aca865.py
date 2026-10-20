"""Frozen-brief, catalog, privacy, and connected replay checks for the Yelp/nearby-friends draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca865"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": PROBLEM_ID,
    "title": "Design Yelp or Nearby Friends",
    "description": "Design a location-based service to find nearby places or friends based on geographical location.",
    "requirements": [
        "Find nearby places/friends within radius",
        "Search by location, category, rating",
        "Real-time location updates",
        "Support millions of places/users",
        "Provide ratings and reviews",
        "Handle high query volume",
        "Support different search filters",
        "Mobile-first design",
    ],
    "constraints": [
        "Low latency for location queries",
        "Efficient geospatial indexing",
        "Handle frequent location updates",
        "Support complex queries (distance + rating + price)",
        "Scale globally",
    ],
    "hints": [
        "Geospatial indexing (Quadtree, Geohash)",
        "Separate read and write paths",
        "Cache popular locations",
        "Redis geospatial features",
        "Sharding by geographical region",
    ],
}
STEP_TYPES = {"explanation", "add_component", "add_connection", "decision_point", "scale_trigger"}
CONNECTION_TYPES = {"http", "api-call", "database-connection", "message-queue", "data-flow"}
ACTION_TYPES = {"add_component", "add_connection", "decision_point", "scale_trigger"}
EXPECTED_COMPONENTS = {
    "mobile-app",
    "api-gateway",
    "backend-server",
    "database",
    "search-engine",
    "cache",
    "message-broker",
    "stream-processor",
}
EXPECTED_ACTION_ANCHORS = {
    "nearby_03": {"legacy-requirement:1", "legacy-requirement:3", "legacy-requirement:8"},
    "nearby_04": {"legacy-requirement:1", "legacy-requirement:2", "legacy-requirement:7", "legacy-constraint:1"},
    "nearby_05": {"legacy-requirement:1", "legacy-requirement:2", "legacy-requirement:3", "legacy-requirement:7", "legacy-constraint:1", "legacy-constraint:4"},
    "nearby_06": {"legacy-requirement:5"},
    "nearby_08": {"legacy-requirement:1", "legacy-requirement:2", "legacy-requirement:4", "legacy-requirement:7", "legacy-constraint:2", "legacy-constraint:4"},
    "nearby_09": {"legacy-requirement:1", "legacy-requirement:3", "legacy-requirement:6", "legacy-constraint:1", "legacy-constraint:3"},
    "nearby_10": {"legacy-requirement:3", "legacy-constraint:3"},
    "nearby_11": {"legacy-requirement:3", "legacy-requirement:5", "legacy-constraint:2", "legacy-constraint:3"},
    "nearby_14": {"legacy-requirement:3", "legacy-requirement:8", "legacy-constraint:3"},
    "nearby_15": {"legacy-requirement:1", "legacy-requirement:2", "legacy-requirement:7", "legacy-constraint:1"},
    "nearby_16": {"legacy-requirement:5"},
    "nearby_19": {"legacy-requirement:1", "legacy-requirement:3", "legacy-requirement:6", "legacy-constraint:1", "legacy-constraint:3"},
    "nearby_20": {"legacy-requirement:3", "legacy-constraint:3"},
    "nearby_21": {"legacy-requirement:1", "legacy-requirement:2", "legacy-requirement:7", "legacy-constraint:1", "legacy-constraint:2", "legacy-constraint:4"},
    "nearby_22": {"legacy-requirement:3", "legacy-requirement:5", "legacy-constraint:2", "legacy-constraint:3"},
    "nearby_23": {"legacy-requirement:2", "legacy-requirement:4", "legacy-requirement:5", "legacy-requirement:7", "legacy-constraint:2", "legacy-constraint:4"},
    "nearby_24": {"legacy-requirement:3", "legacy-requirement:6", "legacy-constraint:1", "legacy-constraint:3"},
    "nearby_25": {"legacy-requirement:3", "legacy-constraint:3"},
    "nearby_28": {"legacy-requirement:1", "legacy-requirement:2", "legacy-requirement:7", "legacy-constraint:2", "legacy-constraint:4"},
    "nearby_29": {"legacy-requirement:1", "legacy-requirement:3", "legacy-requirement:6", "legacy-constraint:1", "legacy-constraint:3"},
    "nearby_30": {"legacy-requirement:1", "legacy-requirement:3", "legacy-constraint:3"},
    "nearby_31": {"legacy-requirement:4", "legacy-constraint:5"},
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


def test_schema_order_and_exact_frozen_brief_anchor_coverage():
    problem = frozen_problem()
    raw, guide = load_guide()

    assert {field: problem[field] for field in FROZEN_BRIEF} == FROZEN_BRIEF
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 24
    assert set(raw) == {"problem_id", "version", "requirementRevision", "totalSteps", "phases", "steps"}
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES and step.content.strip() for step in guide.steps)

    expected_anchors = {
        *(f"legacy-requirement:{index}" for index in range(1, len(FROZEN_BRIEF["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(FROZEN_BRIEF["constraints"]) + 1)),
    }
    actual_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert actual_anchors == expected_anchors

    framing = guide.steps[0].content
    for item in [FROZEN_BRIEF["title"], FROZEN_BRIEF["description"], *FROZEN_BRIEF["requirements"],
                 *FROZEN_BRIEF["constraints"], *FROZEN_BRIEF["hints"]]:
        assert item in framing, f"Frozen brief item missing from walkthrough framing: {item}"

    replay = build_architecture(raw)
    applied_step_ids = set(replay["appliedStepIds"])
    for anchor in expected_anchors:
        assert any(
            anchor in step.requirementIds
            and step.type in ACTION_TYPES
            and step.id in applied_step_ids
            for step in guide.steps
        ), f"{anchor} is not tied to an applied component, connection, or explicit decision action"

    request = make_request(problem, raw, replay)
    assert request["problem"]["id"] == FROZEN_BRIEF["id"]
    assert request["problem"]["title"] == FROZEN_BRIEF["title"]
    assert request["problem"]["description"] == FROZEN_BRIEF["description"]
    assert request["problem"]["requirements"].splitlines() == FROZEN_BRIEF["requirements"]
    assert request["problem"]["constraints"].splitlines() == FROZEN_BRIEF["constraints"]


def test_each_action_has_only_its_direct_frozen_brief_anchors():
    _, guide = load_guide()
    actual = {
        step.id: set(step.requirementIds)
        for step in guide.steps
        if step.type in ACTION_TYPES
    }
    assert actual == EXPECTED_ACTION_ANCHORS
    assert guide.steps[0].requirementIds == []
    assert guide.steps[-1].id == "nearby_32"
    assert guide.steps[-1].requirementIds == []

def test_phases_unique_ordered_actions_and_replay_as_one_connected_graph():
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
            assert not saw_connection, "All replayed component additions must precede connection actions"
            assert step.component is not None
            assert step.component.nodeId not in node_ids
            assert step.component.position.keys() == {"x", "y"}
            node_ids.add(step.component.nodeId)
        elif step.type == "add_connection":
            saw_connection = True
            assert step.connection is not None
            assert step.connection.edgeId not in edge_ids
            assert step.connection.connectionType in CONNECTION_TYPES
            assert {step.connection.sourceNodeId, step.connection.targetNodeId} <= node_ids
            edge_ids.add(step.connection.edgeId)
        elif step.type == "decision_point":
            assert step.decision is not None and len(step.decision.alternatives) >= 2
        elif step.type == "scale_trigger":
            assert step.scaleTrigger is not None
            assert step.scaleTrigger.metric and step.scaleTrigger.action and step.scaleTrigger.impact
        if step.componentUpdate is not None:
            assert step.componentUpdate.nodeId in node_ids
            assert step.componentUpdate.properties

    assert len(node_ids) == 8
    assert len(edge_ids) == 10

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    replayed_nodes = {node["id"] for node in architecture["components"]}
    neighbors = {node_id: set() for node_id in replayed_nodes}
    for edge in architecture["connections"]:
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["nearby_mobile"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == replayed_nodes

    expected_applied = {
        step.id
        for step in guide.steps
        if step.type in {"add_component", "add_connection"}
        or (step.type in {"decision_point", "scale_trigger"} and step.componentUpdate is not None)
    }
    assert set(replay["appliedStepIds"]) == expected_applied
    assert len(replay["appliedStepIds"]) + len(replay["explanationOnlyStepIds"]) == guide.totalSteps


def test_existing_catalog_ids_and_supported_properties():
    raw, guide = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step.component.nodeId: step.component
        for step in guide.steps
        if step.component is not None
    }
    assert {component.componentType for component in additions.values()} == EXPECTED_COMPONENTS
    assert all(component_type not in {"custom", "custom-component"} for component_type in EXPECTED_COMPONENTS)

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
            component_type = additions[update["nodeId"]].componentType
            properties = update["properties"]
        else:
            continue
        assert_catalog_properties(catalog, component_type, properties, step["id"])


def test_geo_filter_scale_and_privacy_guidance_survives_replay():
    raw, guide = load_guide()
    replay = build_architecture(raw)
    nodes = {node["id"]: node for node in replay["architecture"]["components"]}
    prose_parts = [step.content for step in guide.steps]
    prose_parts.extend(node["properties"].get("purpose", "") for node in nodes.values())
    for step in guide.steps:
        if step.decision:
            prose_parts.extend((step.decision.question, step.decision.chosen, step.decision.chosenReason))
            prose_parts.extend(f"{alternative.option} {alternative.tradeoff}" for alternative in step.decision.alternatives)
        if step.scaleTrigger:
            prose_parts.extend((step.scaleTrigger.metric, step.scaleTrigger.action, step.scaleTrigger.impact))
    prose = " ".join(prose_parts).casefold()

    assert nodes["nearby_primary"]["properties"]["sharding"] == "Geographic"
    assert nodes["nearby_primary"]["properties"]["crossRegion"] is True
    assert nodes["nearby_primary"]["properties"]["replicationMode"] == "Async"
    assert nodes["nearby_cache"]["properties"]["engine"] == "redis"
    assert nodes["nearby_cache"]["properties"]["cacheStrategy"] == "cache-aside"

    for signal in (
        "geohash",
        "exact distance",
        "requested radius",
        "category",
        "rating",
        "price",
        "redis geo",
        "millions of places/users",
        "low latency for location queries",
        "frequent location updates",
        "scale globally",
        "transactional outbox",
        "opt-in",
        "consent",
        "audience",
        "revocation",
        "expire",
        "no coordinates",
        "freshness",
    ):
        assert signal in prose, f"Missing location-service design signal: {signal}"

    # The frozen brief contains no numeric latency, freshness, retention, radius, or traffic target.
    quantities = re.findall(
        r"\b\d+(?:\.\d+)?\s*(?:ms|milliseconds?|seconds?|minutes?|hours?|days?|rps|qps|km|meters?)\b",
        prose,
    )
    assert quantities == []
    assert re.search(r"\b\d+(?:\.\d+)?\s*%", prose) is None
    assert re.search(r"\bp\d{2}\b", prose) is None
    assert re.search(r"\b(?:radius|within)\s*(?:of|<=|<|=|:)?\s*\d+", prose) is None


def test_proximity_query_is_candidate_complete_then_checks_exact_radius_and_filters():
    _, guide = load_guide()
    by_id = {step.id: step for step in guide.steps}
    index_content = by_id["nearby_08"].content.casefold()
    query_content = by_id["nearby_21"].content.casefold()

    for signal in ("superset", "cell boundaries", "antimeridian", "polar", "exact distance", "false negatives"):
        assert signal in index_content
    for signal in ("full requested radius", "same documented distance model", "requested-radius boundary", "category, rating, and price", "never report a spatial-cell match"):
        assert signal in query_content
    assert "legacy-constraint:2" in by_id["nearby_08"].requirementIds
    assert "legacy-constraint:4" in by_id["nearby_21"].requirementIds


def test_friend_location_privacy_and_staleness_fail_closed_without_numeric_slos():
    _, guide = load_guide()
    by_id = {step.id: step for step in guide.steps}
    update = by_id["nearby_19"].content.casefold()
    query = by_id["nearby_21"].content.casefold()
    cache = by_id["nearby_24"].content.casefold()
    revocation = by_id["nearby_30"].content.casefold()
    event = by_id["nearby_10"].content.casefold()
    push = by_id["nearby_25"].content.casefold()

    for signal in ("current consent", "strictly newer", "server-accepted time", "do not trust device wall-clock", "product-approved freshness/privacy policy", "never append every coordinate", "remove presence on opt-out"):
        assert signal in update
    for signal in ("outside the product-approved freshness window", "recheck current consent/audience", "do not return stale coordinates as current"):
        assert signal in query
    for signal in ("fail closed", "current policy/version", "past its approved freshness window is omitted"):
        assert signal in revocation
    assert "never coordinates" in event
    assert "not coordinates" in by_id["nearby_20"].content.casefold()
    assert "no coordinates" in push
    assert "private friend results out of the shared place-result namespace" in cache

