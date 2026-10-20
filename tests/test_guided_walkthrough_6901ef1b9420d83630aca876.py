"""Frozen-brief, catalog, and connected-replay checks for stock-prices guide."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca876"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "category": "Financial Systems",
    "companies": ["Google", "Bloomberg", "Amazon", "Robinhood"],
    "constraints": [
        "Low latency for price updates (<1 second)",
        "Handle market data feeds",
        "Support high read throughput",
        "Accurate price information",
        "Handle market volatility",
    ],
    "createdAt": "2025-10-29T10:40:27.393000",
    "description": "Design a real-time stock price tracking system with market data from global exchanges.",
    "difficulty": "Easy",
    "domain": "application",
    "estimatedTime": "30-45 minutes",
    "has_guided_walkthrough": False,
    "hints": [
        "WebSocket for real-time updates",
        "Market data feed integration",
        "Time-series database for history",
        "Redis for caching latest prices",
        "CDN for static content",
    ],
    "id": PROBLEM_ID,
    "requirements": [
        "Display real-time stock prices",
        "Support multiple stock exchanges",
        "Historical price charts",
        "Price alerts and notifications",
        "Search stocks by symbol/name",
        "Support millions of concurrent users",
        "Market hours and timezone handling",
        "Watchlist functionality",
    ],
    "slug": "design-a-system-to-view-latest-stock-prices-worldwide",
    "tags": ["financial", "real-time", "stock-market", "websockets", "data-feeds"],
    "title": "Design a System to View Latest Stock Prices Worldwide",
    "updatedAt": "2025-10-29T10:40:27.393000",
}

CONNECTION_TYPES = {
    "http",
    "api-call",
    "database-connection",
    "message-queue",
    "data-flow",
}
ANCHORS = {
    *(f"legacy-requirement:{index}" for index in range(1, 9)),
    *(f"legacy-constraint:{index}" for index in range(1, 6)),
}


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def frozen_problem():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def test_exact_frozen_brief_and_walkthrough_schema():
    problem = frozen_problem()
    assert problem == FROZEN_BRIEF

    raw, guide = load_guide()
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 50
    assert raw["totalSteps"] == 50

    request = make_request(problem, raw, build_architecture(raw))
    assert request["problem"]["requirements"].splitlines() == FROZEN_BRIEF["requirements"]
    assert request["problem"]["constraints"].splitlines() == FROZEN_BRIEF["constraints"]


def test_ordering_phases_and_all_brief_anchors_reach_graph_actions():
    raw, guide = load_guide()
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in {"explanation", "add_component", "add_connection"} for step in guide.steps)

    actual_anchors = {anchor for step in raw["steps"] for anchor in step["requirementIds"]}
    assert actual_anchors == ANCHORS
    action_steps = [
        step for step in raw["steps"]
        if step["type"] in {"add_component", "add_connection"}
    ]
    assert all(any(anchor in step["requirementIds"] for step in action_steps) for anchor in ANCHORS)
    assert all(set(step["requirementIds"]) <= ANCHORS for step in raw["steps"])

    expected_start = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == expected_start <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        expected_start = end + 1
    assert expected_start == guide.totalSteps + 1


def test_concurrent_users_requirement_is_anchored_to_socket_capacity_path():
    raw, _ = load_guide()
    requirement_number = FROZEN_BRIEF["requirements"].index(
        "Support millions of concurrent users"
    ) + 1
    anchor = f"legacy-requirement:{requirement_number}"
    steps = {step["id"]: step for step in raw["steps"]}

    assert anchor in steps["stock-ws-fleet"]["requirementIds"]
    assert anchor in steps["stock-pubsub-ws-edge"]["requirementIds"]
    assert anchor in steps["stock-ws-monitor-edge"]["requirementIds"]


def test_catalog_properties_and_ordered_connected_replay():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    node_ids = set()
    components = {}

    for step in raw["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            node_id = component["nodeId"]
            assert node_id not in node_ids
            node_ids.add(node_id)
            components[node_id] = component
            assert component["properties"]["componentName"] == component["label"]
            assert len(component["properties"]["purpose"]) >= 70
            assert component["highlightReason"]

            match = re.search(rf'\bid:\s*"{re.escape(component["componentType"])}"', catalog)
            assert match is not None, f"{step['id']}: unknown catalog ID {component['componentType']}"
            block_end = catalog.find("\n  },", match.start())
            assert block_end != -1
            block = catalog[match.start():block_end]
            supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
            unsupported = set(component["properties"]) - supported
            assert not unsupported, f"{step['id']}: unsupported properties {sorted(unsupported)}"

        elif step["type"] == "add_connection":
            connection = step["connection"]
            assert connection["sourceNodeId"] in node_ids
            assert connection["targetNodeId"] in node_ids
            assert connection["connectionType"] in CONNECTION_TYPES

    assert len(components) == 18
    replay = build_architecture(raw)
    nodes = {node["id"]: node for node in replay["architecture"]["components"]}
    edges = replay["architecture"]["connections"]
    assert len(nodes) == 18
    assert len(edges) == 28
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in edges)

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["stock_web_app"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == set(nodes)


def test_assumptions_and_open_questions_are_labeled():
    raw, _ = load_guide()
    text = json.dumps(raw, ensure_ascii=False).casefold()
    for phrase in (
        "design assumptions",
        "open questions",
        "not specified",
        "not derived requirements",
        "under-one-second",
        "exchange-local calendar",
        "licensed",
        "capacity claims",
    ):
        assert phrase in text
