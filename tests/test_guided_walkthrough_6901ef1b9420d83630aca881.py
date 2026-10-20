"""Frozen-live-brief, catalog, coverage, and replay checks for external sorting."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca881"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
FROZEN_BRIEFS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
PROBLEM_SNAPSHOT_FIELDS = (
    "id",
    "title",
    "description",
    "requirements",
    "constraints",
    "hints",
    "slug",
    "has_guided_walkthrough",
)
CONNECTION_TYPES = {"http", "api-call", "database-connection", "message-queue", "data-flow"}
COVERAGE_EVIDENCE = {
    "legacy-requirement:1": ("larger than available memory", "external merge sort"),
    "legacy-requirement:2": ("different data types", "comparator"),
    "legacy-requirement:3": ("efficient disk i/o operations", "sequential"),
    "legacy-requirement:4": ("parallel processing support", "independent"),
    "legacy-requirement:5": ("terabytes of data", "object storage"),
    "legacy-requirement:6": ("time complexity", "o(n log n)"),
    "legacy-requirement:7": ("custom sorting keys", "same versioned comparator"),
    "legacy-constraint:1": ("limited memory availability", "bounded"),
    "legacy-constraint:2": ("large disk space required", "object storage"),
    "legacy-constraint:3": ("minimize disk i/o operations", "sequential"),
    "legacy-constraint:4": ("data that doesn't fit in ram", "never materialized in ram"),
    "legacy-constraint:5": ("efficient merge operations", "k-way merge"),
}


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def load_frozen_problem():
    rows = json.loads(FROZEN_BRIEFS_PATH.read_text(encoding="utf-8"))
    matches = [problem for problem in rows if problem["id"] == PROBLEM_ID]
    assert len(matches) == 1, f"Expected one frozen brief for {PROBLEM_ID}"
    return matches[0]


def expected_anchors(problem):
    return {
        *(f"legacy-requirement:{index}" for index in range(1, len(problem["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(problem["constraints"]) + 1)),
    }


def test_candidate_preserves_exact_live_problem_fields_and_schema():
    raw, guide = load_guide()
    frozen_problem = load_frozen_problem()

    assert raw["problemSnapshot"] == {
        field: frozen_problem[field] for field in PROBLEM_SNAPSHOT_FIELDS
    }
    assert guide.problem_id == frozen_problem["id"]
    assert guide.version == "1.0.0-review-draft"
    assert guide.totalSteps == len(guide.steps) == 40
    assert guide.requirementRevision is None


def test_every_requirement_and_constraint_has_actionable_observable_coverage():
    raw, guide = load_guide()
    frozen_problem = load_frozen_problem()
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in {"explanation", "add_component", "add_connection"} for step in guide.steps)

    actual_anchors = {anchor for step in raw["steps"] for anchor in step["requirementIds"]}
    expected = expected_anchors(frozen_problem)
    assert set(COVERAGE_EVIDENCE) == expected
    assert actual_anchors == expected
    action_steps = [step for step in raw["steps"] if step["type"] in {"add_component", "add_connection"}]
    for anchor, phrases in COVERAGE_EVIDENCE.items():
        anchored_actions = [step for step in action_steps if anchor in step["requirementIds"]]
        assert anchored_actions, f"{anchor} is not tied to an observable component/connection action"
        evidence_text = json.dumps(anchored_actions, ensure_ascii=False).casefold()
        assert all(phrase in evidence_text for phrase in phrases), f"{anchor} lacks explicit evidence: {phrases}"
    assert all(set(step["requirementIds"]) <= expected for step in raw["steps"])

    expected_start = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == expected_start <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        expected_start = end + 1
    assert expected_start == guide.totalSteps + 1


def test_supported_catalog_components_properties_and_connected_replay():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}
    node_ids = set()

    for step in raw["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            node_id = component["nodeId"]
            assert node_id not in node_ids
            node_ids.add(node_id)
            components[node_id] = component
            assert component["properties"]["componentName"] == component["label"]
            assert len(component["properties"]["purpose"]) >= 70

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

    assert len(components) == 10
    assert {component["componentType"] for component in components.values()} == {
        "web-app", "api-gateway", "backend-server", "database", "object-storage",
        "queue", "processing-worker", "monitoring",
    }

    # Values used for catalog select properties must be real options, not invented provider names.
    assert '"Data Processing"' in catalog
    assert '"exponential"' in catalog
    assert '"Prometheus + Grafana"' in catalog

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {node["id"]: node for node in architecture["components"]}
    edges = architecture["connections"]
    assert len(nodes) == len(components)
    assert len(edges) == 19
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in edges)

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["sort_web_app"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == set(nodes)


def test_supplied_hints_appear_in_walkthrough_instruction():
    raw, _ = load_guide()
    content = json.dumps(raw, ensure_ascii=False).casefold()
    for phrase in (
        "external merge sort",
        "divide data into chunks",
        "sort chunks in memory",
        "merge sorted chunks using k-way merge",
        "mapreduce",
    ):
        assert phrase in content
