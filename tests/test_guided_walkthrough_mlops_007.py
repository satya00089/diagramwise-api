"""Frozen-brief, catalog, and architecture checks for mlops_007."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "mlops_007"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": "mlops_007",
    "title": "Design an A/B Testing Framework for ML Models",
    "slug": "design-an-a-b-testing-framework-for-ml-models",
    "description": (
        "Design an A/B testing and experimentation framework specifically for ML models in production, "
        "supporting traffic splitting, statistical analysis, multi-armed bandits, and automated experiment conclusion."
    ),
    "difficulty": "Hard",
    "category": "MLOps - Experimentation",
    "domain": "aiml",
    "estimated_time": "60-90 minutes",
    "requirements": [
        "Route traffic between model variants",
        "Implement statistically rigorous A/B tests",
        "Support multi-armed bandit experiments",
        "Track experiment metrics and outcomes",
        "Handle interaction effects between experiments",
        "Automate experiment conclusion decisions",
        "Provide experiment dashboards and reports",
        "Support feature flag-based model selection",
    ],
    "constraints": [
        "Traffic routing latency under 5ms",
        "Statistical significance at p < 0.05",
        "Support 50+ concurrent experiments",
        "Handle metric corrections (novelty effect, etc.)",
        "Consistent user assignment across sessions",
    ],
    "hints": [
        "Use consistent hashing for user bucketing",
        "Implement sequential testing for early stopping",
        "Use Bayesian methods for faster experiment conclusion",
        "Implement CUPED for variance reduction",
        "Use holdback groups for long-term measurement",
        "Implement interleaving for ranking model comparison",
    ],
    "tags": ["mlops", "ab-testing", "experimentation", "statistics", "traffic-routing", "bandits"],
    "companies": ["Netflix", "Spotify", "LinkedIn", "Uber"],
}

ACTION_TYPES = {"add_component", "add_connection", "update_component"}
STEP_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "update_component",
    "decision_point",
    "scale_trigger",
    "conclusion",
}
CONNECTION_TYPES = {"api-call", "data-flow", "database-connection", "event-stream"}


def load_guide() -> dict:
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def catalog_component_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'(?m)^\s*id:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"unknown catalog component type {component_type!r}"
    end = catalog.find("\n  },", match.start())
    assert end != -1, f"could not find catalog block end for {component_type!r}"
    return catalog[match.start() : end]


def expected_anchors() -> set[str]:
    return {
        *(f"legacy-requirement:{index}" for index in range(1, len(FROZEN_BRIEF["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(FROZEN_BRIEF["constraints"]) + 1)),
    }


def test_local_draft_preserves_the_exact_live_brief():
    raw = load_guide()
    text = json.dumps(raw, ensure_ascii=False).casefold()

    assert raw["problem_id"] == FROZEN_BRIEF["id"]
    assert raw["version"] == "1.0"
    assert raw.get("requirementRevision") is None
    assert raw["totalSteps"] == len(raw["steps"]) == 60
    for field in (
        "title",
        "slug",
        "description",
        "difficulty",
        "category",
        "domain",
        "estimated_time",
    ):
        assert FROZEN_BRIEF[field].casefold() in text
    for field in ("requirements", "constraints", "hints", "tags", "companies"):
        for statement in FROZEN_BRIEF[field]:
            assert statement.casefold() in text, f"live {field} item missing: {statement}"
    assert "has_guided_walkthrough" not in raw
    assert "design reference" in text
    assert "does not claim any target has been achieved" in text


def test_schema_order_phases_and_every_brief_anchor_has_an_action():
    raw = load_guide()
    guide = GuidedWalkthrough.model_validate(raw)

    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0"
    assert guide.totalSteps == len(guide.steps)
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES for step in guide.steps)

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(guide.steps[number - 1].phase == phase.name for number in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    expected = expected_anchors()
    actual = {anchor for step in raw["steps"] for anchor in step["requirementIds"]}
    assert actual == expected
    for anchor in expected:
        assert any(
            step["type"] in ACTION_TYPES and anchor in step["requirementIds"]
            for step in raw["steps"]
        ), f"{anchor} appears only on prose or decision steps"


def test_components_use_existing_catalog_types_and_supported_properties():
    raw = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = [step["component"] for step in raw["steps"] if step["type"] == "add_component"]

    assert len(components) == 12
    assert len({component["nodeId"] for component in components}) == len(components)
    assert all(component["componentType"] != "custom-component" for component in components)

    for component in components:
        block = catalog_component_block(catalog, component["componentType"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        properties = set(component["properties"])
        assert {"componentName", "purpose"} <= properties
        assert properties <= supported, (
            f"{component['nodeId']} has unsupported properties: {sorted(properties - supported)}"
        )
        assert component["label"].strip()
        assert component["description"].strip()
        assert component["highlightReason"].strip()

    types = {component["componentType"] for component in components}
    assert "configuration-management" in types
    assert "loadbalancer" in types
    assert "experiment-tracking" in types
    assert "model-serving" in types


def test_ordered_actions_replay_to_one_connected_graph():
    raw = load_guide()
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {component["id"] for component in architecture["components"]}
    edges = architecture["connections"]
    updates = [step for step in raw["steps"] if step["type"] == "update_component"]
    expected_nodes = {
        step["component"]["nodeId"] for step in raw["steps"] if step["type"] == "add_component"
    }

    assert nodes == expected_nodes
    assert len(edges) == sum(step["type"] == "add_connection" for step in raw["steps"])
    assert len(replay["appliedStepIds"]) == len(nodes) + len(edges) + len(updates)
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in edges)
    assert all(edge["type"] in CONNECTION_TYPES for edge in edges)

    component_properties = {
        component["id"]: component["properties"]
        for component in architecture["components"]
    }
    assert len(updates) == 12
    latest_updates = {}
    for step in updates:
        update = step["componentUpdate"]
        assert update["nodeId"] in nodes
        latest_updates[update["nodeId"]] = update
    for node_id, update in latest_updates.items():
        assert component_properties[node_id]["purpose"] == update["properties"]["purpose"]

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached: set[str] = set()
    pending = deque([next(iter(nodes))])
    while pending:
        current = pending.popleft()
        if current in reached:
            continue
        reached.add(current)
        pending.extend(neighbors[current] - reached)
    assert reached == nodes


def test_access_recovery_and_retention_policies_replay_without_adding_nodes():
    replay = build_architecture(load_guide())
    architecture = replay["architecture"]
    components = {component["id"]: component["properties"] for component in architecture["components"]}
    edges = {edge["id"]: edge for edge in architecture["connections"]}

    assert len(components) == 12
    assert edges["mlops007_event_log_to_router_recovery"]["type"] == "event-stream"
    assert "tenant-scoped role authorization" in components["mlops007_control_api"]["purpose"]
    assert "re-authorizes every operation" in components["mlops007_control_ui"]["purpose"]
    assert "rebuild the local sticky-assignment cache asynchronously" in components["mlops007_router"]["purpose"]
    assert "owner-approved lateness/correction window" in components["mlops007_event_log"]["purpose"]
    assert "without expiring unresolved corrections or audit-held evidence" in components["mlops007_result_store"]["purpose"]


def test_experiment_design_covers_hints_and_keeps_targets_anchored_to_brief():
    raw = load_guide()
    text = json.dumps(raw, ensure_ascii=False).casefold()
    components = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step["type"] == "add_component"
    }
    connections = {
        step["connection"]["edgeId"]: step["connection"]
        for step in raw["steps"]
        if step["type"] == "add_connection"
    }
    triggers = {
        step["scaleTrigger"]["metric"]
        for step in raw["steps"]
        if step["type"] == "scale_trigger"
    }

    for hint in FROZEN_BRIEF["hints"]:
        assert hint.casefold() in text
    assert triggers == {
        "Traffic routing latency under 5ms",
        "Statistical significance at p < 0.05",
        "Support 50+ concurrent experiments",
    }
    assert "stable experiment subject key" in text
    assert "interaction metadata" in text
    assert "novelty effect" in text
    assert "does not provide an effect-size threshold" in text
    assert "does not specify automatic model promotion" in text

    statistical_plan = components["mlops007_decision_engine"]["properties"]["purpose"].casefold()
    assert "welch" in statistical_plan
    assert "two-proportion" in statistical_plan
    assert "holm" in statistical_plan
    assert "o'brien-fleming" in statistical_plan
    assert "family-wise alpha at 0.05" in statistical_plan

    registry_policy = components["mlops007_experiment_registry"]["properties"]["purpose"].casefold()
    assert "mutual-exclusion group" in registry_policy
    assert "reject incompatible concurrent assignments" in registry_policy
    assert "last-known-good" in components["mlops007_router"]["properties"]["purpose"].casefold()
    assert "event_id" in components["mlops007_event_log"]["properties"]["purpose"].casefold()
    assert "exposure_id" in components["mlops007_metric_pipeline"]["properties"]["purpose"].casefold()
    assert "deduplicates by event_id" in connections["mlops007_event_log_to_processor"]["description"].casefold()
    assert "corrected-data watermark" in components["mlops007_result_store"]["properties"]["purpose"].casefold()
