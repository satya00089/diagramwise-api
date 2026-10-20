"""Frozen-brief, catalog, and graph checks for the dynamic pricing draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "ml_008"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

LIVE_BRIEF = {
    "title": "Design a Dynamic Pricing Engine",
    "description": (
        "Design an ML-driven dynamic pricing engine that optimizes prices in "
        "real-time based on demand, competition, inventory levels, and customer "
        "segments to maximize revenue."
    ),
    "requirements": [
        "Predict demand elasticity per product",
        "Monitor competitor prices in real-time",
        "Optimize prices for revenue or margin targets",
        "Segment customers for price personalization",
        "Handle inventory-aware pricing",
        "Implement price change guardrails and constraints",
        "A/B test pricing strategies",
        "Provide pricing dashboards and analytics",
    ],
    "constraints": [
        "Price updates within 5 minutes of demand changes",
        "Revenue improvement above 5% vs static pricing",
        "Respect price change frequency limits",
        "Handle 100k+ SKUs",
        "Comply with pricing regulations",
    ],
    "hints": [
        "Use price elasticity models (log-linear demand curves)",
        "Implement contextual bandits for exploration vs exploitation",
        "Use causal inference to estimate price sensitivity",
        "Implement constraint optimization for business rules",
        "Use reinforcement learning for long-term revenue optimization",
        "Build competitor price monitoring with web scraping pipelines",
    ],
}

STEP_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "decision_point",
    "scale_trigger",
}
CONNECTION_TYPES = {
    "api-call",
    "data-flow",
    "database-connection",
    "event-stream",
}


def live_brief_block() -> str:
    lines = [
        f"Title: {LIVE_BRIEF['title']}",
        f"Description: {LIVE_BRIEF['description']}",
        "Requirements:",
        *(f"- {item}" for item in LIVE_BRIEF["requirements"]),
        "Constraints:",
        *(f"- {item}" for item in LIVE_BRIEF["constraints"]),
        "Hints:",
        *(f"- {item}" for item in LIVE_BRIEF["hints"]),
    ]
    return "\n".join(lines)


def load_guide() -> tuple[dict, GuidedWalkthrough]:
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def catalog_block(catalog: str, component_type: str) -> str:
    match = re.search(
        rf'(?ms)^  \{{\r?\n    id: "{re.escape(component_type)}",(?P<body>.*?)^  \}},',
        catalog,
    )
    assert match, f"Unknown component catalog ID {component_type!r}"
    return match.group("body")


def expected_anchors() -> set[str]:
    return {
        *(f"legacy-requirement:{index}" for index in range(1, len(LIVE_BRIEF["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(LIVE_BRIEF["constraints"]) + 1)),
    }


def test_live_title_description_requirements_constraints_and_hints_are_verbatim():
    raw, guide = load_guide()
    assert guide.problem_id == PROBLEM_ID
    first_step = guide.steps[0]
    assert first_step.content.startswith(live_brief_block() + "\n\n")
    assert raw["version"].endswith("review-draft")


def test_steps_phases_and_requirement_anchors_are_ordered_and_complete():
    raw, guide = load_guide()
    assert guide.totalSteps == len(guide.steps) == 57
    assert [step.stepNumber for step in guide.steps] == list(range(1, 58))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES for step in guide.steps)

    expected = expected_anchors()
    mapped = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert mapped == expected
    action_mapped = {
        anchor
        for step in guide.steps
        if step.type in {"add_component", "add_connection"}
        for anchor in step.requirementIds
    }
    assert action_mapped == expected

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(guide.steps[number - 1].phase == phase.name for number in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1


def test_components_use_catalog_properties_and_only_real_gaps_are_custom():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step["type"] == "add_component"
    }
    assert len(additions) == 18

    custom_labels = {
        component["label"]
        for component in additions.values()
        if component["componentType"] == "custom-component"
    }
    assert custom_labels == {
        "Commerce, Inventory & Customer Context",
        "Competitor Price Collection",
    }

    for step in raw["steps"]:
        if step["type"] != "add_component":
            continue
        component = step["component"]
        assert component["properties"]["componentName"] == component["label"]
        assert len(component["properties"]["purpose"]) >= 70
        block = catalog_block(catalog, component["componentType"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert set(component["properties"]) <= supported, (
            f"{step['id']} uses unsupported {component['componentType']} properties: "
            f"{sorted(set(component['properties']) - supported)}"
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

    assert len(nodes) == 18
    assert len(edge_ids) == 27
    neighbors = {node_id: set() for node_id in nodes}
    for source, target in pairs:
        neighbors[source].add(target)
        neighbors[target].add(source)
    reached = set()
    pending = deque(["price_context_sources"])
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
    assert all(
        edge["source"] in nodes and edge["target"] in nodes
        for edge in architecture["connections"]
    )


def test_supplied_targets_and_hint_topics_are_taught_without_claiming_results():
    raw, _ = load_guide()
    text = json.dumps(raw, ensure_ascii=False).casefold()
    for phrase in (
        "within 5 minutes of demand changes",
        "above 5% vs static pricing",
        "100k+ skus",
        "log-linear demand curve",
        "contextual bandits",
        "causal inference",
        "constraint optimization",
        "reinforcement learning",
        "competitor-price observations",
        "not results or derived capacity estimates",
        "does not establish that the 5-minute or above-5% target is achieved",
    ):
        assert phrase in text, f"Walkthrough does not explicitly cover {phrase!r}"


def test_ab_analysis_checks_seasonality_spillover_and_independent_guardrails():
    raw, _ = load_guide()
    steps = {step["id"]: step for step in raw["steps"]}
    experiment = steps["price_38"]
    experiment_text = json.dumps(experiment, ensure_ascii=False).casefold()

    for phrase in (
        "seasonality",
        "spill over",
        "report the limitation",
        "frequency and regulatory eligibility gates",
        "guardrail outcomes separately from revenue lift",
    ):
        assert phrase in experiment_text, f"A/B analysis omits {phrase!r}"

    # The revenue-lift target remains an outcome, not a promise or a guardrail.
    target_text = steps["price_39"]["content"].casefold()
    assert "above 5%" in target_text
    assert "do not describe the target as achieved" in target_text


def test_anchors_distinguish_entry_policy_and_uplift_evaluation():
    raw, _ = load_guide()
    steps = {step["id"]: step for step in raw["steps"]}

    assert steps["price_06"]["requirementIds"] == ["legacy-requirement:3"]
    assert "legacy-requirement:6" in steps["price_03"]["requirementIds"]
    assert "legacy-requirement:6" in steps["price_28"]["requirementIds"]
    assert "legacy-constraint:2" in steps["price_38"]["requirementIds"]
    assert "legacy-constraint:2" in steps["price_40"]["requirementIds"]
    assert "legacy-constraint:2" in steps["price_41"]["requirementIds"]
    assert "legacy-constraint:2" not in steps["price_43"]["requirementIds"]
    assert "legacy-constraint:2" not in steps["price_44"]["requirementIds"]
