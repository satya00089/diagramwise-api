"""Frozen-brief, catalog, and connected replay checks for the Twitter review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca85d"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": PROBLEM_ID,
    "title": "Design Twitter for millions of users",
    "description": "Design a microblogging platform like Twitter/X that handles millions of users posting and reading short messages.",
    "requirements": [
        "Post tweets (280 characters)",
        "Follow/unfollow users",
        "Generate timeline/feed",
        "Like and retweet functionality",
        "Trending topics and hashtags",
        "Search tweets and users",
        "Handle millions of tweets per day",
        "Real-time feed updates",
    ],
    "constraints": [
        "High read throughput",
        "Low latency for timeline generation",
        "Handle viral tweets (millions of retweets)",
        "Real-time trending topics",
        "Support global user base",
    ],
    "hints": [
        "Fan-out service for tweet distribution",
        "Cache timelines and trending topics",
        "Separate read and write paths",
        "Use message queues for async processing",
        "Redis for real-time trending analysis",
    ],
}
STEP_TYPES = {"explanation", "add_component", "add_connection", "decision_point", "scale_trigger"}
CONNECTION_TYPES = {"http", "api-call", "database-connection", "message-queue", "data-flow"}
ACTION_TYPES = {"add_component", "add_connection", "decision_point"}


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def frozen_problem():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def test_schema_and_exact_frozen_brief_anchor_coverage():
    problem = frozen_problem()
    raw, guide = load_guide()

    assert {field: problem[field] for field in FROZEN_BRIEF} == FROZEN_BRIEF
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 64
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
    for anchor in expected_anchors:
        assert any(anchor in step.requirementIds and step.type in ACTION_TYPES for step in guide.steps), (
            f"{anchor} is only described, not tied to an actionable step"
        )

    replay = build_architecture(raw)
    request = make_request(problem, raw, replay)
    assert request["problem"]["id"] == FROZEN_BRIEF["id"]
    assert request["problem"]["title"] == FROZEN_BRIEF["title"]
    assert request["problem"]["description"] == FROZEN_BRIEF["description"]
    assert request["problem"]["requirements"].splitlines() == FROZEN_BRIEF["requirements"]
    assert request["problem"]["constraints"].splitlines() == FROZEN_BRIEF["constraints"]


def test_phases_and_ordered_actions_replay_without_forward_references():
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
    for step in guide.steps:
        if step.type == "add_component":
            assert step.component is not None
            component = step.component
            assert component.nodeId not in node_ids
            assert component.position.keys() >= {"x", "y"}
            node_ids.add(component.nodeId)
        elif step.type == "add_connection":
            assert step.connection is not None
            connection = step.connection
            assert connection.edgeId not in edge_ids
            assert connection.connectionType in CONNECTION_TYPES
            assert {connection.sourceNodeId, connection.targetNodeId} <= node_ids
            edge_ids.add(connection.edgeId)
        elif step.type == "decision_point":
            assert step.decision is not None and step.decision.alternatives
            assert step.componentUpdate is not None
            assert step.componentUpdate.nodeId in node_ids
            assert step.componentUpdate.properties
        elif step.type == "scale_trigger":
            assert step.scaleTrigger is not None
        if step.componentUpdate is not None:
            assert step.componentUpdate.nodeId in node_ids

    assert len(node_ids) == 23
    assert len(edge_ids) == 33

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    replayed_nodes = {node["id"] for node in architecture["components"]}
    neighbors = {node_id: set() for node_id in replayed_nodes}
    for edge in architecture["connections"]:
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["tw_web"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == replayed_nodes
    assert len(replay["appliedStepIds"]) + len(replay["explanationOnlyStepIds"]) == guide.totalSteps


def test_existing_catalog_ids_and_supported_properties():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"] if step.get("component")
    }
    assert additions
    # Every concept uses an existing catalog ID, so this draft needs no custom component or custom rationale.
    assert all(component["componentType"] != "custom-component" for component in additions.values())

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

        match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
        assert match is not None, f"{step['id']}: unknown catalog ID {component_type}"
        block_end = catalog.find("\n  },", match.start())
        assert block_end != -1
        component_block = catalog[match.start():block_end]
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', component_block))
        assert set(properties) <= supported, (
            f"{step['id']}: unsupported properties {sorted(set(properties) - supported)}"
        )

        for key, value in properties.items():
            field_start = component_block.index(f'key: "{key}"')
            field_end = component_block.find("},", field_start)
            field = component_block[field_start:field_end]
            field_type = re.search(r'\btype:\s*"([^"]+)"', field)
            assert field_type is not None, f"{step['id']}/{key}: missing catalog field type"
            kind = field_type.group(1)
            if kind in {"text", "textarea"}:
                assert isinstance(value, str)
            elif kind == "boolean":
                assert type(value) is bool
            elif kind == "number":
                assert type(value) in {int, float}
            elif kind == "select":
                options = re.search(r'\boptions:\s*\[([^\]]+)\]', field)
                assert options is not None
                assert value in re.findall(r'"([^"]+)"', options.group(1)), (
                    f"{step['id']}/{key}: {value!r} is not a supported catalog option"
                )


def test_replay_preserves_twitter_specific_design_signals():
    raw, _ = load_guide()
    replay = build_architecture(raw)
    nodes = {node["id"]: node for node in replay["architecture"]["components"]}
    purpose = lambda node_id: nodes[node_id]["properties"]["purpose"].casefold()
    all_prose = " ".join(
        [step["content"] for step in raw["steps"]]
        + [component["properties"]["purpose"] for component in
           (step["component"] for step in raw["steps"] if step.get("component"))]
    ).casefold()

    assert "280-character" in purpose("tw_post_write")
    assert "follow and unfollow" in purpose("tw_social")
    assert "push" in purpose("tw_fanout") and "pull" in purpose("tw_fanout")
    assert "idempotent" in purpose("tw_engagement")
    assert "viral-post counter" in purpose("tw_engagement_db")
    assert "hashtag" in purpose("tw_trend_processor")
    assert nodes["tw_trend_cache"]["properties"]["engine"] == "redis"
    assert nodes["tw_timeline_cache"]["properties"]["engine"] == "redis"
    assert "user search" in purpose("tw_search")
    assert "visibility" in purpose("tw_search")
    assert "feed-ready" in purpose("tw_notifications")
    assert "public application assets" in purpose("tw_cdn")
    assert "personalized timelines" in purpose("tw_cdn")
    assert "read path" in purpose("tw_timeline_read")
    assert "write path" in purpose("tw_post_write")
    hints = " ".join(FROZEN_BRIEF["hints"]).casefold()
    edge_types = {edge["type"] for edge in replay["architecture"]["connections"]}
    assert "fan-out service" in hints and "fan-out" in nodes["tw_fanout"]["label"].casefold()
    assert "cache timelines" in hints and nodes["tw_timeline_cache"]["properties"]["engine"] == "redis"
    assert "separate read and write paths" in hints
    assert "read path" in purpose("tw_timeline_read") and "write path" in purpose("tw_post_write")
    assert "message queues for async processing" in hints and "message-queue" in edge_types
    assert "redis for real-time trending analysis" in hints
    assert "redis" in purpose("tw_trend_cache")
    assert "redis" in all_prose
    assert not re.search(r"\b(?:p\d{2,3}|\d+\s*(?:ms|milliseconds?|seconds?|minutes?|hours?|days?|rps|qps|followers?))\b", all_prose)


def test_canonical_events_are_recoverable_from_transactional_outboxes():
    raw, _ = load_guide()
    replay = build_architecture(raw)
    nodes = {node["id"]: node for node in replay["architecture"]["components"]}
    edges = {edge["id"]: edge for edge in replay["architecture"]["connections"]}

    expected_outbox_edges = {
        "tw_tweet_db_events": "tw_tweet_db",
        "tw_graph_db_events": "tw_graph_db",
        "tw_engagement_db_events": "tw_engagement_db",
    }
    for node_id in expected_outbox_edges.values():
        purpose = nodes[node_id]["properties"]["purpose"].casefold()
        assert "outbox" in purpose and "same transaction" in purpose

    for edge_id, source_id in expected_outbox_edges.items():
        edge = edges[edge_id]
        assert edge["source"] == source_id
        assert edge["target"] == "tw_events"
        assert edge["type"] == "message-queue"
        assert "at least once" in edge["description"].casefold()
        assert "event id" in edge["description"].casefold()
