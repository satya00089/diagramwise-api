"""Frozen-brief, component-catalog, and ordered-replay checks for Facebook live comments."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca879"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
TITLE = "Design a Live Comments Feature for Facebook"
DESCRIPTION = "Design a real-time commenting system for posts with live updates and threading."
REQUIREMENTS = [
    "Post and view comments in real-time",
    "Support nested/threaded comments",
    "Like and reply to comments",
    "Edit and delete comments",
    "Handle viral posts with thousands of comments",
    "Spam and profanity filtering",
    "Support millions of comments per day",
    "Pagination for large comment threads",
]
CONSTRAINTS = [
    "Real-time updates for new comments",
    "Handle high write throughput",
    "Support comment ordering (chronological, top)",
    "Moderation capabilities",
    "Low latency for updates",
]
HINTS = [
    "WebSockets for real-time updates",
    "Message queue for comment processing",
    "Nested set model for threaded comments",
    "Cache popular comment threads",
    "Content moderation pipeline",
]
STEP_TYPES = {
    "explanation", "add_component", "add_connection", "decision_point", "scale_trigger",
}
CONNECTION_TYPES = {
    "http", "api-call", "database-connection", "message-queue", "data-flow",
}
def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def frozen_problem():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def brief_anchor(items, kind, statement):
    return f"legacy-{kind}:{items.index(statement) + 1}"


def test_schema_exact_frozen_brief_and_full_anchor_coverage():
    problem = frozen_problem()
    raw, guide = load_guide()

    assert problem["title"] == TITLE
    assert problem["description"] == DESCRIPTION
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert problem["hints"] == HINTS
    assert problem["has_guided_walkthrough"] is False
    assert guide.problem_id == PROBLEM_ID
    assert guide.version.endswith("-review")
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 47
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES and step.content.strip() for step in guide.steps)

    expected_anchors = {
        *(f"legacy-requirement:{index}" for index in range(1, len(problem["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(problem["constraints"]) + 1)),
    }
    actual_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert actual_anchors == expected_anchors
    graph_actions = [step for step in guide.steps if step.type in {"add_component", "add_connection"}]
    for anchor in expected_anchors:
        assert any(anchor in step.requirementIds for step in graph_actions), (
            f"{anchor} is described but is not anchored to an applied graph action"
        )

    scope = raw["steps"][0]["content"].casefold()
    assert "functional requirements" in scope
    assert "nonfunctional requirements" in scope
    assert "no numeric latency" in scope


def test_rate_limiter_anchors_only_the_scale_and_throughput_brief_items():
    problem = frozen_problem()
    raw, _ = load_guide()
    step = next(step for step in raw["steps"] if step["stepNumber"] == 7)

    expected_anchors = {
        brief_anchor(problem["requirements"], "requirement", REQUIREMENTS[4]),
        brief_anchor(problem["requirements"], "requirement", REQUIREMENTS[6]),
        brief_anchor(problem["constraints"], "constraint", CONSTRAINTS[1]),
    }
    assert set(step["requirementIds"]) == expected_anchors
    assert "not a substitute for spam/profanity moderation" in step["content"]


def test_phases_actions_and_replay_form_one_connected_graph():
    raw, _ = load_guide()
    next_step = 1
    nodes = {}
    edges = set()

    for phase in raw["phases"]:
        start, end = phase["stepRange"]
        assert start == next_step and start <= end
        assert all(raw["steps"][index - 1]["phase"] == phase["name"] for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == len(raw["steps"]) + 1

    for step in raw["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            assert component["nodeId"] not in nodes
            assert set(component["position"]) >= {"x", "y"}
            nodes[component["nodeId"]] = component
        elif step["type"] == "add_connection":
            connection = step["connection"]
            assert connection["edgeId"] not in edges
            assert connection["connectionType"] in CONNECTION_TYPES
            assert {connection["sourceNodeId"], connection["targetNodeId"]} <= nodes.keys()
            edges.add(connection["edgeId"])

    assert len(nodes) == 12
    assert len(edges) == 20
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    replay_nodes = {component["id"] for component in architecture["components"]}
    replay_edges = architecture["connections"]
    assert len(replay_nodes) == len(nodes)
    assert len(replay_edges) == len(edges)
    assert set(replay["appliedStepIds"]) == {
        step["id"] for step in raw["steps"] if step["type"] in {"add_component", "add_connection"}
    }

    neighbors = {node_id: set() for node_id in replay_nodes}
    for edge in replay_edges:
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["comment_client"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == replay_nodes

    edge_pairs = {(edge["source"], edge["target"]) for edge in replay_edges}
    assert {
        ("comment_client", "comment_api"),
        ("comment_service", "comment_store"),
        ("comment_outbox_relay", "moderation_queue"),
        ("moderation_queue", "moderation_worker"),
        ("comment_outbox_relay", "comment_events"),
        ("comment_events", "comment_websocket"),
        ("comment_websocket", "comment_client"),
    } <= edge_pairs


def test_component_types_and_editable_properties_match_the_catalog():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    for step in raw["steps"]:
        component = step.get("component")
        if component is None:
            continue
        assert component["componentType"] != "custom-component"
        properties = component["properties"]
        assert properties["componentName"] == component["label"]
        assert len(properties["purpose"]) >= 70
        assert component["highlightReason"]
        match = re.search(rf'\bid:\s*"{re.escape(component["componentType"])}"', catalog)
        assert match is not None, f"{step['id']}: unknown catalog ID {component['componentType']}"
        block_end = catalog.find("\n  },", match.start())
        assert block_end != -1
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', catalog[match.start():block_end]))
        assert set(properties) <= supported, (
            f"{step['id']}: unsupported properties {sorted(set(properties) - supported)}"
        )


def test_walkthrough_explains_moderation_recovery_and_viral_post_tradeoffs():
    raw, _ = load_guide()
    authored_text = " ".join(
        [step["title"] + " " + step["content"] for step in raw["steps"]]
        + [step["component"]["properties"]["purpose"] for step in raw["steps"] if step.get("component")]
        + [
            " ".join(
                [step["decision"]["chosen"], step["decision"]["chosenReason"]]
                + [alternative["tradeoff"] for alternative in step["decision"]["alternatives"]]
            )
            for step in raw["steps"] if step.get("decision")
        ]
        + [
            " ".join([step["scaleTrigger"]["metric"], step["scaleTrigger"]["action"], step["scaleTrigger"]["impact"]])
            for step in raw["steps"] if step.get("scaleTrigger")
        ]
    ).casefold()

    for signal in (
        "transactional outbox", "pending", "dead-letter", "idempotent", "keyset",
        "parent_id", "tombstone", "reconnect", "authoritative", "backpressure",
        "retry-later", "viral post", "partition", "fail closed", "silently discard",
    ):
        assert signal in authored_text, f"missing live-comments design guidance: {signal}"

    assert all(step.get("decision", {}).get("alternatives") for step in raw["steps"] if step["type"] == "decision_point")
    assert all(step.get("scaleTrigger") for step in raw["steps"] if step["type"] == "scale_trigger")
