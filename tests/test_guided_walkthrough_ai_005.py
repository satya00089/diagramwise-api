"""Structural review checks for the fraud-detection walkthrough draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "ai_005"
GUIDE_PATH = ROOT / "data/guided-walkthroughs/ai_005.json"
PROBLEMS_PATH = ROOT / "tests/fixtures/walkthroughs/problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic/src/config/components.ts"
FROZEN_BRIEF = {
    "id": PROBLEM_ID,
    "slug": "design-an-ai-based-real-time-fraud-detection-system",
    "title": "Design an AI-Based Real-time Fraud Detection System",
    "description": "Design an AI system that detects fraudulent transactions in real-time using ML models, graph analysis, and behavioral patterns, with adaptive learning from new fraud patterns.",
    "requirements": [
        "Score transactions in real-time",
        "Detect known and novel fraud patterns",
        "Analyze user behavioral biometrics",
        "Build fraud rings using graph analysis",
        "Adapt models to evolving fraud tactics",
        "Minimize false positives for legitimate users",
        "Provide explainable fraud decisions",
        "Generate regulatory compliance reports",
    ],
    "constraints": [
        "Scoring latency under 50ms per transaction",
        "Process 50k+ transactions per second",
        "False positive rate below 0.1%",
        "Fraud detection rate above 95%",
        "Models must be explainable for compliance",
    ],
    "hints": [
        "Use ensemble models (gradient boosting + neural networks)",
        "Implement feature stores for real-time feature computation",
        "Use graph neural networks for relationship analysis",
        "Implement velocity checks and rule-based pre-filters",
        "Use streaming frameworks for real-time scoring",
        "Implement online learning for model adaptation",
    ],
}
EXPECTED_ANCHORS = {
    *(f"legacy-requirement:{index}" for index in range(1, 9)),
    *(f"legacy-constraint:{index}" for index in range(1, 6)),
}
ACTION_TYPES = {"add_component", "add_connection", "update_component"}
STEP_TYPES = {"explanation", "add_component", "add_connection", "decision_point", "scale_trigger", "update_component"}
ANCHOR_EVIDENCE = {
    "legacy-requirement:1": ("transaction", "scoring"),
    "legacy-requirement:2": ("novelty", "anomaly"),
    "legacy-requirement:3": ("behavioral-biometric", "freshness"),
    "legacy-requirement:4": ("relationship", "graph"),
    "legacy-requirement:5": ("retraining", "confirmed outcomes"),
    "legacy-requirement:6": ("false-positive", "recall"),
    "legacy-requirement:7": ("reason codes", "model version"),
    "legacy-requirement:8": ("compliance", "reporting"),
    "legacy-constraint:1": ("under-50ms", "scoring"),
    "legacy-constraint:2": ("50k+", "transactions/sec"),
    "legacy-constraint:3": ("below-0.1%", "false-positive"),
    "legacy-constraint:4": ("above-95%", "detection"),
    "legacy-constraint:5": ("compliance", "reports"),
}
EXPECTED_ANCHOR_CARRIERS = {
    "legacy-requirement:1": {
        "fraud_s02", "fraud_s03", "fraud_s04", "fraud_s05", "fraud_s06",
        "fraud_s09", "fraud_s10", "fraud_s14", "fraud_s15", "fraud_s22", "fraud_s38",
    },
    "legacy-requirement:2": {"fraud_s14", "fraud_s16", "fraud_s38", "fraud_s39", "fraud_s40"},
    "legacy-requirement:3": {
        "fraud_s11", "fraud_s12", "fraud_s15", "fraud_s21", "fraud_s27",
        "fraud_s28", "fraud_s29", "fraud_s38", "fraud_s40", "fraud_s41",
    },
    "legacy-requirement:4": {
        "fraud_s19", "fraud_s20", "fraud_s27", "fraud_s28", "fraud_s30", "fraud_s38", "fraud_s41",
    },
    "legacy-requirement:5": {
        "fraud_s17", "fraud_s18", "fraud_s25", "fraud_s26", "fraud_s27", "fraud_s28",
        "fraud_s29", "fraud_s30", "fraud_s31", "fraud_s32", "fraud_s33", "fraud_s38", "fraud_s41",
    },
    "legacy-requirement:6": {
        "fraud_s09", "fraud_s14", "fraud_s16", "fraud_s22", "fraud_s31", "fraud_s32",
        "fraud_s33", "fraud_s38", "fraud_s40",
    },
    "legacy-requirement:7": {
        "fraud_s02", "fraud_s05", "fraud_s07", "fraud_s08", "fraud_s09", "fraud_s10",
        "fraud_s14", "fraud_s17", "fraud_s18", "fraud_s22", "fraud_s31", "fraud_s33", "fraud_s34", "fraud_s35",
        "fraud_s37", "fraud_s38", "fraud_s39",
    },
    "legacy-requirement:8": {
        "fraud_s07", "fraud_s08", "fraud_s25", "fraud_s26", "fraud_s34", "fraud_s35", "fraud_s36", "fraud_s37",
    },
    "legacy-constraint:1": {
        "fraud_s05", "fraud_s09", "fraud_s11", "fraud_s12", "fraud_s14", "fraud_s15",
        "fraud_s20", "fraud_s21", "fraud_s22", "fraud_s38", "fraud_s39", "fraud_s40",
    },
    "legacy-constraint:2": {
        "fraud_s03", "fraud_s04", "fraud_s05", "fraud_s06", "fraud_s11", "fraud_s12", "fraud_s15", "fraud_s20", "fraud_s21",
        "fraud_s25", "fraud_s26", "fraud_s27", "fraud_s28", "fraud_s29", "fraud_s30", "fraud_s38", "fraud_s41",
    },
    "legacy-constraint:3": {"fraud_s22", "fraud_s31", "fraud_s32", "fraud_s33", "fraud_s38", "fraud_s40"},
    "legacy-constraint:4": {"fraud_s22", "fraud_s31", "fraud_s32", "fraud_s33", "fraud_s38", "fraud_s40"},
    "legacy-constraint:5": {
        "fraud_s14", "fraud_s22", "fraud_s31", "fraud_s33", "fraud_s34", "fraud_s35",
        "fraud_s36", "fraud_s37", "fraud_s38", "fraud_s39", "fraud_s40",
    },
}


def load_rows() -> tuple[dict, dict]:
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    return problem, json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"{step_id}: unknown component type {component_type}"
    end = catalog.find("\n  },", match.start())
    assert end > match.start(), f"{step_id}: incomplete catalog entry"
    return catalog[match.start() : end]


def test_frozen_problem_row_matches_the_scoring_problem():
    problem, raw = load_rows()
    for field, expected in FROZEN_BRIEF.items():
        assert problem.get(field) == expected
    assert problem["category"] == "AI - Fraud Detection"
    assert problem["domain"] == "aiml"
    assert problem["difficulty"] == "Hard"
    assert problem["estimated_time"] == "60-90 minutes"
    assert "has_guided_walkthrough" not in raw


def test_schema_phases_and_every_brief_anchor_has_graph_action_evidence():
    _, raw = load_rows()
    guide = GuidedWalkthrough.model_validate(raw)
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 43
    assert [step.stepNumber for step in guide.steps] == list(range(1, 44))
    assert len({step.id for step in guide.steps}) == 43
    assert all(step.type in STEP_TYPES and step.title.strip() and step.content.strip() for step in guide.steps)

    next_number = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_number <= end <= guide.totalSteps
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_number = end + 1
    assert next_number == guide.totalSteps + 1

    mapped = {anchor for step in raw["steps"] for anchor in step.get("requirementIds", [])}
    actionable = {
        anchor
        for step in raw["steps"]
        if step["type"] in ACTION_TYPES
        for anchor in step.get("requirementIds", [])
    }
    assert mapped == actionable == EXPECTED_ANCHORS
    actual_anchor_carriers = {
        anchor: {
            step["id"]
            for step in raw["steps"]
            if step["type"] in ACTION_TYPES and anchor in step.get("requirementIds", [])
        }
        for anchor in EXPECTED_ANCHORS
    }
    assert actual_anchor_carriers == EXPECTED_ANCHOR_CARRIERS
    for anchor, phrases in ANCHOR_EVIDENCE.items():
        carriers = [
            step for step in raw["steps"]
            if step["type"] in ACTION_TYPES and anchor in step.get("requirementIds", [])
        ]
        assert any(all(phrase in json.dumps(step, ensure_ascii=False).casefold() for phrase in phrases) for step in carriers), anchor


def test_numeric_and_explainability_targets_are_independent_unclaimed_gates():
    _, raw = load_rows()
    steps = {step["id"]: step for step in raw["steps"]}
    validation = steps["fraud_s42"]["content"].casefold()
    for target in (
        "under-50ms",
        "50k+ transactions per second",
        "false-positive rate below 0.1%",
        "fraud detection rate above 95%",
        "explanation coverage",
        "fidelity",
    ):
        assert target in validation
    assert "five independent" in validation
    assert "no numeric explainability threshold" in validation
    assert "numeric explainability threshold or jurisdiction-specific regulatory threshold" in validation
    assert "design alone cannot prove" in validation

    tradeoff = steps["fraud_s23"]["content"].casefold()
    assert "report and gate each result independently" in tradeoff
    assert "passing one does not compensate for failing the other" in tradeoff

    evaluation = steps["fraud_s31"]["content"].casefold()
    assert "false-positive-below-0.1%" in evaluation
    assert "detection-above-95%" in evaluation
    assert "explainability" in evaluation
    assert "separate promotion gates" in evaluation


def test_components_use_only_catalog_types_and_supported_properties():
    _, raw = load_rows()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}
    for step in raw["steps"]:
        if step["type"] != "add_component":
            continue
        component = step["component"]
        assert component["nodeId"] not in components
        assert set(component["position"]) == {"x", "y"}
        properties = component["properties"]
        assert set(properties) == {"componentName", "purpose"}
        assert properties["componentName"] == component["label"]
        assert properties["purpose"].strip()
        block = catalog_block(catalog, component["componentType"], step["id"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert set(properties) <= supported
        components[component["nodeId"]] = component
    assert len(components) == 16


def test_ordered_actions_replay_to_one_connected_graph():
    _, raw = load_rows()
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    node_ids = {step["component"]["nodeId"] for step in raw["steps"] if step["type"] == "add_component"}
    edges = [step["connection"] for step in raw["steps"] if step["type"] == "add_connection"]
    assert {component["id"] for component in architecture["components"]} == node_ids
    assert len(architecture["components"]) == 16
    assert len(architecture["connections"]) == len(edges) == 21
    assert len(replay["appliedStepIds"]) == 37

    neighbors = {node_id: set() for node_id in node_ids}
    for edge in edges:
        neighbors[edge["sourceNodeId"]].add(edge["targetNodeId"])
        neighbors[edge["targetNodeId"]].add(edge["sourceNodeId"])
    reached, pending = set(), deque(["fraud_clients"])
    while pending:
        current = pending.popleft()
        if current in reached:
            continue
        reached.add(current)
        pending.extend(neighbors[current] - reached)
    assert reached == node_ids
