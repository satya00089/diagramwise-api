"""Contract, graph, palette, and brief-coverage checks for the time-series guide."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "ml_005"
GUIDE_PATH = ROOT / "data/guided-walkthroughs/ml_005.json"
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


def brief_anchors(*, requirements=(), constraints=()) -> set[str]:
    return {
        *(f"legacy-requirement:{number}" for number in requirements),
        *(f"legacy-constraint:{number}" for number in constraints),
    }


EXPECTED_STEP_ANCHORS = {
    "ts_scope": brief_anchors(requirements=(1, 2, 3, 4, 5, 6, 7, 8), constraints=(1, 2, 3, 4, 5)),
    "ts_sources": brief_anchors(constraints=(3, 5)),
    "ts_api": brief_anchors(requirements=(6,)),
    "ts_rules": brief_anchors(requirements=(3, 6), constraints=(4,)),
    "ts_config": brief_anchors(requirements=(3, 6), constraints=(4,)),
    "ts_ingest": brief_anchors(requirements=(4,), constraints=(1, 3, 4, 5)),
    "ts_buffer": brief_anchors(constraints=(1, 5)),
    "ts_hot": brief_anchors(requirements=(2, 5), constraints=(3, 4)),
    "ts_archive": brief_anchors(requirements=(2,)),
    "ts_training": brief_anchors(requirements=(1, 2), constraints=(2, 3, 4)),
    "ts_registry": brief_anchors(requirements=(2, 6), constraints=(2,)),
    "ts_scorer": brief_anchors(requirements=(1, 2, 3, 5, 6), constraints=(1, 3, 4)),
    "ts_correlator": brief_anchors(requirements=(5, 7)),
    "ts_alert_queue": brief_anchors(requirements=(7, 8)),
    "ts_integrations": brief_anchors(requirements=(7, 8)),
    "ts_query": brief_anchors(requirements=(5,)),
    "ts_monitoring": brief_anchors(requirements=(1, 2, 3, 4, 5, 6, 7, 8), constraints=(1, 2, 3, 4, 5)),
    "ts_online_offline": brief_anchors(requirements=(1, 2, 3), constraints=(1, 3, 4)),
    "ts_edge_collect": brief_anchors(requirements=(4,), constraints=(3, 4, 5)),
    "ts_edge_api_rules": brief_anchors(requirements=(6,)),
    "ts_edge_rules_config": brief_anchors(requirements=(3, 6), constraints=(4,)),
    "ts_edge_policy_stream": brief_anchors(requirements=(3, 6), constraints=(1, 5)),
    "ts_edge_buffer": brief_anchors(requirements=(4,), constraints=(1, 5)),
    "ts_edge_replay": brief_anchors(requirements=(7,)),
    "ts_edge_hot": brief_anchors(requirements=(2, 5), constraints=(3, 4)),
    "ts_edge_archive": brief_anchors(requirements=(2,)),
    "ts_edge_train_archive": brief_anchors(requirements=(2,), constraints=(3, 4)),
    "ts_edge_train_hot": brief_anchors(requirements=(2,)),
    "ts_edge_registry": brief_anchors(requirements=(2, 6)),
    "ts_edge_model": brief_anchors(requirements=(2, 6)),
    "ts_edge_config_score": brief_anchors(requirements=(3, 6), constraints=(4,)),
    "ts_edge_score": brief_anchors(requirements=(1, 2, 3), constraints=(1, 3, 4)),
    "ts_edge_correlation": brief_anchors(requirements=(1, 5, 7)),
    "ts_edge_context": brief_anchors(requirements=(5, 7), constraints=(3, 4)),
    "ts_edge_alert_outbox": brief_anchors(requirements=(7, 8)),
    "ts_edge_integration": brief_anchors(requirements=(7, 8)),
    "ts_edge_api_query": brief_anchors(requirements=(5,)),
    "ts_edge_query_hot": brief_anchors(requirements=(5,)),
    "ts_edge_query_archive": brief_anchors(requirements=(2,)),
    "ts_edge_monitor_ingest": brief_anchors(requirements=(4,), constraints=(1, 3, 4, 5)),
    "ts_edge_monitor_model": brief_anchors(requirements=(1, 2), constraints=(1, 2)),
    "ts_edge_monitor_delivery": brief_anchors(requirements=(7, 8)),
    "ts_missing_data": brief_anchors(requirements=(6,), constraints=(3, 4)),
    "ts_budget": brief_anchors(constraints=(1,)),
    "ts_quality_gate": brief_anchors(constraints=(2,)),
    "ts_recovery_tests": brief_anchors(requirements=(1, 2, 3, 4, 5, 6, 7, 8), constraints=(1, 2, 3, 4, 5)),
}


def load_problem() -> dict:
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def load_guide() -> dict:
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def test_schema_phases_and_every_frozen_brief_anchor_are_covered():
    raw = load_guide()
    guide = GuidedWalkthrough.model_validate(raw)
    problem = load_problem()

    assert guide.problem_id == PROBLEM_ID
    assert guide.totalSteps == len(guide.steps) == 46
    assert [step.stepNumber for step in guide.steps] == list(range(1, 47))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in {"explanation", "add_component", "add_connection", "decision_point"} for step in guide.steps)

    expected = {
        *(f"legacy-requirement:{n}" for n in range(1, len(problem["requirements"]) + 1)),
        *(f"legacy-constraint:{n}" for n in range(1, len(problem["constraints"]) + 1)),
    }
    actual = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert actual == expected
    assert {
        step.id: set(step.requirementIds)
        for step in guide.steps
    } == EXPECTED_STEP_ANCHORS
    action_steps = [
        step
        for step in guide.steps
        if step.type in {"add_component", "add_connection", "update_component"}
        or step.componentUpdate is not None
    ]
    action_anchors = {
        anchor for step in action_steps for anchor in step.requirementIds
    }
    assert action_anchors == expected
    ingest_action = next(step for step in action_steps if step.id == "ts_ingest")
    assert "legacy-requirement:4" in ingest_action.requirementIds
    assert "100k+ concurrent time-series requirement" in ingest_action.content
    assert "millions-of-metrics scale constraint" in ingest_action.content
    assert "different measurements" in ingest_action.content

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(guide.steps[n - 1].phase == phase.name for n in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1


def test_replay_produces_one_connected_supported_architecture():
    replay = build_architecture(load_guide())
    architecture = replay["architecture"]
    components = {component["id"] for component in architecture["components"]}
    edges = architecture["connections"]

    assert len(components) == 16
    assert len(edges) == 24
    assert len(replay["appliedStepIds"]) == 40
    assert all(edge["source"] in components and edge["target"] in components for edge in edges)
    assert all(edge["type"] in CONNECTION_TYPES for edge in edges)

    neighbors = {component_id: set() for component_id in components}
    for edge in edges:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque([next(iter(components))])
    while pending:
        current = pending.popleft()
        if current in reached:
            continue
        reached.add(current)
        pending.extend(neighbors[current] - reached)
    assert reached == components


def test_every_component_reuses_catalog_types_and_supported_properties():
    raw = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = [step["component"] for step in raw["steps"] if step["type"] == "add_component"]
    assert len(additions) == 16
    assert all(component["componentType"] != "custom-component" for component in additions)

    for component in additions:
        component_type = component["componentType"]
        match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
        assert match, f"unknown component type {component_type!r}"
        end = catalog.find("\n  },", match.start())
        block = catalog[match.start():end]
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert {"componentName", "purpose"} <= set(component["properties"])
        assert set(component["properties"]) <= supported


def test_guide_explains_missing_data_quality_latency_and_recovery():
    text = json.dumps(load_guide(), ensure_ascii=False).casefold()
    for phrase in (
        "<1 minute",
        "<1%",
        "100k+",
        "millions of metrics",
        "different measurements",
        "not achieved results",
        "missingness",
        "do not impute zero",
        "irregular-data",
        "false-positive",
        "point-in-time",
        "idempotent",
        "rollback",
        "tenant",
    ):
        assert phrase in text

    for unsupported in (
        "one million active series",
        "16.7k points/s",
        "10s intake",
        "20s windowing",
        "p50/p95/p99",
        "higher-cardinality tenants",
        "faster sample cadences",
    ):
        assert unsupported not in text

    budget = next(step for step in load_guide()["steps"] if step["id"] == "ts_budget")["content"].casefold()
    assert "anomaly-decision emission" in budget
    assert "no separate notification-latency target" in budget
    assert "alert enqueue" not in budget

    training = next(step for step in load_guide()["steps"] if step["id"] == "ts_training")["content"].casefold()
    assert "brief's <1% target" in training
    assert "defines no recall threshold" in training
