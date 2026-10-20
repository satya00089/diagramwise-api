"""Frozen-brief, catalog, action-order, and replay checks for Instagram's local review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca85c"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": PROBLEM_ID,
    "title": "Design Instagram",
    "description": "Design a photo-sharing social media platform like Instagram with feed, stories, and user interactions.",
    "requirements": [
        "Upload and share photos/videos",
        "Follow/unfollow users",
        "Like and comment on posts",
        "Generate personalized feed",
        "Stories feature (24-hour expiry)",
        "Search users and hashtags",
        "Direct messaging",
        "Handle billions of photos",
    ],
    "constraints": [
        "Low latency for feed generation",
        "High availability for uploads",
        "Efficient storage for media files",
        "Real-time notifications",
        "Handle celebrity accounts with millions of followers",
    ],
    "hints": [
        "CDN for image/video delivery",
        "Separate storage for photos and metadata",
        "Fan-out on write vs read for feed",
        "Cache user feeds and popular posts",
        "Image processing pipeline for thumbnails",
    ],
}
BRIEF_FIELDS = tuple(FROZEN_BRIEF)
STEP_TYPES = {"explanation", "add_component", "add_connection", "decision_point", "scale_trigger"}
ACTION_TYPES = {"add_component", "add_connection"}
CONNECTION_TYPES = {"http", "api-call", "database-connection", "message-queue", "data-flow"}
EXPECTED_NODE_IDS = {
    "ig_client", "ig_gateway", "ig_identity", "ig_social_store", "ig_posts", "ig_post_store",
    "ig_media_store", "ig_media_worker", "ig_cdn", "ig_events", "ig_feed", "ig_feed_cache",
    "ig_stories", "ig_story_store", "ig_search", "ig_messages", "ig_message_store", "ig_notifications",
}


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def frozen_problem():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    matches = [problem for problem in problems if problem["id"] == PROBLEM_ID]
    assert len(matches) == 1
    return matches[0]


def test_schema_version_and_exact_repository_frozen_brief():
    problem = frozen_problem()
    raw, guide = load_guide()

    repository_brief = {field: problem[field] for field in BRIEF_FIELDS}
    assert repository_brief == FROZEN_BRIEF
    assert problem["has_guided_walkthrough"] is False
    assert set(raw) == {"problem_id", "version", "requirementRevision", "totalSteps", "phases", "steps"}
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 52
    assert all(step.type in STEP_TYPES and step.content.strip() for step in guide.steps)


def test_phase_ranges_step_order_and_full_actionable_anchor_coverage():
    raw, guide = load_guide()
    expected_anchors = {
        *(f"legacy-requirement:{index}" for index in range(1, len(FROZEN_BRIEF["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(FROZEN_BRIEF["constraints"]) + 1)),
    }
    actual_anchors = {
        anchor for step in raw["steps"] for anchor in step.get("requirementIds", [])
    }
    assert actual_anchors == expected_anchors
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    for step in raw["steps"]:
        assert len(step.get("requirementIds", [])) == len(set(step.get("requirementIds", [])))

    next_number = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_number and start <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_number = end + 1
    assert next_number == guide.totalSteps + 1

    actionable = [step for step in raw["steps"] if step["type"] in ACTION_TYPES]
    for anchor in expected_anchors:
        assert any(anchor in step.get("requirementIds", []) for step in actionable), (
            f"{anchor} is described but not tied to a component or connection action"
        )


def test_component_and_connection_actions_are_unique_and_replay_ordered():
    raw, _ = load_guide()
    node_ids = set()
    edge_ids = set()
    action_step_ids = []

    for step in raw["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            assert component["nodeId"] not in node_ids
            assert set(component["position"]) >= {"x", "y"}
            assert component["highlightReason"].strip()
            node_ids.add(component["nodeId"])
            action_step_ids.append(step["id"])
        elif step["type"] == "add_connection":
            connection = step["connection"]
            assert connection["edgeId"] not in edge_ids
            assert connection["connectionType"] in CONNECTION_TYPES
            assert {connection["sourceNodeId"], connection["targetNodeId"]} <= node_ids, (
                f"{step['id']} connects a component before it is added"
            )
            edge_ids.add(connection["edgeId"])
            action_step_ids.append(step["id"])
        elif step["type"] == "scale_trigger":
            trigger = step["scaleTrigger"]
            assert trigger and trigger["metric"].strip() and trigger["action"].strip() and trigger["impact"].strip()

    assert node_ids == EXPECTED_NODE_IDS
    assert len(node_ids) == 18
    assert len(edge_ids) == 29
    assert action_step_ids == [step["id"] for step in raw["steps"] if step["type"] in ACTION_TYPES]


def test_existing_component_catalog_ids_and_supported_property_keys():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = [step["component"] for step in raw["steps"] if step.get("component")]

    assert len(components) == 18
    # Existing catalog roles cover the client, APIs, services, databases, storage, CDN, cache, broker, and search.
    assert all(component["componentType"] != "custom-component" for component in components)

    for step in raw["steps"]:
        component = step.get("component")
        if not component:
            continue
        assert component["properties"]["componentName"] == component["label"]
        assert len(component["properties"]["purpose"]) >= 70
        match = re.search(rf'\bid:\s*"{re.escape(component["componentType"])}"', catalog)
        assert match is not None, f"{step['id']}: unknown catalog component ID {component['componentType']}"
        block_end = catalog.find("\n  },", match.start())
        assert block_end != -1
        component_block = catalog[match.start():block_end]
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', component_block))
        properties = component["properties"]
        assert set(properties) <= supported, (
            f"{step['id']}: unsupported catalog properties {sorted(set(properties) - supported)}"
        )

        for key, value in properties.items():
            field_start = component_block.index(f'key: "{key}"')
            field_end = component_block.find("},", field_start)
            field = component_block[field_start:field_end]
            field_type = re.search(r'\btype:\s*"([^"]+)"', field)
            assert field_type is not None, f"{step['id']}/{key}: catalog field type is missing"
            if field_type.group(1) in {"text", "textarea"}:
                assert isinstance(value, str)
            elif field_type.group(1) == "boolean":
                assert type(value) is bool
            elif field_type.group(1) == "number":
                assert type(value) in {int, float}
            elif field_type.group(1) == "select":
                options = re.search(r'\boptions:\s*\[([^\]]+)\]', field)
                assert options is not None
                assert value in re.findall(r'"([^"]+)"', options.group(1))


def test_replay_contains_every_action_and_one_connected_architecture():
    raw, _ = load_guide()
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {node["id"]: node for node in architecture["components"]}
    edges = architecture["connections"]

    assert set(nodes) == EXPECTED_NODE_IDS
    assert len(edges) == 29
    expected_actions = [step["id"] for step in raw["steps"] if step["type"] in ACTION_TYPES]
    assert replay["appliedStepIds"] == expected_actions
    assert set(replay["explanationOnlyStepIds"]) == {
        step["id"] for step in raw["steps"] if step["type"] not in ACTION_TYPES
    }

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["type"] in CONNECTION_TYPES
        assert edge["source"] in nodes and edge["target"] in nodes
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["ig_client"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == set(nodes)


def test_instagram_specific_architecture_signals_are_present():
    raw, _ = load_guide()
    authored = json.dumps(raw, ensure_ascii=False).casefold()

    for signal in (
        "billions of photos",
        "24-hour expiry",
        "ttl",
        "thumbnail",
        "hashtag",
        "fan-out-on-write",
        "fan-out-on-read",
        "millions of followers",
        "low-latency feed generation",
        "direct",
        "idempotent",
        "eventual",
    ):
        assert signal in authored, f"missing Instagram design signal: {signal}"
