"""Frozen-brief, supported-catalog, and connected replay checks for the metrics draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca860"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": PROBLEM_ID,
    "title": "Design a Distributed Metrics Logging and Aggregation System",
    "description": "Design a system to collect, store, and analyze metrics from thousands of distributed servers.",
    "requirements": [
        "Collect metrics from thousands of servers",
        "Support different metric types (counters, gauges, histograms)",
        "Real-time aggregation and analysis",
        "Query metrics by time range and dimensions",
        "Alerting based on metric thresholds",
        "Visualization and dashboards",
        "Handle billions of data points per day",
        "Long-term storage for historical data",
    ],
    "constraints": [
        "High write throughput",
        "Low query latency",
        "Handle bursty traffic",
        "Data retention policies",
        "Efficient storage for time-series data",
    ],
    "hints": [
        "Time-series database like Prometheus or InfluxDB",
        "Data aggregation at collection time",
        "Sampling for high-cardinality metrics",
        "Data compression for storage efficiency",
        "Distributed architecture for scalability",
    ],
}
STEP_TYPES = {"explanation", "add_component", "add_connection", "decision_point", "scale_trigger"}
ACTION_TYPES = {"add_component", "add_connection", "decision_point"}
CONNECTION_TYPES = {"http", "api-call", "database-connection", "message-queue", "data-flow"}


def _load():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    guide = GuidedWalkthrough.model_validate(raw)
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    return raw, guide, problem


def _catalog_entry(catalog: str, component_id: str) -> str:
    match = re.search(
        rf'(?ms)^ {{4}}id: "{re.escape(component_id)}",.*?^ {{2}}\}},?',
        catalog,
    )
    assert match, f"Unknown component catalog ID: {component_id}"
    return match.group(0)


def _reachable(start: str, neighbors: dict[str, set[str]]) -> set[str]:
    reached = set()
    pending = deque([start])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    return reached


def _assert_supported_properties(catalog: str, component_type: str, properties: dict, step_id: str):
    block = _catalog_entry(catalog, component_type)
    supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
    assert set(properties) <= supported, (
        f"{step_id}: unsupported properties {sorted(set(properties) - supported)}"
    )

    for key, value in properties.items():
        field_start = block.index(f'key: "{key}"')
        field_end = block.find("},", field_start)
        assert field_end != -1, f"{step_id}/{key}: catalog field is incomplete"
        field = block[field_start:field_end]
        field_type = re.search(r'\btype:\s*"([^"]+)"', field)
        assert field_type, f"{step_id}/{key}: catalog field has no type"
        kind = field_type.group(1)
        if kind in {"text", "textarea"}:
            assert isinstance(value, str)
        elif kind == "boolean":
            assert type(value) is bool
        elif kind == "number":
            assert type(value) in {int, float}
        elif kind == "select":
            options = re.search(r'\boptions:\s*\[([^\]]+)\]', field)
            assert options, f"{step_id}/{key}: catalog select has no options"
            assert value in re.findall(r'"([^"]+)"', options.group(1)), (
                f"{step_id}/{key}: unsupported select value {value!r}"
            )


def test_schema_and_repository_snapshot_exactly_match_the_frozen_brief():
    raw, guide, problem = _load()

    assert {field: problem[field] for field in FROZEN_BRIEF} == FROZEN_BRIEF
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert set(raw) == {"problem_id", "version", "requirementRevision", "totalSteps", "phases", "steps"}
    assert guide.totalSteps == len(guide.steps) == 35
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES and step.content.strip() for step in guide.steps)
    assert problem["has_guided_walkthrough"] is False

    expected_anchors = {
        *(f"legacy-requirement:{index}" for index in range(1, len(FROZEN_BRIEF["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(FROZEN_BRIEF["constraints"]) + 1)),
    }
    actual_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert actual_anchors == expected_anchors
    for anchor in expected_anchors:
        assert any(
            anchor in step.requirementIds and step.type in ACTION_TYPES
            for step in guide.steps
        ), f"{anchor} is only described, not tied to an actionable step"

    replay = build_architecture(raw)
    request = make_request(problem, raw, replay)
    assert request["problem"]["id"] == FROZEN_BRIEF["id"]
    assert request["problem"]["title"] == FROZEN_BRIEF["title"]
    assert request["problem"]["description"] == FROZEN_BRIEF["description"]
    assert request["problem"]["requirements"].splitlines() == FROZEN_BRIEF["requirements"]
    assert request["problem"]["constraints"].splitlines() == FROZEN_BRIEF["constraints"]


def test_phases_and_actions_are_ordered_without_forward_references():
    _, guide, _ = _load()
    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    node_ids = set()
    edge_ids = set()
    decisions = 0
    for step in guide.steps:
        if step.type == "add_component":
            assert step.component is not None
            component = step.component
            assert component.nodeId not in node_ids
            assert component.position.keys() >= {"x", "y"}
            assert component.properties["componentName"] == component.label
            assert len(component.properties["purpose"]) >= 70
            assert component.highlightReason
            node_ids.add(component.nodeId)
        elif step.type == "add_connection":
            assert step.connection is not None
            connection = step.connection
            assert connection.edgeId not in edge_ids
            assert {connection.sourceNodeId, connection.targetNodeId} <= node_ids
            assert connection.connectionType in CONNECTION_TYPES
            assert connection.label and connection.description
            edge_ids.add(connection.edgeId)
        elif step.type == "decision_point":
            assert step.decision is not None
            assert step.decision.chosen and step.decision.chosenReason
            assert len(step.decision.alternatives) >= 2
            assert step.componentUpdate is not None
            assert step.componentUpdate.nodeId in node_ids
            assert step.componentUpdate.properties
            decisions += 1
        elif step.type == "scale_trigger":
            assert step.scaleTrigger is not None
            assert step.scaleTrigger.metric and step.scaleTrigger.action and step.scaleTrigger.impact
        if step.componentUpdate is not None:
            assert step.componentUpdate.nodeId in node_ids

    assert len(node_ids) == 11
    assert len(edge_ids) == 12
    assert decisions == 5


def test_replay_contains_one_connected_metrics_architecture():
    raw, guide, _ = _load()
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {node["id"]: node for node in architecture["components"]}
    edges = architecture["connections"]

    assert len(nodes) == 11
    assert len(edges) == 12
    assert len(replay["appliedStepIds"]) + len(replay["explanationOnlyStepIds"]) == guide.totalSteps
    assert nodes["metrics_tsdb"]["properties"]["type"] == "Time-Series"
    assert nodes["metrics_archive"]["properties"]["originalComponentId"] == "object-storage"
    assert nodes["metrics_agent"]["properties"]["originalComponentId"] == "monitoring"
    assert {edge["type"] for edge in edges} <= CONNECTION_TYPES

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    assert _reachable("metrics_agent", neighbors) == set(nodes)

    expected_edges = {
        ("metrics_agent", "metrics_gateway"),
        ("metrics_gateway", "metrics_ingest"),
        ("metrics_ingest", "metrics_broker"),
        ("metrics_broker", "metrics_aggregator"),
        ("metrics_aggregator", "metrics_tsdb"),
        ("metrics_aggregator", "metrics_archive"),
        ("metrics_query", "metrics_tsdb"),
        ("metrics_query", "metrics_archive"),
        ("metrics_dashboard", "metrics_query"),
        ("metrics_aggregator", "metrics_alerts"),
        ("metrics_alerts", "metrics_tsdb"),
        ("metrics_alerts", "metrics_notifications"),
    }
    assert {(edge["source"], edge["target"]) for edge in edges} == expected_edges


def test_all_component_ids_and_properties_exist_in_the_frontend_catalog():
    raw, _, _ = _load()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step.component.nodeId: step.component
        for step in GuidedWalkthrough.model_validate(raw).steps
        if step.component is not None
    }
    assert additions
    assert all(component.componentType != "custom-component" for component in additions.values())

    for step in GuidedWalkthrough.model_validate(raw).steps:
        if step.component is not None:
            _assert_supported_properties(
                catalog,
                step.component.componentType,
                step.component.properties,
                step.id,
            )
        if step.componentUpdate is not None:
            component = additions[step.componentUpdate.nodeId]
            _assert_supported_properties(
                catalog,
                component.componentType,
                step.componentUpdate.properties,
                step.id,
            )


def test_guidance_covers_metric_semantics_scale_retention_and_tradeoffs():
    raw, _, _ = _load()
    authored_text = " ".join(
        [step["content"] for step in raw["steps"]]
        + [step["component"]["properties"]["purpose"] for step in raw["steps"] if step.get("component")]
        + [step["componentUpdate"]["properties"]["purpose"] for step in raw["steps"] if step.get("componentUpdate")]
        + [
            " ".join(
                [step["decision"]["question"], step["decision"]["chosen"], step["decision"]["chosenReason"]]
                + [alternative["option"] + " " + alternative["tradeoff"] for alternative in step["decision"]["alternatives"]]
            )
            for step in raw["steps"] if step.get("decision")
        ]
        + [
            " ".join(step["scaleTrigger"].values())
            for step in raw["steps"] if step.get("scaleTrigger")
        ]
    ).casefold()

    for signal in (
        "thousands of distributed servers", "billions of data points per day",
        "counter reset", "gauge", "histogram", "time range", "dimension",
        "high-cardinality", "sampling", "real-time", "threshold", "dashboard",
        "bursts", "backpressure", "compression", "retention", "historical",
        "late samples", "assumption", "tradeoff", "not give a peak ingest rate",
    ):
        assert signal in authored_text, f"missing metrics-specific guidance: {signal}"

    assert "custom-component" not in {
        step["component"]["componentType"]
        for step in raw["steps"] if step.get("component")
    }
    assert not re.search(
        r"\b\d+\s*(?:ms|milliseconds?|seconds?|minutes?|hours?|days?|rps|qps)\b",
        authored_text,
    ), "the draft invents a numeric latency, rate, or retention target"
