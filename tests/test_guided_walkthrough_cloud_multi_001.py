"""Focused structural and domain review gates for cloud_multi_001."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_multi_001"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

DESCRIPTION = (
    "Design a data synchronization system that replicates data across multiple "
    "cloud providers, detects changes, resolves conflicts, and ensures data consistency."
)
REQUIREMENTS = [
    "Sync data across three cloud providers",
    "Detect and resolve conflicts",
    "Maintain data consistency",
    "Handle large file transfers",
    "Implement incremental sync",
    "Monitor sync status",
    "Handle network failures",
    "Optimize transfer costs",
]
CONSTRAINTS = [
    "Sync latency under 5 minutes",
    "Support 100TB+ data transfers",
    "Ensure data integrity",
    "Minimize egress costs",
    "Handle concurrent updates",
]
HINTS = [
    "Use native sync tools (DataSync, AzCopy, gsutil)",
    "Implement change detection (checksums, timestamps)",
    "Use event notifications for triggers",
    "Consider third-party tools (Rclone)",
    "Implement retry and error handling",
    "Use direct cloud-to-cloud transfers",
]
STEP_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "decision_point",
    "scale_trigger",
}
ACTION_TYPES = {"add_component", "add_connection", "decision_point", "scale_trigger"}
CONNECTION_TYPES = {
    "api-call",
    "data-flow",
    "database-connection",
    "event-stream",
    "http",
    "message-queue",
}
ANCHORS = {
    *(f"legacy-requirement:{number}" for number in range(1, len(REQUIREMENTS) + 1)),
    *(f"legacy-constraint:{number}" for number in range(1, len(CONSTRAINTS) + 1)),
}
ACTION_ANCHOR_EVIDENCE = {
    "legacy-requirement:1": {"mcs_13_s3", "mcs_14_azure", "mcs_15_gcs"},
    "legacy-requirement:2": {"mcs_29_conflicts", "mcs_30_coordinator_conflict"},
    "legacy-requirement:3": {"mcs_11_consistency_decision", "mcs_worker_metadata"},
    "legacy-requirement:4": {"mcs_35_transfer_workers", "mcs_worker_s3"},
    "legacy-requirement:5": {"mcs_16_events", "mcs_18_scanner", "mcs_27_scanner_coordinator"},
    "legacy-requirement:6": {"mcs_53_monitoring", "mcs_monitor_coordinator"},
    "legacy-requirement:7": {"mcs_queue_workers", "mcs_queue_dlq", "mcs_failure_drill"},
    "legacy-requirement:8": {"mcs_54_cost_analytics", "mcs_worker_cost"},
    "legacy-constraint:1": {"mcs_50_large_transfer", "mcs_53_monitoring"},
    "legacy-constraint:2": {"mcs_13_s3", "mcs_35_transfer_workers"},
    "legacy-constraint:3": {"mcs_13_s3", "mcs_worker_metadata"},
    "legacy-constraint:4": {"mcs_54_cost_analytics", "mcs_transfer_tradeoff"},
    "legacy-constraint:5": {"mcs_29_conflicts", "mcs_32_conflict_decision"},
}
EXPECTED_PHASES = [
    ("1. Define ownership, consistency, and the control plane", 1, 12),
    ("2. Detect changes and reconcile conflicts", 13, 32),
    ("3. Transfer safely across providers", 33, 52),
    ("4. Prove outcomes, cost, and recovery", 53, 64),
]


def _load() -> tuple[dict, dict, GuidedWalkthrough]:
    guide = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    return guide, problem, GuidedWalkthrough.model_validate(guide)


def _catalog_block(catalog: str, component_type: str) -> str:
    match = re.search(
        rf'(?ms)^    id:\s*"{re.escape(component_type)}".*?^  \}},', catalog
    )
    assert match, f"Unknown component catalog ID: {component_type}"
    return match.group(0)


def _property_definitions(block: str) -> dict[str, tuple[str, set[str]]]:
    definitions = {}
    for section in re.split(r"(?=\n\s*\{\s*key:)", block):
        key = re.search(r'\bkey:\s*"([^"]+)"', section)
        if not key:
            continue
        field_type = re.search(r'\btype:\s*"([^"]+)"', section)
        assert field_type, f"Missing type for catalog property {key[1]}"
        options = re.search(r"\boptions:\s*\[([^\]]*)\]", section, re.DOTALL)
        option_values = (
            set(re.findall(r'"([^"]+)"', options[1])) if options else set()
        )
        definitions[key[1]] = (field_type[1], option_values)
    return definitions


def _assert_supported_properties(component_type: str, properties: dict, catalog: str):
    definitions = _property_definitions(_catalog_block(catalog, component_type))
    assert set(properties) <= definitions.keys(), (
        f"Unsupported {component_type} properties: "
        f"{sorted(set(properties) - definitions.keys())}"
    )
    for key, value in properties.items():
        field_type, options = definitions[key]
        if field_type == "boolean":
            assert type(value) is bool, f"{component_type}.{key} must be boolean"
        elif field_type == "number":
            assert type(value) in (int, float), f"{component_type}.{key} must be numeric"
        elif field_type == "select":
            assert value in options, (
                f"Unsupported {component_type}.{key} option: {value!r}"
            )


def test_schema_phases_and_exact_live_brief_anchor_coverage():
    raw, problem, guide = _load()
    assert problem["title"] == "Design a Multi-Cloud Data Sync Solution"
    assert problem["description"] == DESCRIPTION
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert problem["hints"] == HINTS
    assert problem["has_guided_walkthrough"] is False

    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 64
    assert [step.stepNumber for step in guide.steps] == list(range(1, 65))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert [
        (phase.name, phase.stepRange[0], phase.stepRange[1]) for phase in guide.phases
    ] == EXPECTED_PHASES

    covered_steps = {}
    for phase in guide.phases:
        start, end = phase.stepRange
        assert len(phase.stepRange) == 2
        assert 1 <= start <= end <= guide.totalSteps
        for step_number in range(start, end + 1):
            assert step_number not in covered_steps
            covered_steps[step_number] = phase.name
    assert list(covered_steps) == list(range(1, guide.totalSteps + 1))
    assert all(covered_steps[step.stepNumber] == step.phase for step in guide.steps)
    assert {step.type for step in guide.steps} == STEP_TYPES
    assert all(step.title and step.content and step.requirementIds for step in guide.steps)

    all_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    action_steps = {step.id: step for step in guide.steps if step.type in ACTION_TYPES}
    action_anchors = {
        anchor for step in action_steps.values() for anchor in step.requirementIds
    }
    assert all_anchors == action_anchors == ANCHORS
    for anchor, evidence_steps in ACTION_ANCHOR_EVIDENCE.items():
        assert evidence_steps <= action_steps.keys(), f"Unknown action for {anchor}"
        assert any(
            anchor in action_steps[step_id].requirementIds for step_id in evidence_steps
        ), f"No concrete non-intro action covers {anchor}"

    for step in guide.steps:
        if step.type == "add_component":
            assert step.component is not None
            assert step.component.position.keys() == {"x", "y"}
            assert not step.connection and not step.decision
        elif step.type == "add_connection":
            assert step.connection is not None
            assert step.connection.label and step.connection.description
            assert step.connection.connectionType in CONNECTION_TYPES
            assert not step.component and not step.decision
        elif step.type == "decision_point":
            assert step.decision and step.componentUpdate
            assert len(step.decision.alternatives) >= 2
            assert all(item.option and item.tradeoff for item in step.decision.alternatives)
        elif step.type == "scale_trigger":
            assert step.scaleTrigger and step.componentUpdate
            assert all(
                (step.scaleTrigger.metric, step.scaleTrigger.action, step.scaleTrigger.impact)
            )

    intro = guide.steps[0].content
    assert DESCRIPTION in intro
    assert all(text in intro for text in REQUIREMENTS + CONSTRAINTS + HINTS)
    assert raw["totalSteps"] == len(raw["steps"])


def test_catalog_components_properties_and_select_options_are_valid():
    raw, _, guide = _load()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}
    edge_ids = set()

    for step in guide.steps:
        if step.type == "add_component":
            component = step.component.model_dump()
            node_id = component["nodeId"]
            assert node_id not in components
            assert component["componentType"] != "custom-component"
            assert component["properties"]["componentName"] == component["label"]
            assert len(component["properties"]["purpose"]) >= 60
            assert component["highlightReason"]
            _assert_supported_properties(
                component["componentType"], component["properties"], catalog
            )
            components[node_id] = component
        elif step.type == "add_connection":
            connection = step.connection
            assert connection.edgeId not in edge_ids
            edge_ids.add(connection.edgeId)
            assert connection.sourceNodeId in components
            assert connection.targetNodeId in components
        if step.componentUpdate:
            update = step.componentUpdate
            assert update.nodeId in components
            _assert_supported_properties(
                components[update.nodeId]["componentType"], update.properties, catalog
            )

    assert len(components) == 18
    assert len(edge_ids) == 35
    assert {item["componentType"] for item in components.values()} == {
        "analytics",
        "api-gateway",
        "auth-service",
        "backend-server",
        "database",
        "message-broker",
        "monitoring",
        "object-storage",
        "queue",
        "stream-processor",
        "web-app",
        "secrets-manager",
    }
    assert {
        components[node_id]["properties"]["provider"]
        for node_id in ("mcs_s3", "mcs_azure", "mcs_gcs")
    } == {"S3", "Azure Blob", "GCS"}
    assert all(
        components[node_id]["properties"]["checksumValidation"] is True
        and components[node_id]["properties"]["versioning"] is True
        for node_id in ("mcs_s3", "mcs_azure", "mcs_gcs")
    )
    assert all(
        components[node_id]["componentType"] == "object-storage"
        for node_id in ("mcs_s3", "mcs_azure", "mcs_gcs")
    )
    assert "custom-component" not in {
        step.component.componentType
        for step in guide.steps
        if step.type == "add_component"
    }


def test_provider_guarantees_are_separated_from_provider_assumptions_and_anchors_are_narrow():
    raw, _, guide = _load()
    steps = {step.id: step for step in guide.steps}

    expected_anchors = {
        "mcs_02_console": {"legacy-requirement:6"},
        "mcs_03_gateway": {"legacy-requirement:1"},
        "mcs_13_s3": {
            "legacy-requirement:1",
            "legacy-requirement:3",
            "legacy-constraint:3",
            "legacy-constraint:5",
        },
        "mcs_14_azure": {
            "legacy-requirement:1",
            "legacy-requirement:3",
            "legacy-constraint:3",
            "legacy-constraint:5",
        },
        "mcs_15_gcs": {
            "legacy-requirement:1",
            "legacy-requirement:3",
            "legacy-constraint:3",
            "legacy-constraint:5",
        },
        "mcs_16_events": {"legacy-requirement:5", "legacy-constraint:1"},
        "mcs_17_broker": {"legacy-requirement:5", "legacy-requirement:7"},
        "mcs_18_scanner": {
            "legacy-requirement:3",
            "legacy-requirement:5",
            "legacy-requirement:7",
        },
        "mcs_19_s3_events": {"legacy-requirement:5"},
        "mcs_20_azure_events": {"legacy-requirement:5"},
        "mcs_21_gcs_events": {"legacy-requirement:5"},
        "mcs_22_events_bus": {"legacy-requirement:5"},
        "mcs_24_s3_scan": {"legacy-requirement:3", "legacy-requirement:5"},
        "mcs_25_azure_scan": {"legacy-requirement:3", "legacy-requirement:5"},
        "mcs_26_gcs_scan": {
            "legacy-requirement:3",
            "legacy-requirement:5",
            "legacy-constraint:5",
        },
        "mcs_27_scanner_coordinator": {
            "legacy-requirement:3",
            "legacy-requirement:5",
            "legacy-constraint:5",
        },
        "mcs_33_transfer_queue": {"legacy-requirement:7"},
        "mcs_34_dead_letter": {"legacy-requirement:6", "legacy-requirement:7"},
        "mcs_35_transfer_workers": {
            "legacy-requirement:1",
            "legacy-requirement:3",
            "legacy-requirement:4",
            "legacy-requirement:7",
            "legacy-constraint:2",
            "legacy-constraint:3",
            "legacy-constraint:5",
        },
        "mcs_37_coordinator_queue": {
            "legacy-requirement:2",
            "legacy-requirement:5",
            "legacy-constraint:5",
        },
        "mcs_queue_workers": {"legacy-requirement:7"},
        "mcs_54_cost_analytics": {
            "legacy-requirement:8",
            "legacy-constraint:4",
        },
    }
    for step_id, anchors in expected_anchors.items():
        assert set(steps[step_id].requirementIds) == anchors, step_id

    first_phase = guide.phases[0].description.casefold()
    assert "provider-independent" in first_phase
    assert "provider-specific" in first_phase
    assert "decimal-unit" in first_phase

    consistency = steps["mcs_11_consistency_decision"].content.casefold()
    for phrase in (
        "provider-independent service contract",
        "opaque provider-local",
        "not assume tokens are mutually comparable",
        "not label a multi-destination job globally atomic",
    ):
        assert phrase in consistency

    provider_text = {
        provider: steps[step_id].content.casefold()
        for provider, step_id in (
            ("s3", "mcs_13_s3"),
            ("azure", "mcs_14_azure"),
            ("gcs", "mcs_15_gcs"),
        )
    }
    assert "only when bucket versioning is enabled" in provider_text["s3"]
    assert "not a portable revision sequence or checksum" in provider_text["azure"]
    assert "gcs-local revision metadata" in provider_text["gcs"]
    assert all("not a cross-provider guarantee" in content for content in provider_text.values())

    intro = steps["mcs_01_brief"].content.casefold()
    assert "333 gb/s" in intro and "2.67 tb/s" in intro
    assert "no such throughput guarantee" in intro
    assert "for just one full copy" in intro
    assert "before protocol overhead" in intro
    assert raw["totalSteps"] == len(raw["steps"])


def test_ordered_replay_is_one_connected_graph_with_required_data_paths():
    raw, _, _ = _load()
    built = build_architecture(raw)
    architecture = built["architecture"]
    nodes = {row["id"]: row for row in architecture["components"]}
    edges = architecture["connections"]
    assert len(nodes) == 18
    assert len(edges) == 35
    assert built["provenance"]["problemId"] == PROBLEM_ID
    assert built["provenance"]["walkthroughVersion"] == "1.0.0-review-draft"

    neighbors = {node_id: set() for node_id in nodes}
    directed = {node_id: set() for node_id in nodes}
    seen_pairs = set()
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] in CONNECTION_TYPES
        assert edge["label"] and edge["description"]
        pair = (edge["source"], edge["target"])
        assert pair not in seen_pairs, f"Duplicate directed edge: {pair}"
        seen_pairs.add(pair)
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
        directed[edge["source"]].add(edge["target"])

    visited = set()
    pending = deque(["mcs_console"])
    while pending:
        current = pending.popleft()
        if current not in visited:
            visited.add(current)
            pending.extend(neighbors[current] - visited)
    assert visited == set(nodes)

    def reaches(source: str, target: str) -> bool:
        reached = set()
        pending_nodes = [source]
        while pending_nodes:
            current = pending_nodes.pop()
            if current == target:
                return True
            if current not in reached:
                reached.add(current)
                pending_nodes.extend(directed[current] - reached)
        return False

    assert reaches("mcs_console", "mcs_metadata")
    assert reaches("mcs_s3", "mcs_coordinator")
    assert reaches("mcs_azure", "mcs_coordinator")
    assert reaches("mcs_gcs", "mcs_coordinator")
    assert reaches("mcs_reconciler", "mcs_coordinator")
    assert reaches("mcs_coordinator", "mcs_transfer_workers")
    assert all(
        reaches("mcs_transfer_workers", node_id)
        for node_id in ("mcs_s3", "mcs_azure", "mcs_gcs", "mcs_metadata")
    )
    assert reaches("mcs_transfer_queue", "mcs_dead_letter")
    assert reaches("mcs_transfer_workers", "mcs_monitoring")
    assert reaches("mcs_transfer_workers", "mcs_cost_analytics")


def test_domain_safety_recovery_cost_and_no_unearned_guarantees():
    raw, _, _ = _load()
    content = json.dumps(raw, ensure_ascii=False).casefold()
    for evidence in (
        "provisional assumptions",
        "333 gb/s",
        "2.67 tb/s",
        "no such throughput guarantee",
        "provider events are hints",
        "eventual convergence",
        "globally atomic",
        "last-writer-wins",
        "at-least-once",
        "inventory reconciliation",
        "conditional write",
        "multipart",
        "resumable",
        "checksum mismatch",
        "dead-letter",
        "quarantine",
        "short-lived",
        "federation",
        "egress",
        "billing exports",
        "provider-native direct",
        "versioned tombstones",
        "cannot resurrect deleted data",
        "configured provider-side encryption policy",
        "partial completion",
        "five-minute",
        "not establish that those targets have been achieved",
    ):
        assert evidence in content, f"Missing domain-specific guidance: {evidence}"

    for phrase in HINTS:
        assert phrase.casefold() in raw["steps"][0]["content"].casefold()
    assert all(anchor in content for anchor in ANCHORS)
    assert "95%" not in content
    assert "100tb+ in under 5 minutes is guaranteed" not in content

