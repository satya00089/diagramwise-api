"""Frozen-brief, catalog, and connected replay checks for the GCP migration draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca88b"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
REQUIREMENTS = [
    "Migrate petabytes of data",
    "Minimize downtime during migration",
    "Data validation and integrity checks",
    "Incremental/delta migration support",
    "Handle different data sources (databases, files, etc.)",
    "Progress tracking and monitoring",
    "Rollback capabilities",
    "Optimize for cost and time",
]
CONSTRAINTS = [
    "Maintain data consistency",
    "Limited downtime window",
    "Network bandwidth limitations",
    "Data security during transfer",
    "Handle failures gracefully",
]
HINTS = [
    "Parallel data transfer",
    "Checkpointing for resume capability",
    "Data compression for transfer",
    "Change data capture for incremental sync",
    "Blue-green deployment strategy",
]
STEP_TYPES = {
    "explanation", "add_component", "add_connection", "decision_point", "scale_trigger",
}
CONNECTION_TYPES = {
    "http", "api-call", "database-connection", "message-queue", "data-flow",
}


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def frozen_problem():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def test_schema_and_exact_frozen_brief_anchor_coverage():
    problem = frozen_problem()
    raw, guide = load_guide()

    assert problem["title"] == "Create a System to Migrate Large Data to Google Cloud"
    assert problem["description"] == (
        "Design a data migration system to transfer petabytes of data to cloud with minimal downtime."
    )
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert problem["hints"] == HINTS
    assert problem["has_guided_walkthrough"] is False
    assert guide.problem_id == PROBLEM_ID
    assert guide.version.endswith("-review")
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 68
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES and step.content.strip() for step in guide.steps)

    expected_anchors = {
        *(f"legacy-requirement:{index}" for index in range(1, len(REQUIREMENTS) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(CONSTRAINTS) + 1)),
    }
    actual_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert actual_anchors == expected_anchors
    actionable = [
        step for step in guide.steps
        if step.type in {"add_component", "add_connection", "decision_point"}
    ]
    for anchor in expected_anchors:
        assert any(anchor in step.requirementIds for step in actionable), (
            f"{anchor} is only described, not tied to a design action or decision"
        )


def test_action_anchors_match_the_behavior_the_step_implements():
    raw, _ = load_guide()
    steps_by_id = {step["id"]: step for step in raw["steps"]}
    expected_anchors = {
        "gcm_12": {"legacy-requirement:4", "legacy-constraint:1", "legacy-constraint:5"},
        "gcm_16": {"legacy-constraint:4"},
        "gcm_21": {
            "legacy-requirement:1", "legacy-requirement:5", "legacy-requirement:6",
            "legacy-requirement:8", "legacy-constraint:1",
        },
        "gcm_24": {"legacy-requirement:6", "legacy-constraint:1"},
        "gcm_25": {"legacy-requirement:6", "legacy-constraint:5"},
        "gcm_29": {"legacy-requirement:6", "legacy-constraint:5"},
        "gcm_32": {"legacy-requirement:3", "legacy-requirement:5", "legacy-constraint:1"},
        "gcm_34": {
            "legacy-requirement:1", "legacy-requirement:3", "legacy-requirement:5",
            "legacy-constraint:1", "legacy-constraint:5",
        },
        "gcm_37": {"legacy-requirement:4", "legacy-constraint:1", "legacy-constraint:5"},
        "gcm_39": {"legacy-requirement:4", "legacy-constraint:1", "legacy-constraint:5"},
        "gcm_40": {
            "legacy-requirement:4", "legacy-requirement:6",
            "legacy-constraint:1", "legacy-constraint:5",
        },
        "gcm_46": {
            "legacy-requirement:3", "legacy-requirement:6",
            "legacy-constraint:1", "legacy-constraint:4", "legacy-constraint:5",
        },
        "gcm_51": {"legacy-requirement:2", "legacy-constraint:1", "legacy-constraint:2"},
        "gcm_52": {
            "legacy-requirement:2", "legacy-requirement:3",
            "legacy-constraint:1", "legacy-constraint:2", "legacy-constraint:5",
        },
        "gcm_53": {
            "legacy-requirement:2", "legacy-requirement:3", "legacy-requirement:4",
            "legacy-constraint:1", "legacy-constraint:2", "legacy-constraint:5",
        },
        "gcm_56": {"legacy-requirement:6"},
        "gcm_57": {"legacy-requirement:6", "legacy-constraint:5"},
        "gcm_61": {"legacy-requirement:3", "legacy-requirement:6", "legacy-constraint:5"},
        "gcm_62": {
            "legacy-requirement:2", "legacy-requirement:7",
            "legacy-constraint:1", "legacy-constraint:2", "legacy-constraint:5",
        },
    }

    for step_id, anchors in expected_anchors.items():
        assert set(steps_by_id[step_id]["requirementIds"]) == anchors


def test_benchmarks_are_proposals_not_numeric_brief_targets():
    raw, _ = load_guide()
    steps_by_id = {step["id"]: step for step in raw["steps"]}
    assert "proposed estimation and benchmarking method" in steps_by_id["gcm_13"]["content"]
    assert "no exact data volume, bandwidth rate" in steps_by_id["gcm_13"]["content"]
    assert "proposed benchmark work" in steps_by_id["gcm_64"]["content"]

    narrative = " ".join(
        [step["title"] + " " + step["content"] for step in raw["steps"]]
        + [
            " ".join(
                [step["component"]["description"], step["component"]["properties"]["purpose"]]
            )
            for step in raw["steps"] if step.get("component")
        ]
        + [
            " ".join(
                [step["decision"]["question"], step["decision"]["chosen"]]
                + [alternative["option"] + " " + alternative["tradeoff"]
                   for alternative in step["decision"]["alternatives"]]
            )
            for step in raw["steps"] if step.get("decision")
        ]
        + [
            " ".join(
                [step["scaleTrigger"]["metric"], step["scaleTrigger"]["action"]]
            )
            for step in raw["steps"] if step.get("scaleTrigger")
        ]
    )
    numeric_target = re.compile(
        r"(?i)(?:[<>]=?\s*\d+(?:\.\d+)?\s*(?:%|ms|milliseconds?|seconds?|minutes?|hours?|"
        r"days?|tb|pb|gb|mb|gbps|mbps|workers?|concurrent|million|billion)"
        r"|\b\d+(?:\.\d+)?\s*(?:%|percent|ms|milliseconds?|seconds?|minutes?|hours?|days?|"
        r"tb|pb|gb|mb|gbps|mbps|workers?|concurrent|million|billion)\b|\bp(?:95|99)\b)"
    )
    assert numeric_target.search(narrative) is None


def test_phases_and_ordered_actions_are_well_formed():
    _, guide = load_guide()
    next_step = 1
    nodes = {}
    edges = set()

    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    for step in guide.steps:
        if step.type == "add_component":
            assert step.component is not None
            assert step.component.nodeId not in nodes
            assert step.component.position.keys() >= {"x", "y"}
            nodes[step.component.nodeId] = step.component
        elif step.type == "add_connection":
            assert step.connection is not None
            connection = step.connection
            assert connection.edgeId not in edges
            assert connection.connectionType in CONNECTION_TYPES
            assert {connection.sourceNodeId, connection.targetNodeId} <= nodes.keys()
            edges.add(connection.edgeId)
        elif step.type == "decision_point":
            assert step.decision is not None and step.decision.alternatives
        elif step.type == "scale_trigger":
            assert step.scaleTrigger is not None

    assert len(nodes) == 21
    assert len(edges) == 33


def test_catalog_ids_properties_and_select_values_are_supported():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = [step["component"] for step in raw["steps"] if step.get("component")]

    assert components
    assert all(component["componentType"] != "custom-component" for component in components)
    for step in raw["steps"]:
        component = step.get("component")
        if not component:
            continue
        assert component["properties"]["componentName"] == component["label"]
        assert len(component["properties"]["purpose"]) >= 70
        assert component["highlightReason"]
        component_type = component["componentType"]
        match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
        assert match is not None, f"{step['id']}: unknown catalog ID {component_type}"
        block_end = catalog.find("\n  },", match.start())
        assert block_end != -1
        component_block = catalog[match.start():block_end]
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', component_block))
        properties = component["properties"]
        assert set(properties) <= supported, (
            f"{step['id']}: unsupported properties {sorted(set(properties) - supported)}"
        )

        for key, value in properties.items():
            field_start = component_block.index(f'key: "{key}"')
            field_end = component_block.find("},", field_start)
            field = component_block[field_start:field_end]
            field_type = re.search(r'\btype:\s*"([^"]+)"', field)
            assert field_type is not None, f"{step['id']}/{key}: missing catalog field type"
            kind = field_type.group(1)
            if kind in {"text", "textarea"}:
                assert isinstance(value, str)
            elif kind == "boolean":
                assert type(value) is bool
            elif kind == "number":
                assert type(value) in {int, float}
            elif kind == "select":
                options = re.search(r'\boptions:\s*\[([^\]]+)\]', field)
                assert options is not None
                assert value in re.findall(r'"([^"]+)"', options.group(1)), (
                    f"{step['id']}/{key}: {value!r} is not a supported option"
                )


def test_replay_is_one_connected_migration_architecture():
    raw, _ = load_guide()
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {node["id"]: node for node in architecture["components"]}
    edges = architecture["connections"]

    assert len(nodes) == 21
    assert len(edges) == 33
    assert nodes["gcm_staging"]["properties"]["provider"] == "GCS"
    assert nodes["gcm_target_files"]["properties"]["provider"] == "GCS"
    assert nodes["gcm_source_db"]["properties"]["originalComponentId"] == "database"
    assert nodes["gcm_source_files"]["properties"]["originalComponentId"] == "file-storage"

    edge_pairs = {(edge["source"], edge["target"]) for edge in edges}
    for expected in (
        ("gcm_console", "gcm_gateway"),
        ("gcm_gateway", "gcm_coordinator"),
        ("gcm_coordinator", "gcm_metadata"),
        ("gcm_source_db", "gcm_firewall"),
        ("gcm_source_files", "gcm_firewall"),
        ("gcm_firewall", "gcm_vpn"),
        ("gcm_vpn", "gcm_workers"),
        ("gcm_queue", "gcm_workers"),
        ("gcm_workers", "gcm_target_db"),
        ("gcm_vpn", "gcm_cdc"),
        ("gcm_cdc", "gcm_target_db"),
        ("gcm_target_db", "gcm_validator"),
        ("gcm_validator", "gcm_metadata"),
        ("gcm_workload", "gcm_router"),
        ("gcm_router", "gcm_source_db"),
        ("gcm_router", "gcm_target_db"),
    ):
        assert expected in edge_pairs

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["gcm_console"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == set(nodes)


def test_domain_guidance_covers_integrity_downtime_recovery_and_cost_tradeoffs():
    raw, _ = load_guide()
    authored_text = " ".join(
        [step["content"] for step in raw["steps"]]
        + [step["component"]["properties"]["purpose"] for step in raw["steps"] if step.get("component")]
        + [
            " ".join(
                [step["decision"]["chosen"], step["decision"]["chosenReason"]]
                + [alternative["tradeoff"] for alternative in step["decision"]["alternatives"]]
            )
            for step in raw["steps"] if step.get("decision")
        ]
    ).casefold()

    for signal in (
        "petabytes", "snapshot", "watermark", "checksum", "manifest", "checkpoint",
        "idempotent", "bandwidth", "source pressure", "write fence", "single-writer",
        "reverse change capture", "quarantine", "least-privilege", "compression",
        "cost", "acl", "log retention",
    ):
        assert signal in authored_text, f"missing migration-specific guidance: {signal}"
    assert "custom-component" not in {
        step["component"]["componentType"]
        for step in raw["steps"] if step.get("component")
    }

