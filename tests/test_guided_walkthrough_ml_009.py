"""Frozen-brief, catalog, and connected-graph checks for ml_009."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "ml_009"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
STEP_TYPES = {"explanation", "add_component", "add_connection", "decision_point", "scale_trigger"}
CONNECTION_TYPES = {"api-call", "data-flow", "database-connection", "event-stream"}


def frozen_problem() -> dict:
    payload = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        rows = payload.get("problems", [payload] if payload.get("id") else [])
    else:
        rows = payload
    matches = [row for row in rows if row.get("id") == PROBLEM_ID]
    assert len(matches) == 1, f"Expected one frozen problem row for {PROBLEM_ID}"
    return matches[0]


def live_brief_block(problem: dict) -> str:
    lines = [
        f"Title: {problem['title']}",
        f"Description: {problem['description']}",
        "Requirements:",
        *(f"- {item}" for item in problem["requirements"]),
        "Constraints:",
        *(f"- {item}" for item in problem["constraints"]),
        "Hints:",
        *(f"- {item}" for item in problem.get("hints", [])),
    ]
    return "\n".join(lines)


def catalog_block(catalog: str, component_type: str) -> str:
    match = re.search(
        rf'(?ms)^  \{{\r?\n    id: "{re.escape(component_type)}",(?P<body>.*?)^  \}},',
        catalog,
    )
    assert match, f"Unknown component catalog ID {component_type!r}"
    return match.group("body")


def expected_anchors(problem: dict) -> set[str]:
    return {
        *(f"legacy-requirement:{index}" for index in range(1, len(problem["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(problem["constraints"]) + 1)),
    }


def load_guide() -> tuple[dict, GuidedWalkthrough]:
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def test_frozen_problem_brief_is_verbatim_and_this_remains_a_draft():
    problem = frozen_problem()
    raw, guide = load_guide()

    assert guide.problem_id == problem["id"] == PROBLEM_ID
    assert raw["version"].endswith("review-draft")
    assert guide.steps[0].content.startswith(live_brief_block(problem) + "\n\n")


def test_steps_phases_and_all_frozen_requirement_and_constraint_anchors_are_complete():
    problem = frozen_problem()
    raw, guide = load_guide()

    assert guide.totalSteps == len(guide.steps) == 45
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES for step in guide.steps)

    expected = expected_anchors(problem)
    mapped = {anchor for step in guide.steps for anchor in step.requirementIds}
    action_mapped = {
        anchor
        for step in guide.steps
        if step.type in {"add_component", "add_connection"}
        for anchor in step.requirementIds
    }
    assert mapped == expected
    assert action_mapped == expected

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(guide.steps[number - 1].phase == phase.name for number in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1
    assert raw["totalSteps"] == guide.totalSteps


def test_nodes_use_only_existing_catalog_components_and_supported_properties():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = [step["component"] for step in raw["steps"] if step["type"] == "add_component"]

    assert len(components) == 17
    assert len({component["nodeId"] for component in components}) == len(components)
    assert all(component["componentType"] != "custom-component" for component in components)

    for step in raw["steps"]:
        if step["type"] != "add_component":
            continue
        component = step["component"]
        properties = component["properties"]
        assert properties["componentName"] == component["label"]
        assert len(properties["purpose"]) >= 70
        block = catalog_block(catalog, component["componentType"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert set(properties) <= supported, (
            f"{step['id']} uses unsupported {component['componentType']} properties: "
            f"{sorted(set(properties) - supported)}"
        )


def test_ordered_actions_replay_to_one_connected_catalog_graph():
    raw, _ = load_guide()
    nodes = {}
    edge_ids = set()
    pairs = []

    for step in raw["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            assert component["nodeId"] not in nodes
            assert set(component["position"]) >= {"x", "y"}
            nodes[component["nodeId"]] = component
        elif step["type"] == "add_connection":
            connection = step["connection"]
            assert connection["edgeId"] not in edge_ids
            assert connection["connectionType"] in CONNECTION_TYPES
            assert connection["sourceNodeId"] in nodes
            assert connection["targetNodeId"] in nodes
            edge_ids.add(connection["edgeId"])
            pairs.append((connection["sourceNodeId"], connection["targetNodeId"]))

    assert len(nodes) == 17
    assert len(edge_ids) == 25
    neighbors = {node_id: set() for node_id in nodes}
    for source, target in pairs:
        neighbors[source].add(target)
        neighbors[target].add(source)
    reached = set()
    pending = deque(["sentiment_source_connectors"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == set(nodes)

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    assert len(architecture["components"]) == len(nodes)
    assert len(architecture["connections"]) == len(edge_ids)
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in architecture["connections"])


def test_quality_scale_language_and_uncertainty_are_explicitly_operationalized():
    raw, _ = load_guide()
    text = json.dumps(raw, ensure_ascii=False).casefold()
    for phrase in (
        "p95",
        "under 2 seconds",
        "above 85%",
        "1m+ posts per day",
        "20+ languages",
        "sarcasm",
        "slang",
        "emojis",
        "xlm-r",
        "change-point detection",
        "human review",
        "not an achieved result",
    ):
        assert phrase in text, f"Walkthrough does not make {phrase!r} operationally explicit"


def test_report_and_informal_text_anchors_match_the_actions_that_implement_them():
    problem = frozen_problem()
    raw, _ = load_guide()
    steps = {step["id"]: step for step in raw["steps"]}
    report_anchor = "legacy-requirement:7"
    sarcasm_anchor = "legacy-requirement:5"
    informal_anchor = "legacy-constraint:5"

    assert "automated sentiment reports" in problem["requirements"][6].casefold()
    assert report_anchor not in steps["sentiment_connect_live_trends_ui"]["requirementIds"]
    assert report_anchor in steps["sentiment_connect_warehouse"]["requirementIds"]
    assert report_anchor in steps["sentiment_connect_reports_ui"]["requirementIds"]

    assert "multiple social platforms" in problem["requirements"][5].casefold()
    assert informal_anchor not in steps["sentiment_connectors"]["requirementIds"]
    assert "legacy-requirement:6" in steps["sentiment_connectors"]["requirementIds"]

    model_step = steps["sentiment_multilingual_model"]
    assert sarcasm_anchor in model_step["requirementIds"]
    assert informal_anchor in model_step["requirementIds"]
    assert "sarcasm" in model_step["content"].casefold()
    assert "slang" in model_step["content"].casefold()
    assert "emoji" in model_step["content"].casefold()


def test_numeric_claims_are_brief_derived_and_alert_rules_remain_unquantified():
    raw, _ = load_guide()
    text = json.dumps(raw, ensure_ascii=False)

    percentages = set(re.findall(r"\b\d+(?:\.\d+)?\s*%", text))
    assert percentages == {"85%"}

    language_counts = set(re.findall(r"\b\d+(?:\.\d+)?\+?\s+languages?\b", text, re.IGNORECASE))
    assert language_counts == {"20+ languages"}
    assert not re.search(
        r"\b(?:English|Spanish|French|German|Chinese|Mandarin|Arabic|Hindi|Japanese|Korean|"
        r"Portuguese|Russian|Italian|Dutch|Turkish|Indonesian|Vietnamese|Thai|Bengali|Urdu|Swahili)\b",
        text,
        re.IGNORECASE,
    )

    durations = {
        (number, unit.casefold().rstrip("s"))
        for number, unit in re.findall(
            r"\b(\d+(?:\.\d+)?)\s*-?\s*(seconds?|minutes?|hours?|days?|weeks?|months?)\b",
            text,
            re.IGNORECASE,
        )
    }
    assert durations == {("2", "second")}

    steps = {step["id"]: step for step in raw["steps"]}
    alert_text = " ".join(
        json.dumps(steps[step_id], ensure_ascii=False)
        for step_id in (
            "sentiment_trend_analytics",
            "sentiment_shift_notifications",
            "sentiment_connect_alerts",
        )
    )
    numeric_alert_rule = re.compile(
        r"(?:\b(?:alert|significance|minimum[- ]volume|sample(?:[- ]size)?|threshold|time window|window)\b"
        r"[^\n]{0,40}\b\d+\b|\b\d+\b[^\n]{0,40}\b(?:alert|significance|minimum[- ]volume|"
        r"sample(?:[- ]size)?|threshold|time window|window)\b)",
        re.IGNORECASE,
    )
    assert not numeric_alert_rule.search(alert_text)
