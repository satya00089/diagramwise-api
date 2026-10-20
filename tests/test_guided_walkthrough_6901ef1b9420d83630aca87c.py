"""Safety and structural checks for the botnet problem's defensive reframe."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca87c"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
HOLDS_PATH = ROOT / "docs" / "guided-walkthrough-safety-holds.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
EXPECTED_COMPONENTS = {
    "custom-component",
    "firewall",
    "pubsub",
    "log-processing",
    "object-storage",
    "monitoring",
    "notification-service",
}
CONNECTION_TYPES = {"http", "api-call", "database-connection", "message-queue", "data-flow"}
ACTION_TYPES = {"add_component", "add_connection"}


def test_source_brief_is_unchanged_and_candidate_is_explicitly_held():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    assert problem["title"] == "Design a Distributed Botnet"
    assert "Minimize detection" in problem["constraints"]
    assert "Anonymity and stealth considerations" in problem["requirements"]
    assert problem["has_guided_walkthrough"] is False

    holds = json.loads(HOLDS_PATH.read_text(encoding="utf-8"))
    hold = next(item for item in holds["holds"] if item["problemId"] == PROBLEM_ID)
    assert hold["disposition"] == "defensive_reframe_only"
    assert hold["publication"] == "not_published"
    assert hold["aiAssessment"] == "not_run_and_ineligible_against_the_unchanged_offensive_brief"
    assert hold["browserPersistence"] == "not_run"


def test_walkthrough_schema_and_safe_scope_are_explicit():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    guide = GuidedWalkthrough.model_validate(raw)
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-safety-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 34
    assert [step.stepNumber for step in guide.steps] == list(range(1, 35))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert [(phase.stepRange[0], phase.stepRange[1]) for phase in guide.phases] == [
        (1, 8), (9, 18), (19, 27), (28, 34)
    ]
    assert all(
        guide.steps[index - 1].phase == phase.name
        for phase in guide.phases
        for index in range(phase.stepRange[0], phase.stepRange[1] + 1)
    )

    combined = "\n".join(
        [step.title + " " + step.content for step in guide.steps]
        + [step.component.properties.get("purpose", "") for step in guide.steps if step.component]
    ).lower()
    assert "does not teach how to build" in combined
    assert "not eligible for the normal alignment score" in combined
    assert "improve detection coverage" in combined
    assert "distributed hash table" not in combined
    assert "redundant command servers" not in combined
    assert "encrypted communication channels" not in combined


def test_all_legacy_anchors_are_tied_to_defensive_graph_actions():
    guide = GuidedWalkthrough.model_validate_json(GUIDE_PATH.read_text(encoding="utf-8"))
    expected = {
        *(f"legacy-requirement:{index}" for index in range(1, 9)),
        *(f"legacy-constraint:{index}" for index in range(1, 6)),
    }
    action_anchors = {
        anchor
        for step in guide.steps
        if step.type in ACTION_TYPES
        for anchor in step.requirementIds
    }
    assert action_anchors == expected
    assert {anchor for step in guide.steps for anchor in step.requirementIds} == expected


def test_components_are_catalogued_and_replay_as_one_connected_defensive_graph():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    guide = GuidedWalkthrough.model_validate(raw)
    component_steps = [step for step in guide.steps if step.type == "add_component"]
    components = {step.component.nodeId: step.component for step in component_steps}
    assert {component.componentType for component in components.values()} <= EXPECTED_COMPONENTS
    assert len(components) == 12

    for step in component_steps:
        component = step.component
        match = re.search(rf'(?m)^    id:\s*"{re.escape(component.componentType)}"\s*,', catalog)
        assert match, f"{step.id}: component type is absent from the palette"
        entry_end = re.search(r"(?m)^  \},\s*$", catalog[match.end() :])
        assert entry_end, f"{step.id}: catalog block is incomplete"
        block = catalog[match.start() : match.end() + entry_end.start()]
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert set(component.properties) <= supported, (
            f"{step.id}: unsupported properties {set(component.properties) - supported}"
        )

    applied = build_architecture(raw)
    architecture = applied["architecture"]
    node_ids = {node["id"] for node in architecture["components"]}
    assert node_ids == set(components)
    edges = architecture["connections"]
    assert len(edges) >= 14
    neighbors = {node_id: set() for node_id in node_ids}
    for edge in edges:
        assert edge["type"] in CONNECTION_TYPES
        assert edge["source"] in node_ids and edge["target"] in node_ids
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])

    visited = set()
    pending = deque([next(iter(node_ids))])
    while pending:
        current = pending.popleft()
        if current in visited:
            continue
        visited.add(current)
        pending.extend(neighbors[current] - visited)
    assert visited == node_ids
