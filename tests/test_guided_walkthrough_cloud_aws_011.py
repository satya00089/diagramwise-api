"""Structural, catalog, and frozen-brief checks for the leaderboard draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_aws_011"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
CONNECTION_TYPES = {
    "http", "tcp", "websocket", "message-queue", "database-connection",
    "api-call", "data-flow", "event-stream",
}


def _load():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    return raw, GuidedWalkthrough.model_validate(raw), problem


def test_guide_matches_frozen_brief_and_covers_each_requirement_anchor():
    raw, guide, problem = _load()

    assert problem["title"] == "Design a Real-time Gaming Leaderboard System"
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0-review"
    assert guide.totalSteps == len(guide.steps) == 51
    assert [step.stepNumber for step in guide.steps] == list(range(1, 52))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert problem["has_guided_walkthrough"] is False

    expected = {
        *(f"legacy-requirement:{i}" for i in range(1, len(problem["requirements"]) + 1)),
        *(f"legacy-constraint:{i}" for i in range(1, len(problem["constraints"]) + 1)),
    }
    action_types = {"add_component", "add_connection", "decision_point", "scale_trigger"}
    mapped = {anchor for step in guide.steps for anchor in step.requirementIds}
    actionable = {
        anchor for step in guide.steps if step.type in action_types
        for anchor in step.requirementIds
    }
    assert mapped == actionable == expected

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(guide.steps[i - 1].phase == phase.name for i in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1


def test_actions_replay_to_one_connected_graph_with_supported_edges():
    raw, guide, _ = _load()
    replay = build_architecture(raw)
    nodes = {node["id"] for node in replay["architecture"]["components"]}
    edges = replay["architecture"]["connections"]
    assert len(nodes) >= 10
    assert len(edges) >= 15

    known_nodes = set()
    known_edges = set()
    neighbors = {node_id: set() for node_id in nodes}
    directed = {node_id: set() for node_id in nodes}
    for step in guide.steps:
        if step.type == "add_component":
            assert step.component.nodeId not in known_nodes
            known_nodes.add(step.component.nodeId)
        elif step.type == "add_connection":
            edge = step.connection
            assert edge.edgeId not in known_edges
            assert edge.sourceNodeId in known_nodes
            assert edge.targetNodeId in known_nodes
            assert edge.connectionType in CONNECTION_TYPES
            known_edges.add(edge.edgeId)

    for edge in edges:
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
        directed[edge["source"]].add(edge["target"])
    visited = set()
    pending = deque([next(iter(nodes))])
    while pending:
        current = pending.popleft()
        if current not in visited:
            visited.add(current)
            pending.extend(neighbors[current] - visited)
    assert visited == nodes
    assert len(replay["appliedStepIds"]) + len(replay["explanationOnlyStepIds"]) == guide.totalSteps

    def reaches(source, target):
        reachable = set()
        pending = [source]
        while pending:
            current = pending.pop()
            if current not in reachable:
                reachable.add(current)
                pending.extend(directed[current] - reachable)
        return target in reachable

    assert reaches("lb_players", "lb_read_service")
    assert reaches("lb_game_servers", "lb_score_intake")


def test_components_reuse_catalog_ids_and_only_supported_properties():
    raw, _, _ = _load()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")

    for step in raw["steps"]:
        component = step.get("component")
        if component is None:
            continue
        component_type = component["componentType"]
        assert component_type != "custom-component"
        match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
        assert match, f"{step['id']} uses unknown palette ID {component_type!r}"
        block_end = catalog.find("\n  },", match.start())
        block = catalog[match.start() : block_end]
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        properties = component.get("properties", {})
        assert {"componentName", "purpose"} <= properties.keys()
        assert set(properties) <= supported, (
            f"{step['id']} has unsupported properties {sorted(set(properties) - supported)}"
        )


def test_guide_teaches_rank_freshness_and_safe_score_acceptance():
    _, _, _ = _load()
    guide_text = GUIDE_PATH.read_text(encoding="utf-8").casefold()
    for signal in (
        "idempotency", "anti-cheat", "season epoch", "projection freshness",
        "global rank", "friend", "100k", "<10ms", "<50ms",
    ):
        assert signal in guide_text, f"Missing leaderboard decision or target: {signal}"


def test_security_and_ingress_anchors_match_the_step_behavior():
    _, guide, _ = _load()
    steps = {step.id: step for step in guide.steps}

    # Edge filtering, request validation, and request-path telemetry are not
    # themselves gameplay anti-cheat validation; that belongs to score intake.
    for step_id in ("leaderboard_09", "leaderboard_10", "leaderboard_39"):
        assert "legacy-requirement:6" not in steps[step_id].requirementIds
    assert "legacy-requirement:6" in steps["leaderboard_13"].requirementIds
    assert "legacy-requirement:6" in steps["leaderboard_16"].requirementIds

    # A write-ingress quota cannot directly support the read-latency constraint.
    assert "legacy-constraint:1" not in steps["leaderboard_50"].requirementIds


def test_numeric_targets_are_brief_facts_or_labeled_as_observability_examples():
    _, guide, _ = _load()
    steps = {step.id: step for step in guide.steps}
    guide_text = GUIDE_PATH.read_text(encoding="utf-8").casefold()

    assert "100k updates/s" in steps["leaderboard_02"].content
    assert "concurrent users are not a request rate" in steps["leaderboard_02"].content
    assert "1m requests/s" not in guide_text
    assert "p50/p95/p99 are telemetry examples only" in steps["leaderboard_38"].content
    assert "latency percentile/boundary" in steps["leaderboard_45"].content
