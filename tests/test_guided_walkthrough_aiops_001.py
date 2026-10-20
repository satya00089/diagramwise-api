"""Local structural review of the frozen aiops_001 walkthrough draft.

These checks do not establish frontend apply/save parity or live assessment quality.
"""

import json
import re
from pathlib import Path

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / "aiops_001.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

REQUIREMENTS = [
    "Automatically detect incidents from monitoring signals",
    "Correlate related alerts into unified incidents",
    "Identify blast radius and affected services",
    "Suggest remediation based on historical resolutions",
    "Route incidents to appropriate on-call teams",
    "Track MTTD, MTTA, and MTTR metrics",
    "Generate post-incident reports automatically",
    "Learn from incident history to improve detection",
]
CONSTRAINTS = [
    "Incident detection within 2 minutes",
    "Alert correlation accuracy above 90%",
    "Handle 10k+ alerts per hour",
    "Reduce alert noise by 80%",
    "Support 100+ microservices in dependency graph",
]
TRACE_ACTIONS = {
    "legacy-requirement:1": {"im_02", "im_05", "im_08", "im_14"},
    "legacy-requirement:2": {"im_05", "im_07", "im_08", "im_11", "im_14"},
    "legacy-requirement:3": {"im_17", "im_18", "im_20", "im_22"},
    "legacy-requirement:4": {"im_35", "im_36", "im_38", "im_45", "im_46"},
    "legacy-requirement:5": {"im_24", "im_25", "im_27", "im_28", "im_34"},
    "legacy-requirement:6": {"im_13", "im_24", "im_28", "im_49", "im_50"},
    "legacy-requirement:7": {"im_51", "im_52", "im_53", "im_54", "im_55"},
    "legacy-requirement:8": {"im_35", "im_39", "im_56", "im_57", "im_58", "im_59"},
    "legacy-constraint:1": {"im_04", "im_05", "im_09", "im_14", "im_56", "im_59"},
    "legacy-constraint:2": {"im_11", "im_56", "im_58", "im_59"},
    "legacy-constraint:3": {"im_03", "im_04", "im_05", "im_06"},
    "legacy-constraint:4": {"im_05", "im_07", "im_49", "im_56", "im_59"},
    "legacy-constraint:5": {"im_17", "im_18", "im_20", "im_22"},
}


def _guide() -> dict:
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return GuidedWalkthrough.model_validate(raw).model_dump(exclude_none=True)


def _steps(guide: dict) -> dict[str, dict]:
    return {step["id"]: step for step in guide["steps"]}


def test_frozen_problem_brief_and_requirement_traceability():
    problem = next(
        row for row in json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
        if row["id"] == "aiops_001"
    )
    assert problem["title"] == "Design an Intelligent Incident Management System"
    assert problem["description"] == (
        "Design an AIOps-powered incident management system that automatically "
        "detects incidents, correlates alerts, identifies affected services, "
        "suggests remediation, and learns from past incident resolutions."
    )
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS

    guide = _guide()
    assert guide["problem_id"] == problem["id"]
    assert guide["version"].endswith("review-draft")
    steps = _steps(guide)
    assert set(TRACE_ACTIONS) == {
        *(f"legacy-requirement:{number}" for number in range(1, len(REQUIREMENTS) + 1)),
        *(f"legacy-constraint:{number}" for number in range(1, len(CONSTRAINTS) + 1)),
    }
    for requirement_id, action_ids in TRACE_ACTIONS.items():
        assert all(requirement_id in steps[action_id]["requirementIds"] for action_id in action_ids)
        assert all(
            steps[action_id]["type"] in {"add_component", "add_connection", "decision_point"}
            for action_id in action_ids
        )
    assigned = {requirement_id for step in guide["steps"] for requirement_id in step["requirementIds"]}
    assert assigned == set(TRACE_ACTIONS)


def test_schema_sequence_phases_and_explicit_actions():
    guide = _guide()
    steps = guide["steps"]
    assert guide["totalSteps"] == len(steps) == 60
    assert [step["stepNumber"] for step in steps] == list(range(1, 61))
    assert len({step["id"] for step in steps}) == len(steps)
    phase_numbers = [
        number
        for phase in guide["phases"]
        for number in range(phase["stepRange"][0], phase["stepRange"][1] + 1)
    ]
    assert phase_numbers == list(range(1, 61))
    assert all(
        step["phase"] == next(
            phase["name"] for phase in guide["phases"]
            if phase["stepRange"][0] <= step["stepNumber"] <= phase["stepRange"][1]
        ) for step in steps
    )

    kinds = [step["type"] for step in steps]
    assert kinds.count("add_component") == 20
    assert kinds.count("add_connection") == 28
    assert kinds.count("decision_point") == 7
    assert kinds.count("scale_trigger") == 2
    assert kinds.count("explanation") == 3
    assert all(step["content"].strip() and step["title"].strip() for step in steps)
    for step in steps:
        if step["type"] == "decision_point":
            assert step["decision"]["chosen"]
            assert step["decision"]["chosenReason"]
            assert len(step["decision"]["alternatives"]) >= 2
            assert step["componentUpdate"]["properties"]
        if step["type"] == "scale_trigger":
            assert all(step["scaleTrigger"][key] for key in ("metric", "action", "impact"))


