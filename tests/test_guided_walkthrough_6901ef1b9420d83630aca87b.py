"""Frozen-brief, catalog, and replay checks for the Facebook Likes review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca87b"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
REQUIREMENTS = [
    "Like and unlike posts in real-time",
    "Show live like count updates",
    "Display who liked the post",
    "Prevent duplicate likes",
    "Handle millions of likes per minute",
    "Support undo functionality",
    "Optimistic UI updates",
]
CONSTRAINTS = [
    "Real-time updates to all viewers",
    "Handle concurrent like/unlike",
    "Eventual consistency acceptable",
    "Low latency for user actions",
    "Prevent like spam",
]
HINTS = [
    "WebSocket for real-time updates",
    "Optimistic concurrency control",
    "Redis for fast counting",
    "Debouncing for rapid clicks",
    "Batch updates for efficiency",
]
STEP_TYPES = {
    "explanation", "add_component", "add_connection", "decision_point", "scale_trigger",
}
CONNECTION_TYPES = {
    "http", "api-call", "database-connection", "message-queue", "data-flow",
}
ANCHORS = {
    *(f"legacy-requirement:{index}" for index in range(1, len(REQUIREMENTS) + 1)),
    *(f"legacy-constraint:{index}" for index in range(1, len(CONSTRAINTS) + 1)),
}


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def frozen_problem():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def test_schema_matches_frozen_brief_and_graph_actions_cover_every_anchor():
    problem = frozen_problem()
    raw, guide = load_guide()

    assert problem["title"] == "Design Facebook Likes Feature with Live Updates"
    assert problem["description"] == (
        "Design a like system with real-time updates showing when users like/unlike content."
    )
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert problem["hints"] == HINTS
    assert problem["has_guided_walkthrough"] is False
    assert guide.problem_id == PROBLEM_ID
    assert guide.version.endswith("-review")
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 42
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES and step.content.strip() for step in guide.steps)

    actual_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert actual_anchors == ANCHORS
    graph_actions = [
        step for step in guide.steps
        if step.type in {"add_component", "add_connection", "decision_point"}
    ]
    assert all(step.requirementIds for step in graph_actions)
    for anchor in ANCHORS:
        assert any(anchor in step.requirementIds for step in graph_actions), (
            f"{anchor} appears only in lesson text, not a graph action or decision"
        )

    request = make_request(problem, raw, build_architecture(raw))
    assert request["problem"]["requirements"].splitlines() == REQUIREMENTS
    assert request["problem"]["constraints"].splitlines() == CONSTRAINTS


def test_phases_ordered_replay_and_all_components_form_one_connected_graph():
    raw, guide = load_guide()
    next_step = 1
    nodes = {}
    edge_ids = set()
    pairs = set()
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    for step in guide.steps:
        if step.type == "add_component":
            assert step.component is not None
            assert step.component.nodeId not in nodes
            assert step.component.position.keys() >= {"x", "y"}
            nodes[step.component.nodeId] = step.component
        elif step.type == "add_connection":
            assert step.connection is not None
            connection = step.connection
            assert connection.edgeId not in edge_ids
            assert connection.connectionType in CONNECTION_TYPES
            assert {connection.sourceNodeId, connection.targetNodeId} <= nodes.keys()
            edge_ids.add(connection.edgeId)
            pairs.add((connection.sourceNodeId, connection.targetNodeId))
        elif step.type == "decision_point":
            assert step.decision is not None and step.decision.alternatives
        elif step.type == "scale_trigger":
            assert step.scaleTrigger is not None

    assert len(nodes) == 11
    assert len(edge_ids) == 14
    assert {
        ("like_client", "like_api"),
        ("like_api", "like_service"),
        ("like_service", "like_store"),
        ("like_store", "outbox_relay"),
        ("outbox_relay", "like_bus"),
        ("like_bus", "like_projector"),
        ("like_projector", "like_counters"),
        ("like_bus", "like_fanout"),
        ("like_fanout", "like_client"),
        ("like_fanout", "delivery_retry"),
        ("delivery_retry", "like_fanout"),
        ("like_service", "like_monitoring"),
        ("like_bus", "like_monitoring"),
        ("like_fanout", "like_monitoring"),
    } == pairs

    first = build_architecture(raw)
    second = build_architecture(raw)
    architecture = first["architecture"]
    replay_nodes = {node["id"] for node in architecture["components"]}
    assert replay_nodes == set(nodes)
    assert len(architecture["connections"]) == len(edge_ids)
    assert first["architecture"] == second["architecture"]

    neighbors = {node_id: set() for node_id in replay_nodes}
    for edge in architecture["connections"]:
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["like_client"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == replay_nodes


def test_component_catalog_types_properties_and_values_are_supported():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = [step["component"] for step in raw["steps"] if step.get("component")]
    assert len(components) == 11

    for step in raw["steps"]:
        component = step.get("component")
        if not component:
            continue
        assert component["properties"]["componentName"] == component["label"]
        assert len(component["properties"]["purpose"]) >= 70
        assert component["highlightReason"]

        component_type = component["componentType"]
        match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
        assert match is not None, f"{step['id']}: unknown catalog id {component_type}"
        block_end = catalog.find("\n  },", match.start())
        assert block_end != -1
        component_block = catalog[match.start():block_end]
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', component_block))
        properties = component["properties"]
        assert set(properties) <= supported, (
            f"{step['id']}: unsupported properties {sorted(set(properties) - supported)}"
        )

        for key, value in properties.items():
            field_start = component_block.index(f'key: "{key}"')
            field_end = component_block.find("},", field_start)
            field = component_block[field_start:field_end]
            field_type = re.search(r'\btype:\s*"([^"]+)"', field)
            assert field_type is not None, f"{step['id']}/{key}: missing catalog property type"
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
                    f"{step['id']}/{key}: unsupported select value {value!r}"
                )


def test_walkthrough_covers_idempotency_ordering_hot_keys_and_degraded_delivery():
    raw, _ = load_guide()
    nodes = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"] if step.get("component")
    }
    authored = " ".join(
        [step["content"] for step in raw["steps"]]
        + [component["properties"]["purpose"] for component in nodes.values()]
        + [
            " ".join(
                [step["decision"]["question"], step["decision"]["chosen"],
                 step["decision"]["chosenReason"]]
                + [alternative["tradeoff"] for alternative in step["decision"]["alternatives"]]
            )
            for step in raw["steps"] if step.get("decision")
        ]
    ).casefold()

    assert "desired-state" in authored
    assert "idempotency key" in authored
    assert "unique (post_id, user_id)" in authored
    assert "likeversion" in authored
    assert "no global order" in authored or "no total order" in authored
    assert "at least once" in authored
    assert "hot key" in authored or "hot-key" in authored
    assert "viral" in authored and "counterbucket" in authored
    assert "coalesce" in authored
    assert "dead-letter" in authored
    assert "reconnect" in authored and "cursor" in authored and "snapshot" in authored
    assert "polling" in authored and "eventual consistency" in authored
    assert "rate limit" in authored and "abuse" in authored
    assert "undo" in authored and "optimistic" in authored
    assert "millions of likes per minute" in authored
    assert "2 million" not in authored and "33,300" not in authored and "5x" not in authored
    assert "p95" not in authored
    assert "privacy" in authored and "assumption" in authored

    replay = build_architecture(raw)
    replay_nodes = {node["id"]: node for node in replay["architecture"]["components"]}
    assert replay_nodes["like_store"]["properties"]["engine"] == "postgresql"
    assert replay_nodes["like_counters"]["properties"]["engine"] == "redis"
    assert "idempotently" in replay_nodes["like_projector"]["properties"]["purpose"].casefold()
    assert replay_nodes["delivery_retry"]["properties"]["backoff"] == "exponential"


def test_anchor_tags_match_the_behavior_each_step_implements():
    raw, _ = load_guide()
    steps = {step["stepNumber"]: set(step["requirementIds"]) for step in raw["steps"]}
    expected = {
        4: {"legacy-requirement:1", "legacy-requirement:3", "legacy-requirement:4", "legacy-constraint:5"},
        6: {"legacy-requirement:1", "legacy-requirement:3", "legacy-requirement:7", "legacy-constraint:4"},
        7: {"legacy-requirement:1", "legacy-requirement:4"},
        8: {"legacy-requirement:1", "legacy-requirement:4", "legacy-requirement:6"},
        10: {"legacy-requirement:1", "legacy-requirement:4", "legacy-constraint:2"},
        13: {"legacy-requirement:2", "legacy-constraint:1", "legacy-constraint:3"},
        16: {"legacy-requirement:1", "legacy-constraint:2", "legacy-constraint:3"},
        19: {"legacy-requirement:2", "legacy-requirement:5", "legacy-constraint:3"},
        21: {"legacy-requirement:2", "legacy-constraint:3"},
        22: {"legacy-requirement:2", "legacy-requirement:5", "legacy-constraint:3"},
        23: {"legacy-requirement:1", "legacy-requirement:2", "legacy-requirement:3", "legacy-requirement:5", "legacy-constraint:1"},
        26: {"legacy-requirement:3"},
        28: {"legacy-requirement:1", "legacy-constraint:1", "legacy-constraint:3"},
        29: {"legacy-requirement:1", "legacy-constraint:1", "legacy-constraint:3"},
        30: {"legacy-requirement:1", "legacy-requirement:4", "legacy-constraint:3"},
        32: {"legacy-requirement:1", "legacy-requirement:2", "legacy-requirement:5", "legacy-constraint:1"},
        36: {"legacy-requirement:1", "legacy-requirement:5", "legacy-constraint:1"},
        39: {"legacy-requirement:1", "legacy-requirement:4", "legacy-constraint:1", "legacy-constraint:3"},
    }
    for step_number, expected_anchors in expected.items():
        assert steps[step_number] == expected_anchors, f"step {step_number} has an unsupported or missing anchor"


def test_concurrency_dedup_optimistic_reconciliation_and_live_fanout_are_distinct():
    raw, _ = load_guide()
    steps = {step["stepNumber"]: step for step in raw["steps"]}
    client = steps[3]["content"].casefold()
    transition = steps[11]["content"].casefold()
    ordering = steps[16]["content"].casefold()
    projector = steps[17]["content"].casefold()
    fanout = steps[25]["content"].casefold()

    assert "one mutation in flight per actor/post" in client
    assert "coalesce later clicks to the latest desired state" in client
    assert "server likeversion" in client and "fresh idempotency key" in client
    assert "do not let a late response roll the ui back" in client
    assert "commit order determines the resulting state" in transition
    assert "different key is a new intent, not a retry" in transition
    assert "does not impose a global order" in ordering and "may lag or arrive out of order" in ordering
    assert "duplicate delivery" in projector and "prevents duplicate active likes" in projector
    assert "not an atomic all-viewer snapshot" in fanout and "count snapshots can lag" in fanout


def test_walkthrough_does_not_invent_numeric_slos_capacity_or_retry_settings():
    raw, _ = load_guide()
    text = json.dumps(raw).casefold()
    for unsupported_claim in ("2 million", "33,300", "5x", "p95"):
        assert unsupported_claim not in text

    components = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"] if step.get("component")
    }
    assert "replication" not in components["like_bus"]["properties"]
    assert "retention" not in components["like_bus"]["properties"]
    assert "maxRetries" not in components["delivery_retry"]["properties"]

