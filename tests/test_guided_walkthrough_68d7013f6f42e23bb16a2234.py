"""Structural and brief-traceability checks for the file-storage review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "68d7013f6f42e23bb16a2234"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

TITLE = "Distributed File Storage"
DESCRIPTION = (
    "Design a distributed file storage system like Google Drive or Dropbox "
    "for storing and sharing files."
)
REQUIREMENTS = [
    "Upload, download, and store files",
    "File sharing with permissions",
    "File versioning and history",
    "Synchronization across devices",
    "Search files by name and content",
    "Handle large files (up to 1GB)",
    "Support billions of files",
    "Offline access capabilities",
]
CONSTRAINTS = [
    "Fast upload and download speeds",
    "Handle concurrent file modifications",
    "Efficient storage utilization",
    "Data durability and backup",
    "Support different file types",
]
HINTS = [
    "Chunked file storage for large files",
    "Metadata database for file information",
    "CDN for fast file access",
    "Conflict resolution for simultaneous edits",
    "Deduplication to save storage space",
]
STEP_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "decision_point",
    "scale_trigger",
}
CONNECTION_TYPES = {
    "http",
    "tcp",
    "websocket",
    "message-queue",
    "database-connection",
    "api-call",
    "data-flow",
    "event-stream",
}
ACTION_TYPES = {"add_component", "add_connection", "decision_point", "scale_trigger"}
ANCHORS = {
    *(f"legacy-requirement:{index}" for index in range(1, len(REQUIREMENTS) + 1)),
    *(f"legacy-constraint:{index}" for index in range(1, len(CONSTRAINTS) + 1)),
}
ACTION_ANCHOR_EVIDENCE = {
    "legacy-requirement:1": {"dfs_21", "dfs_22", "dfs_23", "dfs_24"},
    "legacy-requirement:2": {"dfs_13", "dfs_15", "dfs_25", "dfs_38", "dfs_50"},
    "legacy-requirement:3": {"dfs_15", "dfs_19", "dfs_29", "dfs_42"},
    "legacy-requirement:4": {"dfs_44", "dfs_46", "dfs_47", "dfs_48"},
    "legacy-requirement:5": {"dfs_36", "dfs_37", "dfs_38"},
    "legacy-requirement:6": {"dfs_19", "dfs_21", "dfs_22", "dfs_23", "dfs_24", "dfs_29"},
    "legacy-requirement:7": {"dfs_14", "dfs_36", "dfs_64"},
    "legacy-requirement:8": {"dfs_03", "dfs_54"},
    "legacy-constraint:1": {"dfs_20", "dfs_21", "dfs_22", "dfs_65"},
    "legacy-constraint:2": {"dfs_15", "dfs_24", "dfs_42", "dfs_64"},
    "legacy-constraint:3": {"dfs_31", "dfs_40"},
    "legacy-constraint:4": {"dfs_19", "dfs_29", "dfs_55", "dfs_56", "dfs_57", "dfs_66"},
    "legacy-constraint:5": {"dfs_19", "dfs_31", "dfs_37", "dfs_39", "dfs_60"},
}


def load_guide_and_problem():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    return raw, problem


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"{step_id}: unknown catalog component {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), (
        f"{step_id}: incomplete catalog definition for {component_type}"
    )
    return catalog[match.start() : block_end]


def assert_catalog_properties(
    catalog: str, component_type: str, properties: dict, step_id: str
) -> None:
    block = catalog_block(catalog, component_type, step_id)
    supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
    assert set(properties) <= supported, (
        f"{step_id}: unsupported {component_type} properties "
        f"{sorted(set(properties) - supported)}"
    )

    for key, value in properties.items():
        field_start = re.search(rf'\{{\s*key:\s*"{re.escape(key)}"', block)
        assert field_start, f"{step_id}: missing {component_type}.{key} in catalog"
        field_end = block.find("},", field_start.start())
        assert field_end != -1, f"{step_id}: incomplete catalog property {key}"
        field = block[field_start.start() : field_end]
        field_type = re.search(r'\btype:\s*"([^"]+)"', field)
        assert field_type, f"{step_id}: catalog property {key} has no type"

        kind = field_type.group(1)
        if kind == "boolean":
            assert type(value) is bool, f"{step_id}/{key} must be boolean"
        elif kind == "number":
            assert type(value) in (int, float), f"{step_id}/{key} must be numeric"
        elif kind in {"text", "textarea"}:
            assert isinstance(value, str), f"{step_id}/{key} must be text"
        elif kind == "select":
            options = re.search(r'\boptions:\s*\[([^\]]*)\]', field, re.DOTALL)
            assert options, f"{step_id}/{key}: select options are missing"
            allowed = set(re.findall(r'"([^"]+)"', options.group(1)))
            assert value in allowed, (
                f"{step_id}/{key}: {value!r} is not one of {sorted(allowed)}"
            )


def test_live_brief_schema_phases_and_exact_legacy_anchor_coverage():
    raw, problem = load_guide_and_problem()
    guide = GuidedWalkthrough.model_validate(raw)

    assert problem["title"] == TITLE
    assert problem["description"] == DESCRIPTION
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert problem["hints"] == HINTS
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 66
    assert [step.stepNumber for step in guide.steps] == list(range(1, 67))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert {step.type for step in guide.steps} == STEP_TYPES

    next_expected = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_expected
        assert start <= end <= guide.totalSteps
        assert all(step.phase == phase.name for step in guide.steps[start - 1 : end])
        next_expected = end + 1
    assert next_expected == guide.totalSteps + 1
    assert raw["totalSteps"] == len(raw["steps"])

    for step in guide.steps:
        assert step.title and step.content
        assert set(step.requirementIds) <= ANCHORS
        if step.type == "add_component":
            assert step.component is not None
            assert set(step.component.position) == {"x", "y"}
            assert step.component.label == step.component.properties["componentName"]
            assert len(step.component.properties["purpose"]) >= 60
        elif step.type == "add_connection":
            assert step.connection is not None
            assert step.connection.connectionType in CONNECTION_TYPES
            assert step.connection.label and step.connection.description
        elif step.type == "decision_point":
            assert step.decision and step.componentUpdate
            assert step.decision.question and step.decision.chosen
            assert step.decision.chosenReason
            assert len(step.decision.alternatives) >= 2
            assert all(item.option and item.tradeoff for item in step.decision.alternatives)
        elif step.type == "scale_trigger":
            assert step.scaleTrigger
            assert all(
                (
                    step.scaleTrigger.metric,
                    step.scaleTrigger.action,
                    step.scaleTrigger.impact,
                )
            )

    brief_text = guide.steps[0].content
    for item in [TITLE, DESCRIPTION, *REQUIREMENTS, *CONSTRAINTS, *HINTS]:
        assert item in brief_text, f"Supplied brief item missing from framing: {item}"

    mapped_anchors = {
        anchor for step in guide.steps for anchor in step.requirementIds
    }
    action_anchors = {
        anchor
        for step in guide.steps
        if step.type in ACTION_TYPES
        for anchor in step.requirementIds
    }
    assert mapped_anchors == action_anchors == ANCHORS

    steps_by_id = {step.id: step for step in guide.steps}
    for anchor, evidence_steps in ACTION_ANCHOR_EVIDENCE.items():
        assert evidence_steps <= steps_by_id.keys()
        assert any(
            anchor in steps_by_id[step_id].requirementIds
            and steps_by_id[step_id].type in ACTION_TYPES
            for step_id in evidence_steps
        ), f"No concrete design action covers {anchor}"


def test_all_nodes_and_updates_use_existing_catalog_properties():
    raw, _ = load_guide_and_problem()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}

    for step in raw["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            assert component["componentType"] != "custom-component"
            assert component["nodeId"] not in components
            assert component["properties"]["componentName"] == component["label"]
            assert len(component["properties"]["purpose"]) >= 60
            assert_catalog_properties(
                catalog, component["componentType"], component["properties"], step["id"]
            )
            components[component["nodeId"]] = component

    assert len(components) == 17
    assert {
        component["componentType"] for component in components.values()
    } == {
        "api-gateway",
        "auth-service",
        "backend-server",
        "cache",
        "cdn",
        "cold-storage",
        "database",
        "desktop-app",
        "message-broker",
        "mobile-app",
        "monitoring",
        "notification-service",
        "object-storage",
        "processing-worker",
        "queue",
        "search-engine",
        "web-app",
    }

    for step in raw["steps"]:
        update = step.get("componentUpdate")
        if update:
            assert update["nodeId"] in components
            assert update["properties"]
            assert_catalog_properties(
                catalog,
                components[update["nodeId"]]["componentType"],
                update["properties"],
                step["id"],
            )

    assert components["dfs_objects"]["componentType"] == "object-storage"
    assert components["dfs_metadata"]["componentType"] == "database"
    assert components["dfs_worker"]["componentType"] == "processing-worker"
    assert all(
        component["componentType"] != "custom-component"
        for component in components.values()
    )


def test_ordered_actions_replay_as_one_connected_file_storage_graph():
    raw, _ = load_guide_and_problem()
    component_ids = [
        step["component"]["nodeId"]
        for step in raw["steps"]
        if step["type"] == "add_component"
    ]
    edge_ids = [
        step["connection"]["edgeId"]
        for step in raw["steps"]
        if step["type"] == "add_connection"
    ]
    assert len(component_ids) == len(set(component_ids)) == 17
    assert len(edge_ids) == len(set(edge_ids)) == 37

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    edges = architecture["connections"]
    assert len(nodes) == 17
    assert len(edges) == 37
    assert len(replay["acceptedDecisions"]) == 7

    neighbors = {node_id: set() for node_id in nodes}
    directed = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] in CONNECTION_TYPES
        assert edge["label"] and edge["description"]
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
        directed[edge["source"]].add(edge["target"])

    reached = set()
    pending = deque(["dfs_web"])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    assert reached == set(nodes)

    def reaches(source: str, target: str) -> bool:
        seen = set()
        pending_nodes = [source]
        while pending_nodes:
            current = pending_nodes.pop()
            if current == target:
                return True
            if current not in seen:
                seen.add(current)
                pending_nodes.extend(directed[current] - seen)
        return False

    assert reaches("dfs_web", "dfs_gateway")
    assert reaches("dfs_gateway", "dfs_metadata")
    assert reaches("dfs_mobile", "dfs_objects")
    assert reaches("dfs_desktop", "dfs_cdn")
    assert reaches("dfs_objects", "dfs_ingest_queue")
    assert reaches("dfs_ingest_queue", "dfs_worker")
    assert reaches("dfs_worker", "dfs_search")
    assert reaches("dfs_metadata", "dfs_backup")
    assert reaches("dfs_objects", "dfs_backup")
    assert reaches("dfs_metadata", "dfs_monitoring")


def test_file_storage_content_covers_failure_security_tradeoffs_and_unknown_targets():
    raw, _ = load_guide_and_problem()
    content = json.dumps(raw, ensure_ascii=False).casefold()
    for phrase in (
        "1gb",
        "billions of files",
        "resumable",
        "chunk",
        "checksum",
        "immutable",
        "manifest",
        "base revision",
        "conflict version",
        "offline",
        "deduplicate",
        "tenant-scoped",
        "reference-aware",
        "revocation",
        "signed",
        "reauthorized",
        "unsupported-format",
        "dead-letter",
        "outbox",
        "tombstone",
        "backup",
        "restore",
        "partition skew",
        "no numeric slo",
        "implementation assumptions",
        "not guarantees",
    ):
        assert phrase in content, f"Missing file-storage concern or caveat: {phrase}"

    assert "99.9%" not in content
    assert "50ms" not in content
    assert "custom-component" not in {
        step.get("component", {}).get("componentType") for step in raw["steps"]
    }


def test_anchors_distinguish_permissions_versions_sync_search_scale_and_recovery():
    raw, _ = load_guide_and_problem()
    steps = {step["id"]: step for step in raw["steps"]}

    def has(step_id: str, anchor: str) -> bool:
        return anchor in steps[step_id]["requirementIds"]

    permission = "legacy-requirement:2"
    versions = "legacy-requirement:3"
    sync = "legacy-requirement:4"
    search = "legacy-requirement:5"
    offline = "legacy-requirement:8"
    durability_backup = "legacy-constraint:4"

    assert has("dfs_13", permission)
    assert not has("dfs_13", versions)
    assert has("dfs_15", permission) and has("dfs_15", versions)
    assert all(has(step_id, versions) for step_id in ("dfs_29", "dfs_42"))
    assert not any(
        has(step_id, versions) for step_id in ("dfs_34", "dfs_35", "dfs_60", "dfs_61")
    )

    offline_action_ids = {
        step["id"]
        for step in raw["steps"]
        if step["type"] in ACTION_TYPES and offline in step["requirementIds"]
    }
    assert offline_action_ids == {"dfs_03", "dfs_04", "dfs_27", "dfs_54"}
    assert all(has(step_id, sync) for step_id in ("dfs_46", "dfs_47", "dfs_48"))
    assert not any(
        has(step_id, offline)
        for step_id in ("dfs_09", "dfs_23", "dfs_47", "dfs_48", "dfs_52", "dfs_53")
    )

    assert all(has(step_id, search) for step_id in ("dfs_36", "dfs_37", "dfs_38", "dfs_39"))
    assert not has("dfs_35", versions)
    assert not has("dfs_40", "legacy-constraint:5")
    assert not has("dfs_62", "legacy-constraint:5")
    assert has("dfs_40", "legacy-constraint:3")
    assert not has("dfs_31", "legacy-constraint:3")

    assert has("dfs_64", "legacy-requirement:7")
    assert not has("dfs_64", "legacy-constraint:1")
    assert all(
        has(step_id, durability_backup)
        for step_id in ("dfs_55", "dfs_56", "dfs_57", "dfs_66")
    )
    assert not any(
        has(step_id, durability_backup)
        for step_id in ("dfs_14", "dfs_32", "dfs_33", "dfs_41", "dfs_43", "dfs_44", "dfs_45")
    )


def test_file_storage_has_no_invented_numeric_slos_or_recovery_policies():
    raw, _ = load_guide_and_problem()
    serialized = json.dumps(raw, ensure_ascii=False)

    assert "1GB" in serialized
    assert "billions of files" in serialized
    assert not re.search(r"\b\d+(?:\.\d+)?\s*%", serialized)
    assert not re.search(r"\b(?:RPO|RTO)\s*(?:of\s*)?[:=]?\s*\d", serialized, re.IGNORECASE)
    assert not re.search(
        r"\b\d+(?:\.\d+)?\s*(?:[KMGT]i?B|[KMGT]B)\s*/\s*(?:s|sec(?:ond)?s?)\b",
        serialized,
        re.IGNORECASE,
    )
    assert not re.search(r"\bretention\b[^.;]{0,80}\b\d+\b", serialized, re.IGNORECASE)
