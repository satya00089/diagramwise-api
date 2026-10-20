"""Frozen-brief, catalog, and replay checks for the alert-correlation review draft."""

import json
from collections import deque
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "data/guided-walkthroughs/aiops_005.json"
PROBLEMS_PATH = ROOT / "tests/fixtures/walkthroughs/problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic/src/config/components.ts"

REQUIREMENTS = [
    "Correlate alerts from multiple monitoring tools",
    "Deduplicate redundant and flapping alerts",
    "Group related alerts into incidents",
    "Suppress non-actionable alerts intelligently",
    "Rank alerts by severity and business impact",
    "Provide context enrichment for each alert",
    "Handle alert storms during major outages",
    "Learn from operator actions on alert handling",
]
CONSTRAINTS = [
    "Alert correlation latency under 10 seconds",
    "Reduce alert volume by 80%",
    "Zero suppression of critical actionable alerts",
    "Handle 100k+ alerts per hour",
    "Support integration with 10+ monitoring tools",
]
ANCHORS = {
    *(f"legacy-requirement:{number}" for number in range(1, 9)),
    *(f"legacy-constraint:{number}" for number in range(1, 6)),
}
ACTION_TYPES = {"add_component", "add_connection", "decision_point"}
CONNECTION_TYPES = {
    "http", "websocket", "api-call", "data-flow", "event-stream",
    "database-connection", "message-queue",
}
DIRECT_ACTION_EVIDENCE = {
    "legacy-requirement:1": {"alert_02", "alert_07"},
    "legacy-requirement:2": {"alert_11", "alert_13"},
    "legacy-requirement:3": {"alert_16", "alert_22"},
    "legacy-requirement:4": {"alert_25", "alert_28"},
    "legacy-requirement:5": {"alert_25"},
    "legacy-requirement:6": {"alert_14", "alert_18"},
    "legacy-requirement:7": {"alert_09", "alert_11"},
    "legacy-requirement:8": {"alert_37", "alert_40"},
    "legacy-constraint:1": {"alert_16", "alert_19"},
    "legacy-constraint:2": {"alert_25", "alert_48"},
    "legacy-constraint:3": {"alert_28", "alert_31"},
    "legacy-constraint:4": {"alert_09", "alert_12"},
    "legacy-constraint:5": {"alert_02", "alert_07"},
}
PRECISE_ANCHOR_SETS = {
    "alert_15": {
        "legacy-requirement:1", "legacy-requirement:3", "legacy-constraint:1"
    },
    "alert_23": {"legacy-requirement:2", "legacy-requirement:7"},
    "alert_24": {"legacy-requirement:2", "legacy-requirement:7"},
    "alert_29": {
        "legacy-requirement:3", "legacy-requirement:5", "legacy-constraint:3"
    },
}


def _load() -> tuple[dict, dict]:
    guide = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == "aiops_005")
    return guide, problem


def _catalog_entry(catalog: str, component_id: str) -> str:
    entry = re.search(
        rf'(?ms)^ {{4}}id: "{re.escape(component_id)}",.*?^ {{2}}\}},?',
        catalog,
    )
    assert entry, f"Unknown component catalog ID: {component_id}"
    return entry.group(0)


def test_frozen_brief_schema_sequence_and_actionable_traceability():
    guide, problem = _load()
    parsed = GuidedWalkthrough.model_validate(guide)

    assert problem["title"] == "Design an AI-Powered Alert Correlation and Noise Reduction System"
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert parsed.problem_id == problem["id"] == "aiops_005"
    assert parsed.version == "1.0-review"
    assert parsed.totalSteps == len(parsed.steps) == 49
    assert [step.stepNumber for step in parsed.steps] == list(range(1, 50))
    assert len({step.id for step in parsed.steps}) == 49

    phase_by_number = {
        number: phase.name
        for phase in parsed.phases
        for number in range(phase.stepRange[0], phase.stepRange[1] + 1)
    }
    assert list(phase_by_number) == list(range(1, 50))
    assert all(phase_by_number[step.stepNumber] == step.phase for step in parsed.steps)

    all_anchors = {anchor for step in parsed.steps for anchor in step.requirementIds}
    action_anchors = {
        anchor
        for step in parsed.steps
        if step.type in ACTION_TYPES
        for anchor in step.requirementIds
    }
    assert all_anchors == action_anchors == ANCHORS
    for phrase in REQUIREMENTS + CONSTRAINTS:
        assert phrase in parsed.steps[0].content
        assert phrase in parsed.steps[-1].content or phrase in parsed.steps[0].content


def test_each_frozen_brief_item_has_direct_action_evidence():
    guide, _ = _load()
    steps = {step["id"]: step for step in guide["steps"]}

    for anchor, evidence_ids in DIRECT_ACTION_EVIDENCE.items():
        for step_id in evidence_ids:
            step = steps[step_id]
            assert step["type"] in ACTION_TYPES
            assert anchor in step["requirementIds"]

    for step_id, expected_anchors in PRECISE_ANCHOR_SETS.items():
        assert set(steps[step_id]["requirementIds"]) == expected_anchors


def test_unspecified_capacity_and_window_values_are_not_presented_as_defaults():
    guide, _ = _load()
    sizing_properties = {"instances", "partitions", "replication", "retention"}

    for step in guide["steps"]:
        component = step.get("component")
        if component:
            assert sizing_properties.isdisjoint(component["properties"])

    serialized = json.dumps(guide)
    for unsupported_value in (
        "3-second", "16 log partitions", "24-hour retention",
        "three service instances", "p99 correlation", "28 alerts/second",
    ):
        assert unsupported_value not in serialized


