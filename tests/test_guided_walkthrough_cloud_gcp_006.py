"""Contract, catalog, and graph-replay checks for cloud_gcp_006."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_gcp_006"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

REQUIREMENTS = [
    "Stream data into BigQuery",
    "Run real-time SQL queries",
    "Create interactive dashboards",
    "Handle high-volume ingestion",
    "Optimize query performance",
    "Schedule data refreshes",
    "Share dashboards with stakeholders",
    "Monitor query costs",
]
CONSTRAINTS = [
    "Query latency under 5 seconds",
    "Ingest 100k+ events per second",
    "Support concurrent users (100+)",
    "Cost-effective query execution",
    "Dashboard refresh under 1 minute",
]
HINTS = [
    "BigQuery for analytics warehouse",
    "Pub/Sub for event streaming",
    "Data Studio for visualization",
    "Cloud Functions for data processing",
    "BigQuery streaming inserts",
    "Partitioning and clustering for performance",
]
FROZEN_BRIEF = (
    "Title: Build a Real-time Analytics Dashboard\n"
    "Description: Design a real-time analytics solution that ingests streaming data, runs SQL queries on large datasets, "
    "creates interactive dashboards, and refreshes visualizations automatically.\n"
    "Requirements:\n"
    "1. Stream data into BigQuery\n"
    "2. Run real-time SQL queries\n"
    "3. Create interactive dashboards\n"
    "4. Handle high-volume ingestion\n"
    "5. Optimize query performance\n"
    "6. Schedule data refreshes\n"
    "7. Share dashboards with stakeholders\n"
    "8. Monitor query costs\n"
    "Constraints:\n"
    "1. Query latency under 5 seconds\n"
    "2. Ingest 100k+ events per second\n"
    "3. Support concurrent users (100+)\n"
    "4. Cost-effective query execution\n"
    "5. Dashboard refresh under 1 minute\n"
    "Hints:\n"
    "1. BigQuery for analytics warehouse\n"
    "2. Pub/Sub for event streaming\n"
    "3. Data Studio for visualization\n"
    "4. Cloud Functions for data processing\n"
    "5. BigQuery streaming inserts\n"
    "6. Partitioning and clustering for performance"
)
ALL_BRIEF_IDS = {
    *(f"legacy-requirement:{i}" for i in range(1, len(REQUIREMENTS) + 1)),
    *(f"legacy-constraint:{i}" for i in range(1, len(CONSTRAINTS) + 1)),
}
ACTION_ANCHORS = {
    "legacy-requirement:1": "gcp006_ingest_to_bigquery",
    "legacy-requirement:2": "gcp006_dashboard_query",
    "legacy-requirement:3": "gcp006_dashboard",
    "legacy-requirement:4": "gcp006_buffer_policy",
    "legacy-requirement:5": "gcp006_storage_query_policy",
    "legacy-requirement:6": "gcp006_scheduler_to_refresh",
    "legacy-requirement:7": "gcp006_identity_dashboard",
    "legacy-requirement:8": "gcp006_monitoring_policy",
    "legacy-constraint:1": "gcp006_storage_query_policy",
    "legacy-constraint:2": "gcp006_pubsub_to_ingest",
    "legacy-constraint:3": "gcp006_dashboard_freshness",
    "legacy-constraint:4": "gcp006_storage_query_policy",
    "legacy-constraint:5": "gcp006_dashboard_freshness",
}


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"{step_id}: unknown catalog component {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), f"{step_id}: incomplete catalog entry for {component_type}"
    return catalog[match.start():block_end]


def catalog_options(block: str, key: str) -> set[str] | None:
    marker = re.search(rf'\bkey:\s*"{re.escape(key)}"', block)
    if not marker:
        return None
    remainder = block[marker.end():]
    next_property = re.search(r'\bkey:\s*"', remainder)
    section = remainder[:next_property.start()] if next_property else remainder
    options = re.search(r"options:\s*\[([\s\S]*?)\]", section)
    return set(re.findall(r'"([^"]+)"', options.group(1))) if options else None


def test_schema_version_step_order_phases_and_public_copy():
    raw, guide = load_guide()
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0"
    assert guide.totalSteps == len(guide.steps) == 26
    assert [step.stepNumber for step in guide.steps] == list(range(1, 27))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert "has_guided_walkthrough" not in raw

    expected_start = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == expected_start
        assert start <= end <= guide.totalSteps
        assert all(step.phase == phase.name for step in guide.steps[start - 1:end])
        expected_start = end + 1
    assert expected_start == guide.totalSteps + 1

    for step in guide.steps:
        assert step.title and step.content and step.requirementIds
        assert not re.search(r"\b(unpublished|local draft|review draft)\b", step.title + " " + step.content, re.I)
        if step.type == "add_component":
            assert step.component and step.component.highlightReason
            assert set(step.component.position) == {"x", "y"}
        elif step.type == "add_connection":
            assert step.connection and step.connection.label and step.connection.description
        elif step.type == "update_component":
            assert step.componentUpdate and step.componentUpdate.properties


def test_exact_live_brief_and_every_requirement_has_an_action_anchor():
    raw, guide = load_guide()
    assert raw["steps"][0]["content"].startswith(FROZEN_BRIEF + "\n\n")

    expected_ids = set(ALL_BRIEF_IDS)
    mapped_ids = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert expected_ids <= mapped_ids

    steps = {step.id: step for step in guide.steps}
    built = build_architecture(raw)
    applied = set(built["appliedStepIds"])
    assert set(ACTION_ANCHORS) == expected_ids
    for requirement_id, step_id in ACTION_ANCHORS.items():
        assert requirement_id in steps[step_id].requirementIds
        assert step_id in applied, f"{requirement_id} is anchored only to a non-replayable explanation"


def test_catalog_types_properties_and_custom_scheduler_gap():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"] if step.get("component")
    }
    assert len(components) == 8
    assert {
        node_id for node_id, component in components.items()
        if component["componentType"] == "custom-component"
    } == {"gcp006_scheduler"}

    for step in raw["steps"]:
        component = step.get("component")
        update = step.get("componentUpdate")
        if component:
            component_type = component["componentType"]
            properties = component["properties"]
            node_id = component["nodeId"]
            assert properties["componentName"] == component["label"]
            assert len(properties["purpose"]) >= 45
        elif update:
            node_id = update["nodeId"]
            component_type = components[node_id]["componentType"]
            properties = update["properties"]
        else:
            continue

        block = catalog_block(catalog, component_type, step["id"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert set(properties) <= supported, f"{step['id']}: unsupported properties {set(properties) - supported}"
        for key, value in properties.items():
            options = catalog_options(block, key)
            if options is not None:
                assert value in options, f"{step['id']}: {key}={value!r} is not a catalog option"

    assert components["gcp006_bigquery"]["properties"]["platform"] == "BigQuery"
    assert components["gcp006_pubsub"]["componentType"] == "pubsub"
    assert components["gcp006_ingest_function"]["componentType"] == "serverless-function"
    assert components["gcp006_scheduler"]["properties"]["technology"] == "Google Cloud Scheduler"


def test_replay_produces_connected_graph_with_all_actions_applied():
    raw, _ = load_guide()
    built = build_architecture(raw)
    architecture = built["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    edges = architecture["connections"]

    assert len(nodes) == 8
    assert len(edges) == 10
    assert len(built["appliedStepIds"]) == 24
    assert len(built["explanationOnlyStepIds"]) == 2
    assert built["provenance"]["problemId"] == PROBLEM_ID
    assert built["provenance"]["walkthroughVersion"] == "1.0"

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] and edge["description"]
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])

    visited = set()
    pending = deque(["gcp006_pubsub"])
    while pending:
        node_id = pending.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        pending.extend(neighbors[node_id] - visited)
    assert visited == set(nodes)
