"""Focused structural review gates for the log anomaly detection draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / "aiops_004.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

LIVE_DESCRIPTION = (
    "Design a system that automatically detects anomalies in application logs "
    "using ML, identifies new error patterns, clusters similar log messages "
    "into templates, and correlates log anomalies with system events."
)
REQUIREMENTS = [
    "Parse and normalize heterogeneous log formats",
    "Detect anomalous log patterns automatically",
    "Cluster similar log messages into templates",
    "Identify new/unseen error patterns",
    "Correlate log anomalies with metrics and events",
    "Track log volume and pattern trends",
    "Alert on critical log anomalies",
    "Support natural language search over logs",
]
CONSTRAINTS = [
    "Process 1M+ log lines per second",
    "Detection latency under 30 seconds",
    "Log template accuracy above 95%",
    "Handle 100+ different log formats",
    "Storage-efficient log indexing",
]
STEP_TYPES = {
    "explanation", "add_component", "add_connection", "decision_point", "scale_trigger"
}
ACTION_TYPES = {"add_component", "add_connection", "decision_point"}
CONNECTION_TYPES = {
    "api-call", "data-flow", "database-connection", "event-stream",
    "http", "message-queue",
}
ANCHORS = {
    *(f"legacy-requirement:{number}" for number in range(1, len(REQUIREMENTS) + 1)),
    *(f"legacy-constraint:{number}" for number in range(1, len(CONSTRAINTS) + 1)),
}
ACTION_ANCHOR_EVIDENCE = {
    "legacy-requirement:1": {"log_05", "log_06"},
    "legacy-requirement:2": {"log_20", "log_21", "log_23"},
    "legacy-requirement:3": {"log_18", "log_19"},
    "legacy-requirement:4": {"log_18", "log_19", "log_22"},
    "legacy-requirement:5": {"log_14", "log_15", "log_16"},
    "legacy-requirement:6": {"log_26", "log_27"},
    "legacy-requirement:7": {"log_45", "log_46"},
    "legacy-requirement:8": {"log_29", "log_30", "log_35", "log_40"},
    "legacy-constraint:1": {"log_08", "log_16", "log_25"},
    "legacy-constraint:2": {"log_20", "log_21", "log_25"},
    "legacy-constraint:3": {"log_18", "log_19", "log_24"},
    "legacy-constraint:4": {"log_05", "log_12", "log_24"},
    "legacy-constraint:5": {"log_07", "log_29", "log_30"},
}
EXPECTED_PHASES = [
    ("1. Define the log contract and durable intake", 1, 15),
    ("2. Parse templates and detect anomalies in streams", 16, 28),
    ("3. Correlate, alert, and search with evidence", 29, 47),
    ("4. Learn safely and operate against targets", 48, 57),
]


def _load() -> tuple[dict, dict]:
    guide = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == "aiops_004")
    return guide, problem


def _catalog_entry(catalog: str, component_id: str) -> str:
    entry = re.search(
        rf'(?ms)^ {{4}}id: "{re.escape(component_id)}",.*?^ {{2}}\}},?', catalog
    )
    assert entry, f"Unknown component catalog ID: {component_id}"
    return entry.group(0)


def _assert_supported_properties(component: dict, properties: dict, catalog: str) -> None:
    entry = _catalog_entry(catalog, component["componentType"])
    property_keys = set(re.findall(r'\bkey:\s*"([^"]+)"', entry))
    assert properties and set(properties) <= property_keys, (
        f"Unsupported {component['componentType']} properties: "
        f"{sorted(set(properties) - property_keys)}"
    )

    for key, value in properties.items():
        start = re.search(rf'\{{\s*key:\s*"{re.escape(key)}"', entry)
        assert start, f"Missing catalog definition for {component['componentType']}.{key}"
        remainder = entry[start.start():]
        following = re.search(r'\n\s*\{\s*key:', remainder[1:])
        property_block = remainder[:following.start() + 1] if following else remainder
        field_type = re.search(r'\btype:\s*"([^"]+)"', property_block)
        assert field_type, f"Missing catalog type for {component['componentType']}.{key}"
        if field_type[1] == "boolean":
            assert type(value) is bool
        elif field_type[1] == "number":
            assert type(value) in (int, float)
        elif field_type[1] == "select":
            options = re.search(r'\boptions:\s*\[([^\]]*)\]', property_block, re.DOTALL)
            assert options, f"Missing select options for {component['componentType']}.{key}"
            assert value in set(re.findall(r'"([^"]+)"', options[1]))


def test_live_brief_schema_phase_and_exact_anchor_coverage():
    guide, problem = _load()
    parsed = GuidedWalkthrough.model_validate(guide)

    assert problem["title"] == "Design a Log Anomaly Detection System"
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert parsed.problem_id == "aiops_004"
    assert parsed.version == "1.0.0-review-draft"
    assert parsed.requirementRevision is None
    assert parsed.totalSteps == len(parsed.steps) == 57
    assert [step.stepNumber for step in parsed.steps] == list(range(1, 58))
    assert len({step.id for step in parsed.steps}) == len(parsed.steps)

    assert [
        (phase.name, phase.stepRange[0], phase.stepRange[1]) for phase in parsed.phases
    ] == EXPECTED_PHASES
    phase_by_number = {
        number: phase.name
        for phase in parsed.phases
        for number in range(phase.stepRange[0], phase.stepRange[1] + 1)
    }
    assert list(phase_by_number) == list(range(1, 58))
    assert all(phase_by_number[step.stepNumber] == step.phase for step in parsed.steps)
    assert {step.type for step in parsed.steps} == STEP_TYPES

    step_by_id = {step.id: step for step in parsed.steps}
    for number, expected_type in (
        (7, "decision_point"), (24, "decision_point"), (40, "decision_point"),
        (25, "scale_trigger"), (57, "scale_trigger"),
    ):
        assert parsed.steps[number - 1].type == expected_type
    for step in parsed.steps:
        if step.type == "add_component":
            assert step.component is not None
        elif step.type == "add_connection":
            assert step.connection is not None
        elif step.type == "decision_point":
            assert step.decision and step.decision.alternatives
            assert step.componentUpdate and step.componentUpdate.properties
            assert len(step.decision.alternatives) >= 2
        elif step.type == "scale_trigger":
            assert step.scaleTrigger
            assert all((step.scaleTrigger.metric, step.scaleTrigger.action, step.scaleTrigger.impact))

    all_anchors = {anchor for step in parsed.steps for anchor in step.requirementIds}
    action_anchors = {
        anchor for step in parsed.steps if step.type in ACTION_TYPES
        for anchor in step.requirementIds
    }
    assert all_anchors == action_anchors == ANCHORS
    for anchor, evidence_steps in ACTION_ANCHOR_EVIDENCE.items():
        assert evidence_steps <= set(step_by_id)
        assert any(
            step_by_id[step_id].type in ACTION_TYPES
            and anchor in step_by_id[step_id].requirementIds
            for step_id in evidence_steps
        ), f"No concrete action covers {anchor}"

    assert LIVE_DESCRIPTION in parsed.steps[0].content
    assert all(text in parsed.steps[0].content for text in REQUIREMENTS + CONSTRAINTS)


def test_anchor_evidence_keeps_targets_and_alert_timing_distinct():
    guide, _ = _load()
    steps = {step["id"]: step for step in guide["steps"]}

    assert steps["log_01"]["requirementIds"] == []
    assert steps["log_47"]["requirementIds"] == []
    assert steps["log_35"]["requirementIds"] == ["legacy-requirement:8"]
    assert steps["log_36"]["requirementIds"] == ["legacy-requirement:8"]
    assert steps["log_45"]["requirementIds"] == ["legacy-requirement:7"]
    assert steps["log_46"]["requirementIds"] == ["legacy-requirement:7"]
    assert steps["log_56"]["requirementIds"] == ["legacy-requirement:7"]

    brief_facts = steps["log_01"]["content"]
    assert "These are acceptance targets, not measured outcomes or guarantees." in brief_facts
    assert "the design itself does not prove that target." in steps["log_54"]["content"]
    assert "None of these targets is established by this draft alone." in steps["log_57"]["content"]

    detection = steps["log_25"]["content"]
    assert "to durable anomaly-candidate creation" in detection
    assert "Measure candidate-to-notification acknowledgement separately" in detection
    assert "the brief does not define either" in detection
    monitoring = steps["log_48"]["content"]
    assert "ingest-to-candidate detection latency separately from candidate-to-acknowledged-notification delivery latency" in monitoring

    assert "accepted/rejected lines per second" in monitoring
    assert "above-95% template accuracy" in steps["log_24"]["content"]
    assert "100+ heterogeneous formats" in steps["log_05"]["component"]["properties"]["purpose"]
    assert "inverted search index" in steps["log_29"]["title"]
    assert "natural-language search" in steps["log_35"]["title"].casefold()

    all_text = json.dumps(guide, ensure_ascii=False)
    alert_window_patterns = (
        r"(?i)\b(?:alert(?:ing)?|page|notification)\b[^.;\n]{0,100}"
        r"\b(?:window|period|interval)\s*(?:of\s*)?\d+\s*[- ]?"
        r"(?:seconds?|minutes?|hours?)\b",
        r"(?i)\b\d+\s*[- ]?(?:seconds?|minutes?|hours?)\b[^.;\n]{0,100}"
        r"\b(?:alert(?:ing)?|page|notification)\s+(?:window|period|interval)\b",
        r"(?i)\b\d+\s*[- ]?(?:seconds?|minutes?|hours?)[- ]+"
        r"(?:alert(?:ing)?|page|notification)\s+(?:window|period|interval)\b",
    )
    assert not any(re.search(pattern, all_text) for pattern in alert_window_patterns)


def test_catalog_components_properties_and_action_ids_are_valid():
    guide, _ = _load()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}
    edge_ids = set()
    action_ids = []
    counts = {kind: 0 for kind in STEP_TYPES}

    for step in guide["steps"]:
        kind = step["type"]
        assert kind in STEP_TYPES
        counts[kind] += 1
        if kind in ACTION_TYPES:
            action_ids.append(step["id"])

        if kind == "add_component":
            component = step["component"]
            node_id = component["nodeId"]
            assert node_id not in components
            assert component["componentType"] != "custom-component"
            assert set(component["position"]) == {"x", "y"}
            assert component["properties"]["componentName"] == component["label"]
            assert len(component["properties"]["purpose"]) >= 60
            _assert_supported_properties(component, component["properties"], catalog)
            components[node_id] = component
        elif kind == "add_connection":
            connection = step["connection"]
            assert connection["edgeId"] not in edge_ids
            edge_ids.add(connection["edgeId"])
            assert connection["sourceNodeId"] in components
            assert connection["targetNodeId"] in components
            assert connection["connectionType"] in CONNECTION_TYPES
            assert connection["label"] and connection["description"]
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            assert update["nodeId"] in components
            _assert_supported_properties(
                components[update["nodeId"]], update["properties"], catalog
            )

    assert len(action_ids) == len(set(action_ids))
    assert len(components) == 22
    assert len(edge_ids) == 28
    assert counts == {
        "explanation": 2,
        "add_component": 22,
        "add_connection": 28,
        "decision_point": 3,
        "scale_trigger": 2,
    }
    assert {row["componentType"] for row in components.values()} <= {
        "api-gateway", "analytics", "auth-service", "backend-server", "database",
        "embedding-service", "log-processing", "message-broker", "model-registry",
        "model-serving", "model-training", "monitoring", "notification-service",
        "object-storage", "queue", "search-engine", "stream-processor", "vector-database",
        "web-app",
    }


def test_replay_builds_one_connected_graph_and_exact_request_context():
    guide, problem = _load()
    full = build_architecture(guide)
    action_step_ids = [
        step["id"] for step in guide["steps"] if step["type"] in ACTION_TYPES
    ]
    applied = build_architecture(guide, applied_step_ids=action_step_ids)
    assert full["architecture"] == applied["architecture"]
    assert full["appliedStepIds"] == action_step_ids
    assert len(full["acceptedDecisions"]) == 3
    assert len(full["architecture"]["components"]) == 22
    assert len(full["architecture"]["connections"]) == 28

    nodes = {row["id"]: row for row in full["architecture"]["components"]}
    edges = full["architecture"]["connections"]
    neighbors = {node_id: set() for node_id in nodes}
    directed = {node_id: set() for node_id in nodes}
    seen_pairs = set()
    for edge in edges:
        assert edge["type"] in CONNECTION_TYPES
        pair = (edge["source"], edge["target"])
        assert pair not in seen_pairs
        seen_pairs.add(pair)
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
        directed[edge["source"]].add(edge["target"])

    reached = set()
    pending = deque(["log_sources"])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    assert reached == set(nodes)

    def reaches(source: str, target: str) -> bool:
        seen = set()
        pending_nodes = [source]
        while pending_nodes:
            current = pending_nodes.pop()
            if current == target:
                return True
            if current not in seen:
                seen.add(current)
                pending_nodes.extend(directed[current] - seen)
        return False

    assert reaches("log_sources", "log_archive")
    assert reaches("system_event_sources", "log_stream")
    assert reaches("log_bus", "log_detector")
    assert reaches("log_detector", "log_alert_delivery")
    assert reaches("log_console", "log_search")
    assert reaches("log_console", "log_vectors")
    assert reaches("log_model_training", "log_detector")

    request = make_request(problem, guide, full)
    assert request["problem"]["requirements"].splitlines() == REQUIREMENTS
    assert request["problem"]["constraints"].splitlines() == CONSTRAINTS
    assert request["problem"]["requirementRevision"].startswith("legacy-")
    assert request["components"] == full["architecture"]["components"]
    assert request["connections"] == full["architecture"]["connections"]


def test_log_domain_tradeoffs_failures_security_and_no_score_promise():
    guide, _ = _load()
    text = json.dumps(guide, ensure_ascii=False).casefold()
    for phrase in (
        "drain", "logmine", "autoencoder", "inverted", "1m+", "100+",
        "30-second", "above-95%", "idempotent", "at-least-once", "replay",
        "quarantine", "late", "timeout", "failover", "tenant", "redact",
        "least-privilege", "critical", "forecast", "sample", "watermark",
        "provisional assumptions", "not measured outcomes or guarantees",
        "none of these targets is established by this draft alone",
    ):
        assert phrase in text, f"Missing domain or review caveat: {phrase}"
    assert "custom-component" not in {
        step.get("component", {}).get("componentType") for step in guide["steps"]
    }
