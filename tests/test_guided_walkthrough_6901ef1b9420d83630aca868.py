"""Contract checks for the Google Analytics walkthrough review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca868"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": "6901ef1b9420d83630aca868",
    "title": "Design Google Analytics - User Analytics Dashboard and Pipeline",
    "description": "Design an analytics platform to track user behavior, generate reports, and provide insights.",
    "requirements": [
        "Track user events and page views",
        "Real-time and historical analytics",
        "Custom reports and dashboards",
        "User segmentation and funnels",
        "Goal tracking and conversions",
        "Handle billions of events per day",
        "Support custom dimensions and metrics",
        "Data export capabilities",
    ],
    "constraints": [
        "Real-time data processing (<1 minute)",
        "Handle traffic spikes",
        "Accurate counting and aggregation",
        "Support complex queries on large datasets",
        "Data retention policies",
    ],
    "hints": [
        "Lambda architecture (batch + stream)",
        "Data warehouse for historical analysis",
        "Stream processing for real-time metrics",
        "Pre-aggregation for common queries",
        "Sampling for high-traffic sites",
    ],
}

EXPECTED_PHASES = [
    ("Define event meaning and safe ingestion", 1, 11),
    ("Publish real-time metrics and definitions", 12, 16),
    ("Build the batch and historical path", 17, 21),
    ("Serve reports, dashboards, exports, and operations", 22, 35),
    ("Review exactness and unresolved policies", 36, 38),
]
CONNECTION_TYPES = {
    "http",
    "api-call",
    "database-connection",
    "tcp",
    "message-queue",
    "data-flow",
    "event-stream",
    "websocket",
}
ACTION_TYPES = {"add_component", "add_connection", "update_component"}
STEP_TYPES = ACTION_TYPES | {"explanation", "decision_point", "scale_trigger"}
EXPECTED_COMPONENT_TYPES = {
    "ga_sdk": "web-app",
    "ga_ingest_api": "api-gateway",
    "ga_event_log": "message-broker",
    "ga_stream": "stream-processor",
    "ga_realtime_metrics": "analytics",
    "ga_definitions": "database",
    "ga_raw_events": "object-storage",
    "ga_warehouse": "data-warehouse",
    "ga_query_cache": "cache",
    "ga_report_api": "backend-server",
    "ga_dashboard": "web-app",
    "ga_monitoring": "monitoring",
}
EXPECTED_STEP_ANCHORS = {
    "ga_01": set(),
    "ga_02": {"legacy-constraint:3"},
    "ga_03": {"legacy-requirement:2", "legacy-constraint:1"},
    "ga_04": {"legacy-requirement:1"},
    "ga_05": {"legacy-requirement:1", "legacy-constraint:3"},
    "ga_06": {"legacy-requirement:1"},
    "ga_07": {"legacy-requirement:6", "legacy-constraint:2"},
    "ga_08": {"legacy-requirement:1"},
    "ga_09": {
        "legacy-requirement:1",
        "legacy-requirement:2",
        "legacy-requirement:5",
        "legacy-requirement:6",
        "legacy-constraint:1",
        "legacy-constraint:3",
    },
    "ga_10": {
        "legacy-requirement:2",
        "legacy-constraint:1",
        "legacy-constraint:3",
    },
    "ga_11": {
        "legacy-requirement:6",
        "legacy-constraint:2",
        "legacy-constraint:3",
    },
    "ga_12": {
        "legacy-requirement:2",
        "legacy-requirement:4",
        "legacy-requirement:5",
        "legacy-constraint:1",
        "legacy-constraint:3",
    },
    "ga_13": {
        "legacy-requirement:2",
        "legacy-requirement:5",
        "legacy-constraint:1",
        "legacy-constraint:3",
    },
    "ga_14": {
        "legacy-requirement:5",
        "legacy-requirement:7",
        "legacy-constraint:3",
        "legacy-constraint:5",
    },
    "ga_15": {
        "legacy-requirement:5",
        "legacy-requirement:7",
        "legacy-constraint:3",
    },
    "ga_16": {
        "legacy-requirement:4",
        "legacy-requirement:5",
        "legacy-requirement:7",
        "legacy-constraint:3",
    },
    "ga_17": {
        "legacy-requirement:2",
        "legacy-requirement:8",
        "legacy-constraint:5",
    },
    "ga_18": {
        "legacy-requirement:2",
        "legacy-requirement:8",
        "legacy-constraint:5",
    },
    "ga_19": {
        "legacy-requirement:2",
        "legacy-requirement:3",
        "legacy-requirement:4",
        "legacy-constraint:4",
        "legacy-constraint:5",
    },
    "ga_20": {
        "legacy-requirement:2",
        "legacy-requirement:4",
        "legacy-constraint:3",
        "legacy-constraint:4",
        "legacy-constraint:5",
    },
    "ga_21": {
        "legacy-requirement:3",
        "legacy-requirement:4",
        "legacy-requirement:7",
        "legacy-constraint:4",
    },
    "ga_22": {"legacy-requirement:3", "legacy-constraint:4"},
    "ga_23": {"legacy-requirement:3", "legacy-constraint:4"},
    "ga_24": {
        "legacy-requirement:2",
        "legacy-requirement:3",
        "legacy-requirement:8",
        "legacy-constraint:4",
    },
    "ga_25": {
        "legacy-requirement:2",
        "legacy-requirement:3",
        "legacy-constraint:1",
    },
    "ga_26": {
        "legacy-requirement:2",
        "legacy-requirement:3",
        "legacy-requirement:4",
        "legacy-constraint:4",
        "legacy-constraint:5",
    },
    "ga_27": {"legacy-requirement:3", "legacy-constraint:4"},
    "ga_28": {
        "legacy-requirement:3",
        "legacy-requirement:5",
        "legacy-requirement:7",
        "legacy-requirement:8",
    },
    "ga_29": {
        "legacy-requirement:3",
        "legacy-requirement:4",
        "legacy-requirement:5",
    },
    "ga_30": {
        "legacy-requirement:3",
        "legacy-requirement:4",
        "legacy-requirement:5",
    },
    "ga_31": {"legacy-requirement:8", "legacy-constraint:5"},
    "ga_32": {
        "legacy-constraint:1",
        "legacy-constraint:2",
        "legacy-constraint:3",
        "legacy-constraint:4",
    },
    "ga_33": {
        "legacy-requirement:6",
        "legacy-constraint:1",
        "legacy-constraint:2",
        "legacy-constraint:3",
    },
    "ga_34": {
        "legacy-requirement:2",
        "legacy-constraint:1",
        "legacy-constraint:3",
    },
    "ga_35": {
        "legacy-requirement:2",
        "legacy-constraint:4",
        "legacy-constraint:5",
    },
    "ga_36": {"legacy-requirement:6", "legacy-constraint:3"},
    "ga_37": {"legacy-constraint:5"},
    "ga_38": set(),
}
PROSE_KEYS = {
    "title",
    "content",
    "label",
    "description",
    "purpose",
    "chosen",
    "rationale",
    "highlightReason",
}
PROSE_CONTAINER_KEYS = {
    "steps",
    "decision",
    "alternatives",
    "component",
    "componentUpdate",
    "connection",
    "properties",
}


def load_candidate():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    matches = [problem for problem in problems if problem["id"] == PROBLEM_ID]
    assert len(matches) == 1
    return raw, GuidedWalkthrough.model_validate(raw), matches[0]


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"{step_id}: unknown catalog component {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), f"{step_id}: incomplete catalog entry"
    return catalog[match.start() : block_end]


def assert_catalog_properties(catalog: str, component_type: str, properties: dict, step_id: str):
    block = catalog_block(catalog, component_type, step_id)
    supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
    assert set(properties) <= supported, (
        f"{step_id}: unsupported {component_type} properties "
        f"{sorted(set(properties) - supported)}"
    )

    for key, value in properties.items():
        field_start = re.search(rf'\{{\s*key:\s*"{re.escape(key)}"', block)
        assert field_start, f"{step_id}: missing catalog property {component_type}.{key}"
        field_end = block.find("},", field_start.start())
        assert field_end > field_start.start(), f"{step_id}: incomplete property {key}"
        field = block[field_start.start() : field_end]
        field_type = re.search(r'\btype:\s*"([^"]+)"', field)
        assert field_type, f"{step_id}: {component_type}.{key} has no catalog type"

        kind = field_type.group(1)
        if kind in {"text", "textarea"}:
            assert isinstance(value, str), f"{step_id}/{key} must be text"
        elif kind == "boolean":
            assert type(value) is bool, f"{step_id}/{key} must be boolean"
        elif kind == "number":
            assert type(value) in {int, float}, f"{step_id}/{key} must be numeric"
        elif kind == "select":
            options = re.search(r'\boptions:\s*\[([^\]]*)\]', field, re.DOTALL)
            assert options, f"{step_id}/{key}: catalog options are missing"
            allowed = set(re.findall(r'"([^"]+)"', options.group(1)))
            assert value in allowed, f"{step_id}/{key}: unsupported option {value!r}"


def connected_from(start: str, neighbors: dict[str, set[str]]) -> set[str]:
    reached = set()
    pending = deque([start])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    return reached


def authored_prose(value) -> list[str]:
    prose = []

    def collect(item, key=None):
        if isinstance(item, dict):
            for child_key, child in item.items():
                if child_key in PROSE_KEYS or child_key in PROSE_CONTAINER_KEYS:
                    collect(child, child_key)
        elif isinstance(item, list):
            for child in item:
                collect(child, key)
        elif isinstance(item, str) and key in PROSE_KEYS:
            prose.append(item)

    collect(value)
    return prose


def test_exact_frozen_brief_schema_version_and_phases():
    raw, guide, problem = load_candidate()

    assert {field: problem[field] for field in FROZEN_BRIEF} == FROZEN_BRIEF
    assert problem["has_guided_walkthrough"] is False
    assert set(raw) == {
        "problem_id",
        "version",
        "requirementRevision",
        "totalSteps",
        "phases",
        "steps",
    }
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 38
    assert [(phase.name, *phase.stepRange) for phase in guide.phases] == EXPECTED_PHASES
    used_step_types = {step.type for step in guide.steps}
    assert used_step_types <= STEP_TYPES
    assert ACTION_TYPES <= used_step_types
    assert all(step.title.strip() and step.content.strip() for step in guide.steps)


def test_phases_cover_ordered_steps_and_every_brief_anchor_has_an_action():
    _, guide, _ = load_candidate()
    expected_anchors = {
        *(f"legacy-requirement:{index}" for index in range(1, 9)),
        *(f"legacy-constraint:{index}" for index in range(1, 6)),
    }
    assert [step.stepNumber for step in guide.steps] == list(range(1, 39))
    assert len({step.id for step in guide.steps}) == guide.totalSteps

    next_step = 1
    all_anchors = set()
    action_anchors = set()
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end <= guide.totalSteps
        assert all(step.phase == phase.name for step in guide.steps[start - 1 : end])
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    for step in guide.steps:
        anchors = set(step.requirementIds)
        assert step.id in EXPECTED_STEP_ANCHORS
        assert anchors == EXPECTED_STEP_ANCHORS[step.id], (
            f"{step.id}: expected precise anchors "
            f"{sorted(EXPECTED_STEP_ANCHORS[step.id])}, got {sorted(anchors)}"
        )
        assert len(anchors) == len(step.requirementIds), f"{step.id}: repeated anchor"
        assert anchors <= expected_anchors, f"{step.id}: unknown anchor"
        all_anchors.update(anchors)
        if step.type in ACTION_TYPES:
            action_anchors.update(anchors)

    assert all_anchors == expected_anchors
    assert action_anchors == expected_anchors


def test_catalog_ids_properties_and_ordered_unique_actions():
    raw, guide, _ = load_candidate()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    seen_nodes = {}
    seen_edges = set()
    action_ids = []

    for step in guide.steps:
        if step.type == "add_component":
            component = step.component
            assert component is not None
            assert component.nodeId not in seen_nodes
            assert set(component.position) == {"x", "y"}
            assert all(type(value) in {int, float} for value in component.position.values())
            assert component.componentType != "custom"
            assert component.properties["componentName"] == component.label
            assert len(component.properties["purpose"]) >= 70
            assert component.highlightReason
            assert_catalog_properties(catalog, component.componentType, component.properties, step.id)
            seen_nodes[component.nodeId] = component
            action_ids.append(step.id)
        elif step.type == "add_connection":
            connection = step.connection
            assert connection is not None
            assert connection.edgeId not in seen_edges
            assert connection.sourceNodeId in seen_nodes, f"{step.id}: source must exist before replay"
            assert connection.targetNodeId in seen_nodes, f"{step.id}: target must exist before replay"
            assert connection.connectionType in CONNECTION_TYPES
            assert connection.label and connection.description
            seen_edges.add(connection.edgeId)
            action_ids.append(step.id)
        elif step.componentUpdate:
            update = step.componentUpdate
            assert update.nodeId in seen_nodes, f"{step.id}: update must follow component creation"
            assert update.properties
            component = seen_nodes[update.nodeId]
            assert_catalog_properties(catalog, component.componentType, update.properties, step.id)
            action_ids.append(step.id)

    assert {node_id: component.componentType for node_id, component in seen_nodes.items()} == EXPECTED_COMPONENT_TYPES
    assert len(seen_edges) == 17
    assert len(action_ids) == len(set(action_ids)) == 31
    assert action_ids == [step["id"] for step in raw["steps"] if step["type"] in ACTION_TYPES]


def test_replay_contains_one_connected_graph_and_all_actions():
    raw, guide, _ = load_candidate()
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    edges = architecture["connections"]
    expected_action_ids = [step.id for step in guide.steps if step.type in ACTION_TYPES]

    assert set(nodes) == set(EXPECTED_COMPONENT_TYPES)
    assert len(edges) == 17
    assert replay["appliedStepIds"] == expected_action_ids
    assert replay["explanationOnlyStepIds"] == [step.id for step in guide.steps if step.id not in expected_action_ids]
    assert all(edge["type"] in CONNECTION_TYPES for edge in edges)
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in edges)

    neighbors = {node_id: set() for node_id in nodes}
    edge_pairs = set()
    for edge in edges:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
        edge_pairs.add((edge["source"], edge["target"]))

    assert len(edge_pairs) == len(edges)
    assert connected_from("ga_sdk", neighbors) == set(nodes)
    assert nodes["ga_warehouse"]["properties"]["originalComponentId"] == "data-warehouse"
    assert nodes["ga_warehouse"]["type"] == "storage"
    assert nodes["ga_monitoring"]["properties"]["originalComponentId"] == "monitoring"
    assert nodes["ga_monitoring"]["type"] == "backend"


def test_analytics_decisions_preserve_accuracy_and_do_not_invent_targets():
    raw, _, _ = load_candidate()
    steps = {step["id"]: step for step in raw["steps"]}
    authored = json.dumps(raw, ensure_ascii=False).casefold()

    assert "the brief does not define" in steps["ga_01"]["content"].casefold()
    assert "billions of events per day" in steps["ga_01"]["content"].casefold()
    assert "stated scale and freshness values are acceptance targets" in steps["ga_01"]["content"].casefold()
    assert "peak rate" in steps["ga_01"]["content"].casefold()
    assert "stable event_id" in steps["ga_02"]["decision"]["chosen"]
    assert "lambda-style split" in steps["ga_03"]["content"].casefold()
    assert "traffic spikes" in steps["ga_07"]["component"]["properties"]["purpose"].casefold()
    assert "exact" in steps["ga_09"]["component"]["properties"]["purpose"].casefold()
    assert "user or session identity" in steps["ga_16"]["componentUpdate"]["properties"]["purpose"].casefold()
    assert "custom dimensions" in steps["ga_14"]["component"]["properties"]["purpose"].casefold()
    assert "funnels" in steps["ga_21"]["componentUpdate"]["properties"]["purpose"].casefold()
    assert "sampling" in steps["ga_36"]["decision"]["chosen"].casefold()
    assert "do not sample authoritative event counts" in steps["ga_36"]["decision"]["chosen"].casefold()
    assert "leave every duration" in steps["ga_37"]["decision"]["chosen"].casefold()
    assert "less than one minute" in steps["ga_38"]["content"].casefold()
    assert "billions of events per day" in steps["ga_38"]["content"].casefold()
    assert "query latency, peak throughput, and retention duration remain unspecified" in steps["ga_38"]["content"].casefold()

    for phrase in (
        "page-view",
        "historical",
        "custom reports",
        "segmentation",
        "conversion",
        "billions of events per day",
        "custom dimensions",
        "export",
        "traffic spikes",
        "accurate",
        "complex",
        "retention",
    ):
        assert phrase in authored, f"walkthrough does not discuss {phrase}"

    quantitative_prose = "\n".join(authored_prose(raw))
    unsupported_metric = re.compile(
        r"\b(?:p50|p95|p99)\b|"
        r"\b\d[\d,]*(?:\.\d+)?[\s-]*(?:(?:k|m|b)\+?[\s-]*)?(?:"
        r"million|billion|trillion|%|percent|"
        r"ms\b|milliseconds?|seconds?|minutes?|hours?|days?|weeks?|months?|years?|"
        r"events?|requests?|users?|metrics?|dimensions?|series|records?|partitions?|"
        r"queries|rows?|bytes?|[kmgtp]b|"
        r"(?:events?|requests?)\s*(?:/|per)\s*(?:sec(?:ond)?s?|min(?:ute)?s?|hours?|days?)"
        r")",
        re.IGNORECASE,
    )
    assert not unsupported_metric.search(quantitative_prose), (
        "walkthrough contains an unsupported numeric scale/SLO/retention claim: "
        f"{unsupported_metric.search(quantitative_prose).group(0)}"
    )

    for step in raw["steps"]:
        component = step.get("component")
        if component:
            assert set(component["properties"]) == {"componentName", "purpose"}
            assert (component.get("data") or {}).get(
                "originalComponentId", component["componentType"]
            ) == component["componentType"]