def test_catalog_components_have_editable_semantic_properties():
    guide = _guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    seen = set()
    for step in guide["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            assert component["nodeId"] not in seen
            seen.add(component["nodeId"])
            assert component["componentType"] != "custom-component"
            assert len(component["properties"]["purpose"]) >= 65
            assert component["properties"]["componentName"] == component["label"]
            assert component["highlightReason"]
            properties = component["properties"]
            component_type = component["componentType"]
        elif step.get("componentUpdate"):
            assert step["componentUpdate"]["nodeId"] in seen
            properties = step["componentUpdate"]["properties"]
            component_type = next(
                action["component"]["componentType"] for action in guide["steps"]
                if action.get("component", {}).get("nodeId") == step["componentUpdate"]["nodeId"]
            )
        else:
            continue

        match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
        assert match is not None, f"{step['id']}: unknown catalog ID {component_type}"
        block_end = catalog.find("\n  },", match.start())
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', catalog[match.start():block_end]))
        assert set(properties) <= supported, f"{step['id']}: unsupported property"

    components = {
        step["component"]["nodeId"]: step["component"]
        for step in guide["steps"] if step["type"] == "add_component"
    }
    assert components["im_topology"]["properties"]["type"] == "Graph"
    assert components["im_alert_bus"]["properties"]["durable"] is True
    assert components["im_incident_db"]["properties"]["pitr"] is True
    assert components["im_auth"]["properties"]["mfa"] is True


def test_component_configuration_does_not_invent_numeric_sizing_or_retention():
    guide = _guide()
    for step in guide["steps"]:
        if step["type"] != "add_component":
            continue
        numeric_properties = {
            key: value
            for key, value in step["component"]["properties"].items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        assert not numeric_properties, f"{step['id']} invents numeric component settings: {numeric_properties}"

    prose = " ".join(
        [phase["description"] for phase in guide["phases"]]
        + [step["content"] for step in guide["steps"]]
        + [
            text
            for step in guide["steps"]
            for text in (
                step.get("scaleTrigger", {}).get("metric", ""),
                step.get("scaleTrigger", {}).get("action", ""),
                step.get("scaleTrigger", {}).get("impact", ""),
            )
        ]
    ).lower()
    assert "100 events/sec" not in prose
    assert "24-hour retention" not in prose
    assert "response objective" not in prose


def test_accuracy_target_is_anchored_to_validation_not_score_serving():
    steps = _steps(_guide())
    accuracy = "legacy-constraint:2"
    assert accuracy not in steps["im_08"]["requirementIds"]
    assert accuracy not in steps["im_10"]["requirementIds"]
    assert accuracy in steps["im_11"]["requirementIds"]
    assert "accuracy above 90%" in steps["im_11"]["content"]


def test_lifecycle_metric_boundaries_are_unambiguous_and_no_extra_slo_is_claimed():
    steps = _steps(_guide())
    content = steps["im_49"]["content"].lower()
    assert "first qualifying signal to incident detection" in content
    assert "first page to authenticated acknowledgement" in content
    assert "detection to verified resolution" in content
    assert "without adding percentile slos absent from the brief" in content
    assert steps["im_49"]["component"]["label"] == "Incident Lifecycle Metrics"


def test_replay_builds_connected_incident_graph_and_records_decisions():
    guide = _guide()
    built = build_architecture(guide)
    architecture = built["architecture"]
    nodes = {node["id"]: node for node in architecture["components"]}
    edges = {edge["id"]: edge for edge in architecture["connections"]}
    assert len(nodes) == 20
    assert len(edges) == 28
    assert len(built["appliedStepIds"]) == 55
    assert len(built["acceptedDecisions"]) == 7
    assert len(built["explanationOnlyStepIds"]) == 5
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in edges.values())

    adjacency = {node_id: set() for node_id in nodes}
    for edge in edges.values():
        adjacency[edge["source"]].add(edge["target"])
        adjacency[edge["target"]].add(edge["source"])
    reached = set()
    frontier = ["im_monitoring"]
    while frontier:
        node_id = frontier.pop()
        if node_id not in reached:
            reached.add(node_id)
            frontier.extend(adjacency[node_id] - reached)
    assert reached == nodes.keys()
    assert all(adjacency.values())
    assert nodes["im_inference"]["properties"]["purpose"].startswith("Versioned correlation scoring")
    assert "human approval" in nodes["im_runbook_worker"]["properties"]["purpose"]
    assert "human-reviewed" in nodes["im_training"]["properties"]["purpose"]

    # A viewed decision must not silently become an accepted design change.
    without_approval = build_architecture(
        guide,
        applied_step_ids=[step["id"] for step in guide["steps"] if step["id"] != "im_45"],
    )
    worker = next(
        node for node in without_approval["architecture"]["components"]
        if node["id"] == "im_runbook_worker"
    )
    assert worker["properties"]["purpose"] != nodes["im_runbook_worker"]["properties"]["purpose"]
    assert len(without_approval["acceptedDecisions"]) == 6


def test_thresholds_and_failure_paths_are_explicit_in_actions():
    steps = _steps(_guide())
    assert "target is within 2 minutes" in steps["im_01"]["content"]
    for step_id, terms in {
        "im_03": ("10k+ alerts per hour", "bursts"),
        "im_07": ("80% noise reduction", "distinct high-severity incident"),
        "im_11": ("above 90%", "false merges", "fall back"),
        "im_17": ("100+ microservices", "version"),
        "im_22": ("stale", "directly affected owner"),
        "im_34": ("acknowledgement", "fallback"),
        "im_45": ("approves", "destructive"),
        "im_49": ("MTTD", "MTTA", "MTTR", "first page", "percentile SLOs absent"),
        "im_51": ("verified resolution", "review"),
        "im_59": ("hold out", "roll back"),
    }.items():
        content = steps[step_id]["content"].lower()
        assert all(term.lower() in content for term in terms), step_id
    assert "2-minute" in steps["im_12"]["scaleTrigger"]["metric"]
    assert "detection within 2 minutes" in steps["im_12"]["scaleTrigger"]["impact"]
    assert "10k+ alerts per hour" in steps["im_60"]["content"]
    assert "under burst and replay" not in steps["im_60"]["content"]
