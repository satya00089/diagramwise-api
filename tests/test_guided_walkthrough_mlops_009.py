"""Focused schema, action-graph, and frozen-brief checks for mlops_009."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "mlops_009"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / "mlops_009.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
CONNECTION_TYPES = {
    "api-call",
    "database-connection",
    "data-flow",
    "event-stream",
}
REQUIREMENT_COUNT = 8
CONSTRAINT_COUNT = 5
FROZEN_PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
EXPECTED_STEP_IDS = [
    "mlops009_scope",
    "mlops009_unknowns",
    "mlops009_run_identity",
    "mlops009_boundaries",
    "mlops009_workspace_ui",
    "mlops009_framework_clients",
    "mlops009_ingestion_api",
    "mlops009_tracking_service",
    "mlops009_metadata_store",
    "mlops009_metric_log",
    "mlops009_metric_store",
    "mlops009_artifact_store",
    "mlops009_materializer",
    "mlops009_search_index",
    "mlops009_realtime_gateway",
    "mlops009_ui_api",
    "mlops009_sdk_api",
    "mlops009_api_tracking",
    "mlops009_tracking_metadata",
    "mlops009_tracking_log",
    "mlops009_log_materializer",
    "mlops009_materializer_metrics",
    "mlops009_api_artifact_control",
    "mlops009_sdk_artifacts",
    "mlops009_metadata_search",
    "mlops009_metrics_search",
    "mlops009_api_search",
    "mlops009_search_workspace",
    "mlops009_collaboration_flow",
    "mlops009_metrics_compare",
    "mlops009_log_realtime",
    "mlops009_realtime_workspace",
    "mlops009_visualizations",
    "mlops009_multinode_semantics",
    "mlops009_reproducibility",
    "mlops009_scale_project",
    "mlops009_scale_latency",
    "mlops009_scale_artifact",
    "mlops009_scale_realtime",
    "mlops009_scale_retention",
    "mlops009_failure_replay",
    "mlops009_consistency_decision",
    "mlops009_acceptance",
    "mlops009_conclusion",
]
EXPECTED_COMPONENT_IDS = [
    "mlops009_workspace",
    "mlops009_framework_clients",
    "mlops009_ingestion_api",
    "mlops009_tracking_service",
    "mlops009_metadata_store",
    "mlops009_metric_log",
    "mlops009_metric_store",
    "mlops009_artifact_store",
    "mlops009_materializer",
    "mlops009_search_index",
    "mlops009_realtime_gateway",
]
EXPECTED_CONNECTIONS = [
    ("mlops009_ui_to_api", "mlops009_workspace", "mlops009_ingestion_api"),
    ("mlops009_sdk_to_api", "mlops009_framework_clients", "mlops009_ingestion_api"),
    ("mlops009_api_to_tracking", "mlops009_ingestion_api", "mlops009_tracking_service"),
    ("mlops009_tracking_to_metadata", "mlops009_tracking_service", "mlops009_metadata_store"),
    ("mlops009_tracking_to_metric_log", "mlops009_tracking_service", "mlops009_metric_log"),
    ("mlops009_log_to_materializer", "mlops009_metric_log", "mlops009_materializer"),
    ("mlops009_materializer_to_metrics", "mlops009_materializer", "mlops009_metric_store"),
    ("mlops009_api_to_artifacts", "mlops009_ingestion_api", "mlops009_artifact_store"),
    ("mlops009_sdk_to_artifacts", "mlops009_framework_clients", "mlops009_artifact_store"),
    ("mlops009_metadata_to_search", "mlops009_metadata_store", "mlops009_search_index"),
    ("mlops009_materializer_to_search", "mlops009_materializer", "mlops009_search_index"),
    ("mlops009_api_to_search", "mlops009_ingestion_api", "mlops009_search_index"),
    ("mlops009_search_to_workspace", "mlops009_search_index", "mlops009_workspace"),
    ("mlops009_metrics_to_api", "mlops009_metric_store", "mlops009_ingestion_api"),
    ("mlops009_log_to_realtime", "mlops009_metric_log", "mlops009_realtime_gateway"),
    ("mlops009_realtime_to_workspace", "mlops009_realtime_gateway", "mlops009_workspace"),
]


def anchors(requirements=(), constraints=()) -> set[str]:
    return {
        *(f"legacy-requirement:{number}" for number in requirements),
        *(f"legacy-constraint:{number}" for number in constraints),
    }


EXPECTED_ACTION_ANCHORS = {
    "mlops009_workspace_ui": anchors((3, 4, 6, 7)),
    "mlops009_framework_clients": anchors((1, 2, 5, 8)),
    "mlops009_ingestion_api": anchors((1, 2, 4, 6, 7), (2, 3)),
    "mlops009_tracking_service": anchors((1, 2, 4, 7, 8)),
    "mlops009_metadata_store": anchors((2, 4, 7), (5,)),
    "mlops009_metric_log": anchors((1, 5), (2, 4)),
    "mlops009_metric_store": anchors((1, 3, 5), (5,)),
    "mlops009_artifact_store": anchors((1,), (3,)),
    "mlops009_materializer": anchors((1, 3, 6), (2,)),
    "mlops009_search_index": anchors((4, 6), (1,)),
    "mlops009_realtime_gateway": anchors((3,), (4,)),
    "mlops009_ui_api": anchors((3, 4, 6, 7)),
    "mlops009_sdk_api": anchors((1, 2, 5, 8)),
    "mlops009_api_tracking": anchors((1, 2, 4, 7)),
    "mlops009_tracking_metadata": anchors((2, 4, 7), (5,)),
    "mlops009_tracking_log": anchors((1, 5), (2, 4)),
    "mlops009_log_materializer": anchors((1, 3, 6), (4,)),
    "mlops009_materializer_metrics": anchors((1, 3, 5), (5,)),
    "mlops009_api_artifact_control": anchors((1,), (3,)),
    "mlops009_sdk_artifacts": anchors((1, 5), (3,)),
    "mlops009_metadata_search": anchors((2, 4, 6), (1,)),
    "mlops009_metrics_search": anchors((6,)),
    "mlops009_api_search": anchors((6,), (1,)),
    "mlops009_search_workspace": anchors((3, 6), (1,)),
    "mlops009_metrics_compare": anchors((3,), (5,)),
    "mlops009_log_realtime": anchors((3,), (4,)),
    "mlops009_realtime_workspace": anchors((3,), (4,)),
}

NUMERIC_TARGET_PATTERN = re.compile(
    r"(?<![\w.])(?:\d+(?:,\d{3})*(?:\.\d+)?(?:k|m|b)?\+?)\s*"
    r"(?:ms|milliseconds?|seconds?|minutes?|hours?|days?|weeks?|months?|years?|"
    r"gb|tb|pb|experiments?|files?|events?|tenants?|workers?)\b",
    re.IGNORECASE,
)


def load_guide() -> dict:
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def load_frozen_problem() -> dict:
    payload = json.loads(FROZEN_PROBLEMS_PATH.read_text(encoding="utf-8"))
    problems = payload if isinstance(payload, list) else payload["problems"]
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def numeric_targets(text: str) -> set[str]:
    return {
        re.sub(r"\s+", " ", match.group()).casefold()
        for match in NUMERIC_TARGET_PATTERN.finditer(text)
    }


def catalog_component_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'(?m)^\s*id:\s*"{re.escape(component_type)}"', catalog)
    assert match, f"unknown component type {component_type!r}"
    end = catalog.find("\n  },", match.start())
    assert end != -1, f"could not find catalog block end for {component_type!r}"
    return catalog[match.start() : end]


def test_schema_phases_and_exact_guided_step_sequence():
    raw = load_guide()
    guide = GuidedWalkthrough.model_validate(raw)

    assert guide.problem_id == PROBLEM_ID
    assert guide.version.endswith("review-draft")
    assert guide.totalSteps == len(guide.steps) == 44
    assert [step.id for step in guide.steps] == EXPECTED_STEP_IDS
    assert [step.stepNumber for step in guide.steps] == list(range(1, 45))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(
        step.type
        in {
            "explanation",
            "add_component",
            "add_connection",
            "decision_point",
            "scale_trigger",
            "conclusion",
        }
        for step in guide.steps
    )

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(guide.steps[number - 1].phase == phase.name for number in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1


def test_action_targets_catalog_properties_and_replay_graph_are_valid():
    raw = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = [step["component"] for step in raw["steps"] if step["type"] == "add_component"]
    connections = [step["connection"] for step in raw["steps"] if step["type"] == "add_connection"]

    assert [component["nodeId"] for component in components] == EXPECTED_COMPONENT_IDS
    assert [
        (edge["edgeId"], edge["sourceNodeId"], edge["targetNodeId"])
        for edge in connections
    ] == EXPECTED_CONNECTIONS

    for component in components:
        block = catalog_component_block(catalog, component["componentType"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert {"componentName", "purpose"} <= set(component["properties"])
        assert set(component["properties"]) <= supported
        assert component["label"].strip()
        assert component["description"].strip()
        assert component["highlightReason"].strip()

    seen_nodes: set[str] = set()
    seen_edges: set[str] = set()
    for step in raw["steps"]:
        if step["type"] == "add_component":
            node_id = step["component"]["nodeId"]
            assert node_id not in seen_nodes
            seen_nodes.add(node_id)
        elif step["type"] == "add_connection":
            edge = step["connection"]
            assert edge["sourceNodeId"] in seen_nodes
            assert edge["targetNodeId"] in seen_nodes
            assert edge["sourceNodeId"] != edge["targetNodeId"]
            assert edge["edgeId"] not in seen_edges
            assert edge["connectionType"] in CONNECTION_TYPES
            seen_edges.add(edge["edgeId"])

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    replay_nodes = {component["id"] for component in architecture["components"]}
    replay_edges = architecture["connections"]
    assert replay_nodes == set(EXPECTED_COMPONENT_IDS)
    assert len(replay_edges) == len(EXPECTED_CONNECTIONS)
    assert set(replay["appliedStepIds"]) == {
        step["id"] for step in raw["steps"] if step["type"] in {"add_component", "add_connection"}
    }
    assert all(edge["source"] in replay_nodes and edge["target"] in replay_nodes for edge in replay_edges)
    assert all(edge["type"] in CONNECTION_TYPES for edge in replay_edges)

    neighbors = {node_id: set() for node_id in replay_nodes}
    for edge in replay_edges:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached: set[str] = set()
    pending = deque([next(iter(replay_nodes))])
    while pending:
        current = pending.popleft()
        if current in reached:
            continue
        reached.add(current)
        pending.extend(neighbors[current] - reached)
    assert reached == replay_nodes


def test_every_frozen_requirement_and_constraint_has_an_applied_action():
    raw = load_guide()
    problem = load_frozen_problem()
    assert len(problem["requirements"]) == REQUIREMENT_COUNT
    assert len(problem["constraints"]) == CONSTRAINT_COUNT
    expected = {
        *(f"legacy-requirement:{number}" for number in range(1, len(problem["requirements"]) + 1)),
        *(f"legacy-constraint:{number}" for number in range(1, len(problem["constraints"]) + 1)),
    }
    actual = {anchor for step in raw["steps"] for anchor in step["requirementIds"]}
    assert actual == expected

    graph_action_types = {"add_component", "add_connection", "update_component"}
    for anchor in expected:
        assert any(
            step["type"] in graph_action_types and anchor in step["requirementIds"]
            for step in raw["steps"]
        ), f"{anchor} has no applied graph action"


def test_graph_actions_have_only_direct_frozen_brief_anchors():
    raw = load_guide()
    actual = {
        step["id"]: set(step["requirementIds"])
        for step in raw["steps"]
        if step["type"] in {"add_component", "add_connection"}
    }
    assert actual == EXPECTED_ACTION_ANCHORS


def test_content_covers_the_frozen_brief_without_adding_numeric_targets():
    raw = load_guide()
    problem = load_frozen_problem()
    text = json.dumps(raw, ensure_ascii=False).casefold()
    required_coverage = (
        "hyperparameters",
        "metrics",
        "artifacts",
        "code revision",
        "environment",
        "pytorch",
        "tensorflow",
        "scikit-learn",
        "distributed",
        "multi-node",
        "parallel coordinates",
        "projects",
        "groups",
        "annotations",
        "comments",
        "parameter",
        "metric filters",
        "append-only",
        "10k+ experiments per project",
        "under 50ms",
        "10gb",
        "real-time",
        "2+ years",
        "it does not state",
        "do not present one as a brief requirement",
    )
    for phrase in required_coverage:
        assert phrase in text, f"missing frozen-brief coverage: {phrase}"

    stated_limits = ("10k+", "under 50ms", "10gb", "2+ years")
    for limit in stated_limits:
        assert limit in text
    assert "100ms" not in text
    assert "1gb" not in text
    assert "1 year" not in text

    frozen_brief = json.dumps(
        {"requirements": problem["requirements"], "constraints": problem["constraints"]},
        ensure_ascii=False,
    )
    assert numeric_targets(text) <= numeric_targets(frozen_brief)

    unknowns = next(step for step in raw["steps"] if step["id"] == "mlops009_unknowns")["content"]
    assert "ASSUMPTION / OPEN INPUT" in unknowns
    for unstated_value in (
        "broker-log retention",
        "artifact-byte retention",
        "search freshness or query latency",
        "latency percentile",
    ):
        assert unstated_value in unknowns

    reproducibility = next(
        step for step in raw["steps"] if step["id"] == "mlops009_reproducibility"
    )["content"].casefold()
    assert "does not prove model quality" in reproducibility
    assert "evaluate model quality separately" in reproducibility

