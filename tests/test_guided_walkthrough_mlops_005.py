"""Frozen-brief and replay contract for the model-retraining walkthrough."""

from collections import deque
import json
from pathlib import Path

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "mlops_005"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
ACTION_TYPES = {"add_component", "add_connection", "update_component"}


def test_retraining_walkthrough_preserves_brief_and_replays_one_connected_design():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    brief = next(problem for problem in problems if problem["id"] == PROBLEM_ID)
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    guide = GuidedWalkthrough.model_validate(raw)

    assert guide.problem_id == PROBLEM_ID
    assert guide.totalSteps == len(guide.steps)
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    opening = guide.steps[0].content
    assert brief["title"] in opening
    assert brief["description"] in opening
    for item in (*brief["requirements"], *brief["constraints"], *brief["hints"]):
        assert item in opening

    anchors = {
        *(f"legacy-requirement:{index}" for index in range(1, len(brief["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(brief["constraints"]) + 1)),
    }
    mapped = {anchor for step in guide.steps for anchor in step.requirementIds}
    actionable = {
        anchor
        for step in guide.steps
        if step.type in ACTION_TYPES
        for anchor in step.requirementIds
    }
    assert mapped == actionable == anchors

    replay = build_architecture(raw)
    graph = replay["architecture"]
    nodes = {component["id"] for component in graph["components"]}
    edges = graph["connections"]
    assert len(nodes) >= 8
    assert len(edges) >= len(nodes)
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in edges)

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque([next(iter(nodes))])
    while pending:
        node_id = pending.popleft()
        if node_id in reached:
            continue
        reached.add(node_id)
        pending.extend(neighbors[node_id] - reached)
    assert reached == nodes
