"""Frozen-brief, catalog, domain-decision, and replay checks for the likes draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca86e"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": "6901ef1b9420d83630aca86e",
    "title": "Count Facebook Likes, Especially for High-Profile Users",
    "description": "Design a system to efficiently count and display likes for posts, especially for viral content.",
    "requirements": [
        "Count likes for posts in real-time",
        "Handle high-profile users with millions of likes",
        "Display like counts accurately",
        "Support undo/unlike functionality",
        "Prevent duplicate likes",
        "Handle billions of likes per day",
        "Show who liked the post",
    ],
    "constraints": [
        "Real-time updates for like counts",
        "Handle viral posts (millions of likes/min)",
        "Eventual consistency acceptable for counts",
        "Prevent like spam/abuse",
        "Low latency for like operations",
    ],
    "hints": [
        "Separate counter and list storage",
        "Eventual consistency for aggregated counts",
        "Sharding by post ID",
        "Redis for real-time counting",
        "Background jobs for aggregation",
    ],
}
STEP_TYPES = {
    "explanation", "add_component", "add_connection", "decision_point", "scale_trigger",
}
ACTION_TYPES = {"add_component", "add_connection", "decision_point", "scale_trigger"}
CONNECTION_TYPES = {
    "http", "api-call", "database-connection", "message-queue", "data-flow",
}
EXPECTED_PHASES = [
    ("Define the state contract and request path", 1, 13),
    ("Persist membership and publish durable transitions", 14, 25),
    ("Serve live counts and reconcile projections", 26, 39),
    ("Control abuse and operate at daily scale", 40, 42),
]


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def frozen_problem():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    matches = [problem for problem in problems if problem["id"] == PROBLEM_ID]
    assert len(matches) == 1
    return matches[0]


def test_review_schema_and_exact_frozen_brief_anchors_and_order():
    problem = frozen_problem()
    raw, guide = load_guide()

    assert {key: problem[key] for key in FROZEN_BRIEF} == FROZEN_BRIEF
    assert problem["has_guided_walkthrough"] is False
    assert set(raw) == {
        "problem_id", "version", "requirementRevision", "totalSteps", "phases", "steps",
    }
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 42
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES and step.content.strip() for step in guide.steps)
    assert all(set(step.model_dump(exclude_none=True)) <= {
        "id", "stepNumber", "phase", "title", "type", "content", "component",
        "connection", "decision", "scaleTrigger", "requirementIds", "componentUpdate",
    } for step in guide.steps)

    assert [
        (phase.name, phase.stepRange[0], phase.stepRange[1]) for phase in guide.phases
    ] == EXPECTED_PHASES
    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    expected_anchors = {
        *(f"legacy-requirement:{index}" for index in range(1, len(FROZEN_BRIEF["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(FROZEN_BRIEF["constraints"]) + 1)),
    }
    actual_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert actual_anchors == expected_anchors
    actionable = [step for step in guide.steps if step.type in ACTION_TYPES]
    for anchor in expected_anchors:
        assert any(anchor in step.requirementIds for step in actionable), (
            f"{anchor} is only described, not tied to a design action"
        )


def test_phases_have_unique_ordered_component_and_edge_actions():
    raw, _ = load_guide()
    nodes = {}
    edges = set()

    for step in raw["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            assert component["nodeId"] not in nodes
            assert component["position"].keys() >= {"x", "y"}
            assert component["properties"]["componentName"] == component["label"]
            assert len(component["properties"]["purpose"]) >= 70
            assert component["highlightReason"].strip()
            nodes[component["nodeId"]] = component
        elif step["type"] == "add_connection":
            connection = step["connection"]
            assert connection["edgeId"] not in edges
            assert connection["connectionType"] in CONNECTION_TYPES
            assert {connection["sourceNodeId"], connection["targetNodeId"]} <= nodes.keys()
            assert connection["label"].strip() and connection["description"].strip()
            edges.add(connection["edgeId"])
        elif step["type"] == "decision_point":
            decision = step["decision"]
            assert decision["chosen"] and decision["chosenReason"]
            assert decision["alternatives"]
            assert all(item["option"] and item["tradeoff"] for item in decision["alternatives"])
        elif step["type"] == "scale_trigger":
            trigger = step["scaleTrigger"]
            assert trigger["metric"] and trigger["action"] and trigger["impact"]

    assert len(nodes) == 13
    assert len(edges) == 19


def test_catalog_ids_and_every_component_property_are_supported():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = [step["component"] for step in raw["steps"] if step.get("component")]
    assert components

    for step in raw["steps"]:
        component = step.get("component")
        if not component:
            continue
        component_type = component["componentType"]
        match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
        assert match is not None, f"{step['id']}: unknown catalog ID {component_type}"
        block_end = catalog.find("\n  },", match.start())
        assert block_end != -1
        component_block = catalog[match.start():block_end]
        property_matches = list(re.finditer(r'\bkey:\s*"([^"]+)"', component_block))
        fields = {}
        for index, property_match in enumerate(property_matches):
            end = property_matches[index + 1].start() if index + 1 < len(property_matches) else len(component_block)
            field = component_block[property_match.start():end]
            fields[property_match.group(1)] = field

        properties = component["properties"]
        assert set(properties) <= set(fields), (
            f"{step['id']}: unsupported properties {sorted(set(properties) - set(fields))}"
        )
        for key, value in properties.items():
            field = fields[key]
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
                assert options is not None, f"{step['id']}/{key}: missing catalog select options"
                assert value in re.findall(r'"([^"]+)"', options.group(1)), (
                    f"{step['id']}/{key}: {value!r} is not a supported catalog value"
                )
            else:
                raise AssertionError(f"{step['id']}/{key}: unsupported catalog field type {kind}")


def test_replay_builds_one_connected_architecture_with_expected_paths():
    raw, _ = load_guide()
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {node["id"]: node for node in architecture["components"]}
    edges = architecture["connections"]
    edge_pairs = {(edge["source"], edge["target"]) for edge in edges}

    assert len(nodes) == 13
    assert len(edges) == 19
    assert nodes["likes_membership"]["properties"]["originalComponentId"] == "database"
    assert nodes["likes_counter_rollups"]["properties"]["originalComponentId"] == "database"
    assert nodes["likes_counter_cache"]["properties"]["engine"] == "redis"
    assert nodes["likes_counter_cache"]["properties"]["originalComponentId"] == "cache"

    for expected in (
        ("likes_client", "likes_gateway"),
        ("likes_gateway", "likes_auth"),
        ("likes_gateway", "likes_api"),
        ("likes_api", "likes_membership"),
        ("likes_membership", "likes_outbox_relay"),
        ("likes_outbox_relay", "likes_event_stream"),
        ("likes_event_stream", "likes_counter_worker"),
        ("likes_counter_worker", "likes_counter_rollups"),
        ("likes_counter_worker", "likes_counter_cache"),
        ("likes_counter_cache", "likes_api"),
        ("likes_counter_worker", "likes_live_fanout"),
        ("likes_live_fanout", "likes_client"),
        ("likes_membership", "likes_reconciler"),
        ("likes_reconciler", "likes_counter_rollups"),
        ("likes_reconciler", "likes_counter_cache"),
    ):
        assert expected in edge_pairs

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["likes_client"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == set(nodes)


def test_high_profile_counter_membership_privacy_and_abuse_decisions():
    raw, _ = load_guide()
    decisions = {
        step["id"]: step["decision"]
        for step in raw["steps"]
        if step.get("type") == "decision_point"
    }
    authored = " ".join(
        [step["content"] for step in raw["steps"]]
        + [step["component"]["properties"]["purpose"] for step in raw["steps"] if step.get("component")]
        + [
            " ".join(
                [decision["chosen"], decision["chosenReason"]]
                + [alternative["tradeoff"] for alternative in decision["alternatives"]]
            )
            for decision in decisions.values()
        ]
    ).casefold()

    assert "exact membership" in authored
    assert "derived" in authored and "approximate" in authored
    assert "idempotency key" in authored
    assert "conditional insert" in authored and "conditional delete" in authored
    assert "no-op" in authored
    assert "atomic operation" in authored and "outbox" in authored
    assert "unique event id" in authored and "checkpoint" in authored
    assert "actor-hash" in authored or "actor hash" in authored
    assert "single hot key" in authored
    assert "reconciliation" in authored and "snapshot" in authored
    assert "visibility" in authored and "block" in authored and "privacy" in authored
    assert "rate limits" in authored and "abuse" in authored
    assert "millions of likes per minute" in authored
    assert "billions of likes per day" in authored
    assert "slo" in authored

    shard_choice = decisions["likes_25"]["chosen"].casefold()
    assert "stable actor-hash buckets" in shard_choice
    assert "sum counter shards" in shard_choice
    assert "membership and count writes" in shard_choice
    idempotency_choice = decisions["likes_12"]["chosen"].casefold()
    assert "desired-state" in idempotency_choice
    assert "only when" in idempotency_choice
    abuse_choice = decisions["likes_40"]["chosen"].casefold()
    assert "identity-aware rate limits" in abuse_choice
    assert "numeric thresholds" in abuse_choice


def test_eventual_consistency_is_limited_to_count_projections():
    raw, _ = load_guide()
    steps = {step["id"]: step for step in raw["steps"]}
    count_consistency_steps = {
        step["id"]
        for step in raw["steps"]
        if "legacy-constraint:3" in step["requirementIds"]
    }
    assert count_consistency_steps == {
        "likes_02", "likes_18", "likes_20", "likes_21", "likes_22", "likes_23",
        "likes_24", "likes_30", "likes_31", "likes_32", "likes_33", "likes_34",
        "likes_35", "likes_37", "likes_38", "likes_39",
    }

    eventual_text = " ".join(
        text.casefold()
        for step in raw["steps"]
        for text in _all_strings(step)
        if re.search(r"eventual(?:ly)?\s+consisten", text, re.IGNORECASE)
    )
    assert "eventual consistency applies to counts only" in eventual_text
    assert "eventually consistent count reads" in eventual_text
    unlike_steps = {
        step["id"] for step in raw["steps"]
        if "legacy-requirement:4" in step["requirementIds"]
    }
    liker_identity_steps = {
        step["id"] for step in raw["steps"]
        if "legacy-requirement:7" in step["requirementIds"]
    }
    duplicate_prevention_steps = {
        step["id"] for step in raw["steps"]
        if "legacy-requirement:5" in step["requirementIds"]
    }
    assert count_consistency_steps.isdisjoint(unlike_steps)
    assert count_consistency_steps.isdisjoint(liker_identity_steps)
    assert count_consistency_steps & duplicate_prevention_steps == {"likes_02"}
    assert "only the displayed aggregate count" in steps["likes_02"]["content"].casefold()
    assert "unlike, duplicate prevention, and liker identity use exact membership" in (
        steps["likes_02"]["content"].casefold()
    )
    assert "membership is not eventually consistent" in steps["likes_31"]["content"].casefold()
    assert "unlike, duplicate prevention, and liker identity continue to use authoritative per-user membership" in (
        steps["likes_39"]["content"].casefold()
    )


def test_anchors_match_the_behavior_each_step_implements_and_no_latency_numbers_are_invented():
    raw, _ = load_guide()
    steps = {step["id"]: step for step in raw["steps"]}

    liker_identity_steps = {
        step["id"] for step in raw["steps"]
        if "legacy-requirement:7" in step["requirementIds"]
    }
    assert liker_identity_steps == {
        "likes_03", "likes_05", "likes_06", "likes_08", "likes_10", "likes_11",
        "likes_13", "likes_42",
    }
    count_reconciliation_steps = {"likes_30", "likes_31", "likes_33", "likes_39"}
    for step_id in count_reconciliation_steps:
        assert "legacy-requirement:5" not in steps[step_id]["requirementIds"]

    authored_text = " ".join(_all_strings(raw))
    invented_latency_or_precision = re.compile(
        r"\bp(?:50|90|95|99)\b|"
        r"\b\d+(?:\.\d+)?\s*(?:ms|milliseconds?|s|secs?|seconds?|mins?|minutes?|hrs?|hours?|rps|qps|percent)\b|"
        r"\b\d+(?:\.\d+)?\s*%",
        re.IGNORECASE,
    )
    assert invented_latency_or_precision.search(authored_text) is None


def _all_strings(value):
    if isinstance(value, dict):
        for nested in value.values():
            yield from _all_strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _all_strings(nested)
    elif isinstance(value, str):
        yield value

