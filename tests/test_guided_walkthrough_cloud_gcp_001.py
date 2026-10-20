"""Structural contract for the cloud_gcp_001 local review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_gcp_001"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
NODE_COUNT = 9
EDGE_COUNT = 14
ROOT_NODE = "gcp001_global_lb"
ANCHORS = {
    "legacy-requirement:1": "gcp001_runtime",
    "legacy-requirement:2": "gcp001_auth",
    "legacy-requirement:3": "gcp001_runtime_to_sql",
    "legacy-requirement:4": "gcp001_cdn_to_lb",
    "legacy-requirement:5": "gcp001_lb_to_runtime",
    "legacy-requirement:6": "gcp001_runtime_to_cache",
    "legacy-requirement:7": "gcp001_runtime_to_monitor",
    "legacy-requirement:8": "gcp001_release_to_sql",
    "legacy-constraint:1": "gcp001_assets_to_cdn",
    "legacy-constraint:2": "gcp001_lb_to_runtime",
    "legacy-constraint:3": "gcp001_sql_to_monitor",
    "legacy-constraint:4": "gcp001_cdn_to_lb",
    "legacy-constraint:5": "gcp001_runtime_to_monitor",
}


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def frozen_brief():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    lines = [f"Title: {problem['title']}", f"Description: {problem['description']}", "Requirements:"]
    lines.extend(f"{index}. {value}" for index, value in enumerate(problem["requirements"], 1))
    lines.append("Constraints:")
    lines.extend(f"{index}. {value}" for index, value in enumerate(problem["constraints"], 1))
    if problem.get("hints"):
        lines.append("Hints:")
        lines.extend(f"{index}. {value}" for index, value in enumerate(problem["hints"], 1))
    return problem, "\n".join(lines)


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"{step_id}: unknown catalog component {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), f"{step_id}: incomplete catalog entry for {component_type}"
    return catalog[match.start() : block_end]


def catalog_options(block: str, key: str) -> set[str] | None:
    marker = re.search(rf'\bkey:\s*"{re.escape(key)}"', block)
    if not marker:
        return None
    remainder = block[marker.end() :]
    next_property = re.search(r'\bkey:\s*"', remainder)
    section = remainder[: next_property.start()] if next_property else remainder
    options = re.search(r"options:\s*\[([\s\S]*?)\]", section)
    return set(re.findall(r'"([^"]+)"', options.group(1))) if options else None


def test_schema_brief_order_and_complete_action_anchors():
    raw, guide = load_guide()
    problem, expected_brief = frozen_brief()
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0-review-draft"
    assert guide.requirementRevision is None
    assert raw["steps"][0]["content"] == expected_brief
    assert guide.totalSteps == len(guide.steps) == 26
    assert [step.stepNumber for step in guide.steps] == list(range(1, 27))
    assert len({step.id for step in guide.steps}) == guide.totalSteps

    expected_ids = {
        *(f"legacy-requirement:{index}" for index in range(1, len(problem["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(problem["constraints"]) + 1)),
    }
    assert set(ANCHORS) == expected_ids
    steps = {step.id: step for step in guide.steps}
    assert {anchor for step in guide.steps for anchor in step.requirementIds} == expected_ids
    for anchor, step_id in ANCHORS.items():
        assert anchor in steps[step_id].requirementIds
        assert steps[step_id].type in {"add_component", "add_connection"}

    expected_start = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == expected_start and start <= end <= guide.totalSteps
        assert all(step.phase == phase.name for step in guide.steps[start - 1 : end])
        expected_start = end + 1
    assert expected_start == guide.totalSteps + 1
    assert {step.type for step in guide.steps} == {"explanation", "add_component", "add_connection"}


def test_catalog_properties_and_connected_replay():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step.get("component")
    }
    assert len(components) == NODE_COUNT
    assert all(component["componentType"] != "custom-component" for component in components.values())
    for step in raw["steps"]:
        component = step.get("component")
        if not component:
            continue
        assert component["properties"]["componentName"] == component["label"]
        assert len(component["properties"]["purpose"]) >= 45
        block = catalog_block(catalog, component["componentType"], step["id"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert set(component["properties"]) <= supported
        for key, value in component["properties"].items():
            options = catalog_options(block, key)
            if options is not None:
                assert value in options, f"{step['id']}: {key}={value!r} is not a catalog option"

    built = build_architecture(raw)
    nodes = {component["id"] for component in built["architecture"]["components"]}
    edges = built["architecture"]["connections"]
    assert len(nodes) == NODE_COUNT
    assert len(edges) == EDGE_COUNT
    assert len(built["appliedStepIds"]) == NODE_COUNT + EDGE_COUNT
    assert len(built["explanationOnlyStepIds"]) == 3
    assert built["provenance"]["problemId"] == PROBLEM_ID
    assert built["provenance"]["walkthroughVersion"] == "1.0-review-draft"

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] and edge["description"] and edge["label"]
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    visited, pending = set(), deque([ROOT_NODE])
    while pending:
        node_id = pending.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        pending.extend(neighbors[node_id] - visited)
    assert visited == nodes
    assert next(c for c in components.values() if c["nodeId"] == "gcp001_sql")["properties"]["type"] == "RDBMS"
