"""Structural contract for the cloud_gcp_011 recommendation-engine review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_gcp_011"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
FROZEN_PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def load_frozen_problem():
    problems = json.loads(FROZEN_PROBLEMS_PATH.read_text(encoding="utf-8"))
    matches = [problem for problem in problems if problem["id"] == PROBLEM_ID]
    assert len(matches) == 1, f"Expected one frozen brief for {PROBLEM_ID}"
    return matches[0]


def catalog_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'(?m)^    id:\s*"{re.escape(component_type)}"', catalog)
    assert match, f"unknown catalog component type: {component_type}"
    end = catalog.find("\n  },", match.start())
    assert end > match.start(), f"could not bound catalog definition: {component_type}"
    return catalog[match.start() : end]


def catalog_keys(block: str) -> set[str]:
    return set(re.findall(r'\bkey:\s*"([^"]+)"', block))


def test_frozen_fixture_brief_is_preserved_verbatim_and_traceable():
    raw, guide = load_guide()
    problem = load_frozen_problem()
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0-review"
    assert guide.requirementRevision is None
    assert guide.totalSteps == 50

    frozen_brief = raw["steps"][0]["content"]
    assert "no live DynamoDB lookup was performed" in frozen_brief
    assert problem["title"] in frozen_brief
    assert problem["description"] in frozen_brief
    assert all(
        item in frozen_brief
        for item in problem["requirements"] + problem["constraints"] + problem["hints"]
    )

    expected_ids = {
        *(
            f"legacy-requirement:{index}"
            for index in range(1, len(problem["requirements"]) + 1)
        ),
        *(
            f"legacy-constraint:{index}"
            for index in range(1, len(problem["constraints"]) + 1)
        ),
    }
    mapped_ids = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert mapped_ids == expected_ids

    anchors = {
        "legacy-requirement:1": "recs_09_recommendation_service",
        "legacy-requirement:2": "recs_18_publish_events",
        "legacy-requirement:3": "recs_27_model_training",
        "legacy-requirement:4": "recs_11_engine_response",
        "legacy-requirement:5": "recs_16_cold_start",
        "legacy-requirement:6": "recs_35_experiment_assignment",
        "legacy-requirement:7": "recs_41_quality_analytics",
        "legacy-requirement:8": "recs_29_incremental_update_policy",
        "legacy-constraint:1": "recs_12_latency_contract",
        "legacy-constraint:2": "recs_48_online_capacity_gate",
        "legacy-constraint:3": "recs_47_ctr_evaluation",
        "legacy-constraint:4": "recs_49_event_training_capacity",
        "legacy-constraint:5": "recs_49_event_training_capacity",
    }
    by_id = {step.id: step for step in guide.steps}
    for requirement_id, step_id in anchors.items():
        assert requirement_id in by_id[step_id].requirementIds
        assert by_id[step_id].type != "explanation"


def test_phase_ranges_step_order_and_payload_shapes():
    raw, guide = load_guide()
    assert [step.stepNumber for step in guide.steps] == list(range(1, 51))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert len({phase.name for phase in guide.phases}) == len(guide.phases)

    expected_start = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == expected_start
        assert start <= end <= guide.totalSteps
        assert all(step.phase == phase.name for step in guide.steps[start - 1 : end])
        expected_start = end + 1
    assert expected_start == guide.totalSteps + 1
    assert raw["totalSteps"] == len(raw["steps"])

    allowed = {"explanation", "add_component", "add_connection", "decision_point", "scale_trigger"}
    assert {step.type for step in guide.steps} == allowed
    for step in guide.steps:
        assert step.title and step.content and step.requirementIds
        if step.type == "add_component":
            assert step.component is not None
            assert set(step.component.position) == {"x", "y"}
            assert not step.connection and not step.decision
        elif step.type == "add_connection":
            assert step.connection is not None
            assert step.connection.label and step.connection.description
            assert not step.component and not step.decision
        elif step.type == "decision_point":
            assert step.decision is not None and step.componentUpdate is not None
            assert step.decision.question and step.decision.chosen and step.decision.chosenReason
            assert len(step.decision.alternatives) >= 2
            assert all(option.option and option.tradeoff for option in step.decision.alternatives)
        elif step.type == "scale_trigger":
            assert step.scaleTrigger is not None and step.componentUpdate is not None
            assert step.scaleTrigger.metric and step.scaleTrigger.action and step.scaleTrigger.impact


def test_only_existing_catalog_types_and_properties_are_used():
    raw, guide = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step.component.nodeId: step.component
        for step in guide.steps
        if step.type == "add_component"
    }
    assert len(additions) == 16
    custom = {
        node_id: component
        for node_id, component in additions.items()
        if component.componentType == "custom-component"
    }
    assert set(custom) == {"recs_experiment_assignment"}
    assert "catalog gap" in custom["recs_experiment_assignment"].properties["componentType"].casefold()
    assert "product experiment assignment" in custom["recs_experiment_assignment"].highlightReason.casefold()

    for step in raw["steps"]:
        component = step.get("component")
        if component:
            node_id = component["nodeId"]
            component_type = component["componentType"]
            properties = component["properties"]
            assert properties["componentName"] == component["label"]
            assert len(properties["purpose"]) >= 45
            assert component["highlightReason"]
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            node_id = update["nodeId"]
            assert node_id in additions
            component_type = additions[node_id].componentType
            properties = update["properties"]
        else:
            continue

        block = catalog_block(catalog, component_type)
        assert set(properties) <= catalog_keys(block), (
            f"{step['id']} uses unsupported properties: {set(properties) - catalog_keys(block)}"
        )


def test_replay_builds_the_connected_recommendation_architecture():
    raw, _ = load_guide()
    built = build_architecture(raw)
    architecture = built["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    edges = architecture["connections"]
    assert len(nodes) == 16
    assert len(edges) == 23
    assert len(built["appliedStepIds"]) == 48
    assert len(built["explanationOnlyStepIds"]) == 2
    assert len(built["acceptedDecisions"]) == 7
    assert built["provenance"]["problemId"] == PROBLEM_ID
    assert built["provenance"]["walkthroughVersion"] == "1.0-review"

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] and edge["description"]
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    visited = set()
    pending = deque(["recs_api_gateway"])
    while pending:
        node_id = pending.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        pending.extend(neighbors[node_id] - visited)
    assert visited == set(nodes)

    edge_pairs = {(edge["source"], edge["target"]) for edge in edges}
    assert {
        ("recs_api_gateway", "recs_cloud_run_api"),
        ("recs_cloud_run_api", "recs_behavior_events"),
        ("recs_behavior_events", "recs_dataflow"),
        ("recs_dataflow", "recs_feature_store"),
        ("recs_dataflow", "recs_bigquery"),
        ("recs_dataflow", "recs_model_update_queue"),
        ("recs_model_training", "recs_model_registry"),
        ("recs_model_registry", "recs_vertex_serving"),
        ("recs_cloud_run_api", "recs_experiment_assignment"),
        ("recs_experiment_assignment", "recs_cloud_run_api"),
        ("recs_engine", "recs_vertex_serving"),
        ("recs_vertex_serving", "recs_engine"),
    } <= edge_pairs


def test_domain_content_uses_frozen_targets_without_claiming_results():
    raw, _ = load_guide()
    lesson = json.dumps(raw, ensure_ascii=False).casefold()
    assert "frozen local problem fixture" in lesson
    assert "no live dynamodb lookup was performed" in lesson
    assert "strongly consistent getitem" not in lesson
    for evidence in (
        "recommendations ai",
        "bigquery ml",
        "dataflow",
        "cloud run",
        "vertex ai",
        "memorystore",
        "cold start",
        "incremental update",
        "feature freshness",
        "controlled experiment",
        "100ms",
        "1m+ active users",
        "20% click-through",
        "100m+ events daily",
        "cost-effective",
        "not measured results",
    ):
        assert evidence in lesson, f"missing domain-specific guidance: {evidence}"

