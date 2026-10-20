"""Focused contract and graph checks for the MLOps orchestration walkthrough draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "mlops_001"
GUIDE_PATH = ROOT / "data/guided-walkthroughs/mlops_001.json"
PROBLEMS_PATH = ROOT / "tests/fixtures/walkthroughs/problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic/src/config/components.ts"
CONNECTION_TYPES = {
    "api-call",
    "data-flow",
    "database-connection",
    "event-stream",
    "http",
    "message-queue",
}
BRIEF_FIELDS = ("id", "title", "description", "requirements", "constraints", "hints")
FROZEN_BRIEF = {
    "id": "mlops_001",
    "title": "Design an End-to-End ML Pipeline Orchestration Platform",
    "description": "Design a platform that orchestrates end-to-end ML workflows from data ingestion through model deployment, with DAG-based pipeline definitions, caching, and reproducibility guarantees.",
    "requirements": [
        "Define ML pipelines as DAGs",
        "Orchestrate data processing, training, and evaluation steps",
        "Cache intermediate pipeline artifacts",
        "Support pipeline parameterization and scheduling",
        "Track pipeline runs with lineage metadata",
        "Handle pipeline failures with retry and alerting",
        "Support distributed execution across compute backends",
        "Integrate with version control for pipeline definitions",
    ],
    "constraints": [
        "Pipeline startup latency under 30 seconds",
        "Support 100+ concurrent pipeline runs",
        "Artifact storage with deduplication",
        "Reproduce any historical pipeline run",
        "Support heterogeneous compute (CPU, GPU, Spark)",
    ],
    "hints": [
        "Use Kubeflow Pipelines, Airflow, or Prefect for orchestration",
        "Implement content-addressable artifact caching",
        "Use containerized steps for reproducibility",
        "Implement pipeline versioning with Git integration",
        "Use object storage for artifact persistence",
        "Implement DAG visualization for monitoring",
    ],
}


def load_problem() -> dict:
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def load_guide() -> dict:
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def expected_anchors(problem: dict) -> set[str]:
    return {
        *(f"legacy-requirement:{number}" for number in range(1, len(problem["requirements"]) + 1)),
        *(f"legacy-constraint:{number}" for number in range(1, len(problem["constraints"]) + 1)),
    }


def catalog_component_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'(?m)^\s*id:\s*"{re.escape(component_type)}"', catalog)
    assert match, f"unknown component type {component_type!r}"
    end = catalog.find("\n  },", match.start())
    assert end != -1, f"could not find catalog block end for {component_type!r}"
    return catalog[match.start() : end]


def test_frozen_fixture_matches_the_supplied_live_brief_exactly():
    problem = load_problem()
    assert {field: problem[field] for field in BRIEF_FIELDS} == FROZEN_BRIEF
    assert problem["has_guided_walkthrough"] is False


def test_schema_steps_phases_and_exact_action_anchor_coverage():
    raw = load_guide()
    guide = GuidedWalkthrough.model_validate(raw)
    problem = load_problem()

    assert guide.problem_id == PROBLEM_ID
    assert guide.version.endswith("review-draft")
    assert guide.totalSteps == len(guide.steps) == 60
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(
        step.type in {"explanation", "add_component", "add_connection", "decision_point", "scale_trigger"}
        for step in guide.steps
    )

    expected = expected_anchors(problem)
    actual = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert actual == expected
    graph_actions = {"add_component", "add_connection", "update_component"}
    for anchor in expected:
        assert any(
            step.type in graph_actions and anchor in step.requirementIds for step in guide.steps
        ), f"{anchor} appears only on prose/decision steps, not an applied graph action"

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(guide.steps[number - 1].phase == phase.name for number in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1


def test_components_use_only_catalog_types_and_supported_properties():
    raw = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = [step["component"] for step in raw["steps"] if step["type"] == "add_component"]
    assert len(additions) == 20
    assert len({component["nodeId"] for component in additions}) == len(additions)

    custom = [component for component in additions if component["componentType"] == "custom-component"]
    assert len(custom) == 1
    assert custom[0]["label"] == "Apache Spark Batch Backend"
    assert custom[0]["properties"]["technology"] == "Apache Spark"

    for component in additions:
        block = catalog_component_block(catalog, component["componentType"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert {"componentName", "purpose"} <= set(component["properties"])
        assert set(component["properties"]) <= supported, (
            f"{component['nodeId']} uses unsupported properties: "
            f"{set(component['properties']) - supported}"
        )
        assert component["label"].strip()
        assert component["description"].strip()


def test_ordered_replay_has_no_broken_edges_and_one_connected_dag():
    raw = load_guide()
    seen_nodes: set[str] = set()
    component_count = 0
    connection_count = 0

    for step in sorted(raw["steps"], key=lambda row: row["stepNumber"]):
        if step["type"] == "add_component":
            node_id = step["component"]["nodeId"]
            assert node_id not in seen_nodes
            seen_nodes.add(node_id)
            component_count += 1
        elif step["type"] == "add_connection":
            connection = step["connection"]
            assert connection["sourceNodeId"] in seen_nodes
            assert connection["targetNodeId"] in seen_nodes
            assert connection["connectionType"] in CONNECTION_TYPES
            connection_count += 1

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    component_ids = {component["id"] for component in architecture["components"]}
    edges = architecture["connections"]
    assert len(component_ids) == component_count == 20
    assert len(edges) == connection_count == 30
    assert len(replay["appliedStepIds"]) == component_count + connection_count
    assert all(edge["source"] in component_ids and edge["target"] in component_ids for edge in edges)
    assert all(edge["type"] in CONNECTION_TYPES for edge in edges)

    neighbors = {component_id: set() for component_id in component_ids}
    indegree = {component_id: 0 for component_id in component_ids}
    outgoing = {component_id: set() for component_id in component_ids}
    for edge in edges:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
        outgoing[edge["source"]].add(edge["target"])
        indegree[edge["target"]] += 1

    reached: set[str] = set()
    pending = deque([next(iter(component_ids))])
    while pending:
        current = pending.popleft()
        if current in reached:
            continue
        reached.add(current)
        pending.extend(neighbors[current] - reached)
    assert reached == component_ids

    ready = deque(node_id for node_id, degree in indegree.items() if degree == 0)
    topological_count = 0
    while ready:
        current = ready.popleft()
        topological_count += 1
        for target in outgoing[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    assert topological_count == len(component_ids), "the final pipeline graph must be acyclic"


def test_walkthrough_distinguishes_facts_assumptions_and_brief_boundaries():
    text = json.dumps(load_guide(), ensure_ascii=False).casefold()
    for phrase in (
        "fact —",
        "assumption —",
        "the brief does not specify",
        "under 30 seconds",
        "100+ concurrent runs",
        "cpu, gpu, and spark",
        "retry cap",
        "digest",
        "historical",
    ):
        assert phrase in text

