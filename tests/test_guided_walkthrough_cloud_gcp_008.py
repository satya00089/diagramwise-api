"""Focused contract for the cloud_gcp_008 unpublished review draft."""

import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_gcp_008"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
FROZEN_PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def load_frozen_problem():
    problems = json.loads(FROZEN_PROBLEMS_PATH.read_text(encoding="utf-8"))
    matches = [problem for problem in problems if problem["id"] == PROBLEM_ID]
    assert len(matches) == 1, f"expected one frozen brief for {PROBLEM_ID}"
    return matches[0]


def catalog_block(catalog: str, component_type: str) -> str:
    match = re.search(
        rf'(?m)^    id:\s*"{re.escape(component_type)}"', catalog
    )
    assert match, f"unknown catalog component type: {component_type}"
    end = catalog.find("\n  },", match.start())
    assert end > match.start(), f"could not bound catalog definition: {component_type}"
    return catalog[match.start() : end]


def catalog_keys(block: str) -> set[str]:
    return set(re.findall(r'\bkey:\s*"([^"]+)"', block))


def catalog_options(block: str, key: str) -> set[str]:
    marker = re.search(rf'\bkey:\s*"{re.escape(key)}"', block)
    assert marker, f"catalog property missing: {key}"
    prop_end = re.search(r"\n      },", block[marker.end() :])
    section = (
        block[marker.end() : marker.end() + prop_end.start()]
        if prop_end
        else block[marker.end() :]
    )
    options = re.search(r"options:\s*\[([\s\S]*?)\]", section)
    assert options, f"{key} is not a catalog select property"
    return set(re.findall(r'"([^"]+)"', options.group(1)))


def test_schema_order_phase_ranges_and_action_references():
    raw, guide = load_guide()

    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0-review"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 48
    assert [step.stepNumber for step in guide.steps] == list(range(1, 49))
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

    node_ids = set()
    edge_ids = set()
    allowed_types = {
        "explanation",
        "add_component",
        "add_connection",
        "decision_point",
        "scale_trigger",
    }
    assert {step.type for step in guide.steps} == allowed_types

    for step in guide.steps:
        assert step.title and step.content and step.requirementIds
        if step.type == "add_component":
            assert step.component is not None
            assert step.component.position.keys() == {"x", "y"}
            assert step.component.nodeId not in node_ids
            node_ids.add(step.component.nodeId)
        elif step.type == "add_connection":
            assert step.connection is not None
            assert step.connection.sourceNodeId in node_ids
            assert step.connection.targetNodeId in node_ids
            assert step.connection.edgeId not in edge_ids
            edge_ids.add(step.connection.edgeId)
        elif step.type in {"decision_point", "scale_trigger"}:
            assert step.componentUpdate is not None
            assert step.componentUpdate.nodeId in node_ids

    assert len(node_ids) == 9
    assert len(edge_ids) == 12
    assert raw["totalSteps"] == len(raw["steps"])


def test_live_brief_is_preserved_and_each_anchor_has_a_concrete_action():
    _, guide = load_guide()
    frozen_problem = load_frozen_problem()
    first_step = guide.steps[0]
    frozen_brief = "\n".join(
        (
            f"Title: {frozen_problem['title']}",
            f"Description: {frozen_problem['description']}",
            f"Requirements: {'; '.join(frozen_problem['requirements'])}.",
            f"Constraints: {'; '.join(frozen_problem['constraints'])}.",
            f"Hints: {'; '.join(frozen_problem['hints'])}.",
        )
    )
    assert first_step.content.startswith(frozen_brief)

    expected_anchors = {
        *(
            f"legacy-requirement:{index}"
            for index in range(1, len(frozen_problem["requirements"]) + 1)
        ),
        *(
            f"legacy-constraint:{index}"
            for index in range(1, len(frozen_problem["constraints"]) + 1)
        ),
    }
    mapped_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert mapped_anchors == expected_anchors

    concrete_actions = {
        "legacy-requirement:1": "gcp_09_eventarc_ingest",
        "legacy-requirement:2": "gcp_11_pubsub",
        "legacy-requirement:3": "gcp_15_firestore",
        "legacy-requirement:4": "gcp_07_eventarc",
        "legacy-requirement:5": "gcp_30_retry_policy",
        "legacy-requirement:6": "gcp_21_monitoring",
        "legacy-requirement:7": "gcp_17_dead_letter_topic",
        "legacy-requirement:8": "gcp_36_scale_on_backlog",
        "legacy-constraint:1": "gcp_34_latency_instrumentation",
        "legacy-constraint:2": "gcp_36_scale_on_backlog",
        "legacy-constraint:3": "gcp_28_idempotent_consumer",
        "legacy-constraint:4": "gcp_38_variable_cost",
        "legacy-constraint:5": "gcp_36_scale_on_backlog",
    }
    assert set(concrete_actions) == expected_anchors
    by_id = {step.id: step for step in guide.steps}
    for anchor, step_id in concrete_actions.items():
        step = by_id[step_id]
        assert anchor in step.requirementIds
        assert step.type in {"add_component", "add_connection", "update_component"} or (
            step.componentUpdate is not None
        )


def test_components_use_catalog_types_and_only_the_scheduler_is_custom():
    raw, guide = load_guide()
    additions = {
        step.component.nodeId: step.component
        for step in guide.steps
        if step.type == "add_component"
    }
    assert len(additions) == 9
    assert {
        node_id
        for node_id, component in additions.items()
        if component.componentType == "custom-component"
    } == {"gcp_cloud_scheduler"}
    assert "catalog gap" in additions["gcp_cloud_scheduler"].properties[
        "componentType"
    ].casefold()
    assert "optional" in additions["gcp_cloud_scheduler"].properties[
        "purpose"
    ].casefold()
    assert additions["gcp_monitoring"].properties["stack"] == "Google Cloud Monitoring"

    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    for step in raw["steps"]:
        component = step.get("component")
        if component:
            node_id = component["nodeId"]
            component_type = component["componentType"]
            properties = component["properties"]
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            node_id = update["nodeId"]
            component_type = additions[node_id].componentType
            properties = update["properties"]
        else:
            continue

        block = catalog_block(catalog, component_type)
        assert set(properties) <= catalog_keys(block), (
            f"{step['id']} uses unsupported catalog properties: "
            f"{set(properties) - catalog_keys(block)}"
        )
        if component:
            assert properties["componentName"] == component["label"]
            assert properties["purpose"]
            assert component["highlightReason"]

    database = additions["gcp_firestore"]
    assert database.properties["type"] in catalog_options(
        catalog_block(catalog, database.componentType), "type"
    )
    assert database.properties["type"] == "NoSQL"


def test_replayed_architecture_has_the_required_event_and_recovery_paths():
    raw, _ = load_guide()
    built = build_architecture(raw)
    architecture = built["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    edges = {
        (connection["source"], connection["target"])
        for connection in architecture["connections"]
    }

    assert len(nodes) == 9
    assert len(edges) == 12
    assert ("gcp_event_sources", "gcp_eventarc") in edges
    assert ("gcp_eventarc", "gcp_event_ingest") in edges
    assert ("gcp_event_ingest", "gcp_event_topic") in edges
    assert ("gcp_event_topic", "gcp_event_worker") in edges
    assert ("gcp_event_worker", "gcp_firestore") in edges
    assert ("gcp_event_topic", "gcp_dead_letter_topic") in edges
    assert ("gcp_cloud_scheduler", "gcp_event_topic") in edges
    assert built["provenance"]["problemId"] == PROBLEM_ID
    assert len(built["acceptedDecisions"]) == 4
