"""Local structural contract for the Climate Data Analysis Platform review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_gcp_012"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

REQUIREMENTS = [
    "Process satellite imagery",
    "Analyze geospatial datasets",
    "Run climate models",
    "Detect environmental changes",
    "Perform time-series analysis",
    "Visualize results on maps",
    "Handle petabyte-scale data",
    "Collaborate with researchers",
]
CONSTRAINTS = [
    "Process decades of satellite data",
    "Support complex scientific algorithms",
    "Query latency under 30 seconds",
    "High-precision calculations",
    "Cost-effective for research budgets",
]


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def test_schema_step_order_phase_ranges_and_action_payloads():
    raw, guide = load_guide()
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0-review"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 52
    assert [step.stepNumber for step in guide.steps] == list(range(1, 53))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert len({step.name for step in guide.phases}) == len(guide.phases)

    expected_start = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == expected_start
        assert start <= end <= guide.totalSteps
        assert all(step.phase == phase.name for step in guide.steps[start - 1 : end])
        expected_start = end + 1
    assert expected_start == guide.totalSteps + 1

    allowed = {"explanation", "add_component", "add_connection", "decision_point", "scale_trigger"}
    assert {step.type for step in guide.steps} == allowed
    for step in guide.steps:
        assert step.title and step.content and step.requirementIds
        if step.type == "add_component":
            assert step.component is not None
            assert step.component.position.keys() == {"x", "y"}
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
        else:
            assert step.component is None and step.connection is None
    assert raw["totalSteps"] == len(raw["steps"])


def test_exact_frozen_snapshot_and_requirement_traceability():
    raw, guide = load_guide()
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    assert problem["title"] == "Build a Climate Data Analysis Platform"
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS

    expected_ids = {
        *(f"legacy-requirement:{index}" for index in range(1, 9)),
        *(f"legacy-constraint:{index}" for index in range(1, 6)),
    }
    mapped_ids = {key for step in guide.steps for key in step.requirementIds}
    assert mapped_ids == expected_ids

    # Each frozen brief item has a specific implementation or decision action.
    anchors = {
        "legacy-requirement:1": "climate_09",
        "legacy-requirement:2": "climate_14",
        "legacy-requirement:3": "climate_20",
        "legacy-requirement:4": "climate_25",
        "legacy-requirement:5": "climate_16",
        "legacy-requirement:6": "climate_37",
        "legacy-requirement:7": "climate_03",
        "legacy-requirement:8": "climate_40",
        "legacy-constraint:1": "climate_48",
        "legacy-constraint:2": "climate_20",
        "legacy-constraint:3": "climate_47",
        "legacy-constraint:4": "climate_24",
        "legacy-constraint:5": "climate_48",
    }
    steps = {step.id: step for step in guide.steps}
    for requirement_id, step_id in anchors.items():
        assert requirement_id in steps[step_id].requirementIds
        assert steps[step_id].type != "explanation"

    # Keep the strongest traceability claims tied to the action that actually
    # carries them, rather than tagging adjacent metadata/transport steps.
    assert set(steps["climate_03"].requirementIds) == {
        "legacy-requirement:1",
        "legacy-requirement:7",
        "legacy-constraint:1",
    }
    assert "legacy-constraint:4" not in steps["climate_05"].requirementIds
    assert "legacy-constraint:4" not in steps["climate_06"].requirementIds
    assert "legacy-constraint:3" not in steps["climate_15"].requirementIds
    assert "legacy-constraint:3" not in steps["climate_17"].requirementIds
    assert "legacy-constraint:5" not in steps["climate_29"].requirementIds
    assert "legacy-constraint:5" not in steps["climate_40"].requirementIds
    assert "legacy-constraint:5" in steps["climate_42"].requirementIds
    assert "legacy-constraint:4" not in steps["climate_45"].requirementIds

    lesson = json.dumps(raw, ensure_ascii=False).casefold()
    for evidence in (
        "source-scene", "earth engine", "bigquery", "dataflow", "climate model",
        "change detection", "time-series", "map tiles", "petabyte", "decades",
        "under 30 seconds", "float64", "research budget", "project-scoped",
        "checksum", "checkpoint", "quarantine", "units", "lineage",
    ):
        assert evidence in lesson


def test_catalog_ids_properties_and_meaningful_editable_context():
    raw, guide = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step.component.nodeId: step.component
        for step in guide.steps
        if step.type == "add_component"
    }
    assert len(additions) == 18
    assert {node_id for node_id, component in additions.items() if component.componentType == "custom-component"} == {
        "climate_sources"
    }
    assert additions["climate_sources"].properties["componentType"] == "External scientific data source"
    assert additions["climate_warehouse"].componentType == "data-warehouse"
    assert additions["climate_warehouse"].properties["platform"] == "BigQuery"
    assert additions["climate_geospatial"].componentType == "analytics"
    assert additions["climate_models"].componentType == "processing-worker"
    for node_id in ("climate_raw", "climate_curated", "climate_map_tiles"):
        assert additions[node_id].properties["provider"] == "GCS"

    for step in raw["steps"]:
        if step.get("component"):
            component = step["component"]
            component_type = component["componentType"]
            properties = component["properties"]
            assert properties["componentName"] == component["label"]
            assert len(properties["purpose"]) >= 45
            assert component["highlightReason"]
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            assert update["nodeId"] in additions
            component_type = additions[update["nodeId"]].componentType
            properties = update["properties"]
            assert properties
        else:
            continue

        match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
        assert match, f"{step['id']} uses unknown catalog ID {component_type}"
        block_end = catalog.find("\n  },", match.start())
        assert block_end > match.start()
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', catalog[match.start() : block_end]))
        assert set(properties) <= supported, f"{step['id']} has unsupported properties {set(properties) - supported}"

    # Capacity is intentionally left for workload testing; the brief provides
    # no worker-concurrency or numeric service-level target.
    for step in raw["steps"]:
        for action_key in ("component", "componentUpdate"):
            action = step.get(action_key)
            if action:
                assert "concurrency" not in action["properties"]

    authored_copy = " ".join(
        [step.content for step in guide.steps]
        + [
            str(value)
            for step in guide.steps
            for action in (step.component, step.componentUpdate)
            if action
            for value in action.properties.values()
        ]
    )
    duration_claims = set(
        re.findall(r"\b\d+(?:\.\d+)?\s*(?:ms|seconds?|secs?|minutes?|hours?|days?|%)\b", authored_copy, re.I)
    )
    assert duration_claims <= {"30 seconds"}
    assert "petabyte-scale" in authored_copy
    assert "decades-long" in authored_copy


def test_replay_builds_connected_graph_and_applies_scientific_decisions():
    raw, _ = load_guide()
    built = build_architecture(raw)
    architecture = built["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    edges = architecture["connections"]
    assert len(nodes) == 18
    assert len(edges) == 26
    assert len(built["appliedStepIds"]) == 50
    assert len(built["explanationOnlyStepIds"]) == 2
    assert len(built["acceptedDecisions"]) == 5
    assert built["provenance"]["problemId"] == PROBLEM_ID
    assert built["provenance"]["walkthroughVersion"] == "1.0-review"

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] and edge["description"]
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    visited = set()
    pending = deque(["climate_sources"])
    while pending:
        node_id = pending.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        pending.extend(neighbors[node_id] - visited)
    assert visited == set(nodes)

    assert nodes["climate_raw"]["properties"]["versioning"] is True
    assert nodes["climate_raw"]["properties"]["checksumValidation"] is True
    assert nodes["climate_warehouse"]["properties"]["partitioning"] is True
    assert nodes["climate_preprocess"]["properties"]["autoscale"] is True
    assert "float64" in nodes["climate_models"]["properties"]["purpose"]
    assert "quarantine" in nodes["climate_manifest"]["properties"]["purpose"]
    assert "role-checked" in nodes["climate_workspace"]["properties"]["purpose"]

    edge_pairs = {(edge["source"], edge["target"]) for edge in edges}
    assert {
        ("climate_sources", "climate_raw"),
        ("climate_events", "climate_preprocess"),
        ("climate_curated", "climate_geospatial"),
        ("climate_curated", "climate_models"),
        ("climate_models", "climate_curated"),
        ("climate_change", "climate_warehouse"),
        ("climate_api", "climate_warehouse"),
        ("climate_api", "climate_model_queue"),
        ("climate_geospatial", "climate_map_tiles"),
        ("climate_map_tiles", "climate_dashboard"),
        ("climate_api", "climate_workspace"),
        ("climate_models", "climate_monitoring"),
        ("climate_raw", "climate_archive"),
    } <= edge_pairs