def test_actions_use_supported_catalog_ids_properties_and_decisions():
    guide, _ = _load()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}
    edge_ids = set()
    counts = {kind: 0 for kind in (
        "add_component", "add_connection", "decision_point", "scale_trigger", "explanation"
    )}

    for step in guide["steps"]:
        kind = step["type"]
        assert kind in counts
        counts[kind] += 1
        if kind == "add_component":
            component = step["component"]
            node_id = component["nodeId"]
            assert node_id not in components
            assert component["componentType"] != "custom"
            assert {"x", "y"} == component["position"].keys()
            components[node_id] = component
        elif kind == "add_connection":
            edge = step["connection"]
            assert edge["edgeId"] not in edge_ids
            edge_ids.add(edge["edgeId"])
            assert edge["sourceNodeId"] in components
            assert edge["targetNodeId"] in components
            assert edge["connectionType"] in CONNECTION_TYPES
            assert edge["label"] and edge["description"]
        elif kind == "decision_point":
            decision = step["decision"]
            assert decision["question"] and decision["chosen"] and decision["chosenReason"]
            assert len(decision["alternatives"]) >= 2
            assert all(row["option"] and row["tradeoff"] for row in decision["alternatives"])
            assert step["componentUpdate"]["nodeId"] in components
        elif kind == "scale_trigger":
            assert all(step["scaleTrigger"][field] for field in ("metric", "action", "impact"))

        if kind == "add_component" or step.get("componentUpdate"):
            component = (
                step["component"] if kind == "add_component"
                else components[step["componentUpdate"]["nodeId"]]
            )
            props = (
                component["properties"] if kind == "add_component"
                else step["componentUpdate"]["properties"]
            )
            entry = _catalog_entry(catalog, component["componentType"])
            supported = set(re.findall(r'\bkey:\s*"([^"]+)"', entry))
            assert props and set(props) <= supported
            if kind == "add_component":
                assert {"componentName", "purpose"} <= props.keys()
                assert props["componentName"] == component["label"]
                assert len(props["purpose"]) >= 60

    assert counts == {
        "add_component": 18,
        "add_connection": 24,
        "decision_point": 4,
        "scale_trigger": 1,
        "explanation": 2,
    }
    assert components["alert_ingest"]["properties"]["authentication"] == "API Key"
    assert components["alert_dedup"]["properties"]["engine"] == "Apache Flink"
    assert components["alert_delivery"]["properties"]["channels"] == "All"
    assert components["alert_learning"]["properties"]["tasks"] == "Data Processing"


def test_replay_builds_connected_incident_critical_and_feedback_paths():
    guide, problem = _load()
    full = build_architecture(guide)
    action_ids = [step["id"] for step in guide["steps"] if step["type"] in ACTION_TYPES]
    applied = build_architecture(guide, applied_step_ids=action_ids)

    assert full["architecture"] == applied["architecture"]
    assert full["appliedStepIds"] == action_ids
    assert len(full["acceptedDecisions"]) == 4
    assert [row["stepId"] for row in full["acceptedDecisions"]] == [
        "alert_13", "alert_22", "alert_28", "alert_48"
    ]
    assert full["explanationOnlyStepIds"] == ["alert_01", "alert_47", "alert_49"]

    architecture = full["architecture"]
    nodes = {row["id"]: row for row in architecture["components"]}
    edges = architecture["connections"]
    assert len(nodes) == 18
    assert len(edges) == 24
    assert all(node["properties"].get("purpose") for node in nodes.values())
    assert nodes["alert_dedup"]["properties"]["purpose"].startswith("Use tenant-scoped fingerprint")
    assert "never suppress critical" in nodes["alert_policy"]["properties"]["purpose"]

    outgoing = {node_id: set() for node_id in nodes}
    undirected = {node_id: set() for node_id in nodes}
    for edge in edges:
        outgoing[edge["source"]].add(edge["target"])
        undirected[edge["source"]].add(edge["target"])
        undirected[edge["target"]].add(edge["source"])

    visited = set()
    pending = deque(["alert_sources"])
    while pending:
        current = pending.popleft()
        if current not in visited:
            visited.add(current)
            pending.extend(undirected[current] - visited)
    assert visited == set(nodes)

    def reaches(source: str, target: str) -> bool:
        seen = set()
        pending_nodes = [source]
        while pending_nodes:
            current = pending_nodes.pop()
            if current == target:
                return True
            if current not in seen:
                seen.add(current)
                pending_nodes.extend(outgoing[current] - seen)
        return False

    assert reaches("alert_sources", "alert_incidents")
    assert reaches("alert_sources", "alert_console")
    assert reaches("alert_log", "alert_archive")
    assert reaches("alert_correlator", "alert_policy")
    assert reaches("alert_correlator", "alert_delivery")
    assert reaches("alert_console", "alert_learning")
    assert reaches("alert_console", "alert_similarity")
    assert ("alert_correlator", "alert_delivery") in {
        (edge["source"], edge["target"]) for edge in edges
    }

    request = make_request(problem, guide, applied)
    assert request["problem"]["requirements"].splitlines() == REQUIREMENTS
    assert request["problem"]["constraints"].splitlines() == CONSTRAINTS
    assert request["components"] == architecture["components"]
    assert request["connections"] == architecture["connections"]
