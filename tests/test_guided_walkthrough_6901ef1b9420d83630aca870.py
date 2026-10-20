"""Frozen-brief and graph checks for the Weather Application review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca870"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "category": "Consumer Apps",
    "companies": ["Amazon", "Chime", "Facebook", "Hubspot", "Weather.com"],
    "constraints": [
        "Real-time weather updates",
        "Handle location queries efficiently",
        "Third-party API integration",
        "Cache weather data appropriately",
        "Support offline mode",
    ],
    "createdAt": "2025-10-29T10:40:27.393000",
    "description": "Design a weather application that provides current conditions, forecasts, and weather alerts.",
    "difficulty": "Easy",
    "domain": "application",
    "estimatedTime": "30-45 minutes",
    "has_guided_walkthrough": False,
    "hints": [
        "Integrate with weather APIs",
        "Cache weather data with TTL",
        "Geolocation for user location",
        "Push notifications for alerts",
        "CDN for static assets",
    ],
    "id": PROBLEM_ID,
    "requirements": [
        "Show current weather conditions",
        "7-day weather forecast",
        "Hourly weather updates",
        "Weather alerts and warnings",
        "Location-based weather",
        "Support millions of users",
        "Historical weather data",
        "Mobile and web support",
    ],
    "slug": "develop-a-weather-application",
    "tags": ["api-integration", "caching", "location-services", "mobile"],
    "title": "Develop a Weather Application",
    "updatedAt": "2025-10-29T10:40:27.393000",
}

STEP_TYPES = {"explanation", "add_component", "add_connection"}
CONNECTION_TYPES = {
    "http",
    "api-call",
    "database-connection",
    "message-queue",
    "data-flow",
}


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def frozen_problem():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def test_exact_frozen_brief_and_draft_identity():
    problem = frozen_problem()
    assert problem == FROZEN_BRIEF

    raw, guide = load_guide()
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert raw["totalSteps"] == len(raw["steps"]) == 44
    request = make_request(problem, raw, build_architecture(raw))
    assert request["problem"]["requirements"].splitlines() == FROZEN_BRIEF["requirements"]
    assert request["problem"]["constraints"].splitlines() == FROZEN_BRIEF["constraints"]


def test_ordered_phases_and_every_brief_item_anchors_to_graph_actions():
    raw, guide = load_guide()
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step["type"] in STEP_TYPES and step["content"].strip() for step in raw["steps"])

    anchors = {
        *(f"legacy-requirement:{index}" for index in range(1, len(FROZEN_BRIEF["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(FROZEN_BRIEF["constraints"]) + 1)),
    }
    assert {anchor for step in raw["steps"] for anchor in step["requirementIds"]} == anchors
    for step in raw["steps"]:
        assert step["requirementIds"]
        assert set(step["requirementIds"]) <= anchors

    actions = [step for step in raw["steps"] if step["type"] in {"add_component", "add_connection"}]
    assert all(any(anchor in step["requirementIds"] for step in actions) for anchor in anchors)

    expected_range_start = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == expected_range_start <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        expected_range_start = end + 1
    assert expected_range_start == guide.totalSteps + 1


def test_catalog_components_properties_and_replay_connectivity():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step["type"] == "add_component"
    }
    assert len(components) == 14

    for step in raw["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            component_type = component["componentType"]
            properties = component["properties"]
            assert properties["componentName"] == component["label"]
            assert len(properties["purpose"]) >= 70
            assert component["highlightReason"]
        else:
            continue

        match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
        assert match is not None, f"{step['id']}: unknown component catalog ID {component_type}"
        block_end = catalog.find("\n  },", match.start())
        assert block_end != -1
        block = catalog[match.start():block_end]
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert set(properties) <= supported, (
            f"{step['id']}: unsupported properties {sorted(set(properties) - supported)}"
        )

    for component in components.values():
        if component["componentType"] == "custom-component":
            assert component["properties"]["componentType"] in {
                "External Geocoding API",
                "External Weather API",
            }

    replay = build_architecture(raw)
    nodes = {node["id"]: node for node in replay["architecture"]["components"]}
    edges = replay["architecture"]["connections"]
    assert len(nodes) == 14
    assert len(edges) == 21
    assert all(edge["type"] in CONNECTION_TYPES for edge in edges)
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in edges)

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["weather_mobile"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == set(nodes)


def test_assumptions_and_open_questions_are_explicit():
    raw, _ = load_guide()
    text = json.dumps(raw, ensure_ascii=False).casefold()
    for phrase in (
        "design assumptions",
        "not specify",
        "hourly weather updates",
        "freshness",
        "millions of users",
        "provider",
        "retention",
        "offline",
        "remain open decisions",
    ):
        assert phrase in text
