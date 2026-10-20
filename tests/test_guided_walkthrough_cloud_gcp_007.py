"""Focused structural contract for the video-transcoding review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_gcp_007"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

DESCRIPTION = (
    "Design a video transcoding and processing pipeline that uploads videos, "
    "transcodes to multiple formats, generates thumbnails, and delivers content via CDN."
)
REQUIREMENTS = [
    "Upload videos at scale",
    "Transcode to multiple formats",
    "Generate thumbnails",
    "Extract metadata",
    "Implement DRM protection",
    "Optimize for adaptive streaming",
    "Handle processing failures",
    "Monitor transcoding jobs",
]
CONSTRAINTS = [
    "Process 1000+ hours of video daily",
    "Transcoding time under 2x real-time",
    "Support 4K and HDR content",
    "Cost-effective processing",
    "Handle large file uploads (100GB+)",
]
HINTS = [
    "Cloud Storage for video storage",
    "Transcoder API for encoding",
    "Cloud Run for custom processing",
    "Pub/Sub for event notifications",
    "Cloud CDN for delivery",
    "Cloud Functions for orchestration",
]


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def catalog_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'(?m)^    id:\s*"{re.escape(component_type)}"', catalog)
    assert match, f"unknown catalog component type: {component_type}"
    end = catalog.find("\n  },", match.start())
    assert end > match.start(), f"could not bound catalog definition: {component_type}"
    return catalog[match.start() : end]


def catalog_keys(block: str) -> set[str]:
    return set(re.findall(r'\bkey:\s*"([^"]+)"', block))


def catalog_options(block: str, key: str) -> set[str]:
    marker = re.search(rf'\bkey:\s*"{re.escape(key)}"', block)
    assert marker, f"catalog property missing: {key}"
    remainder = block[marker.end() :]
    property_end = re.search(r"\n      },", remainder)
    section = remainder[: property_end.start()] if property_end else remainder
    options = re.search(r"options:\s*\[([\s\S]*?)\]", section)
    assert options, f"{key} is not a catalog select property"
    return set(re.findall(r'"([^"]+)"', options.group(1)))


def test_schema_step_order_phase_ranges_and_action_payloads():
    raw, guide = load_guide()
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 40
    assert [step.stepNumber for step in guide.steps] == list(range(1, 41))
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

    allowed = {
        "explanation",
        "add_component",
        "add_connection",
        "decision_point",
        "scale_trigger",
    }
    assert {step.type for step in guide.steps} == allowed
    for step in guide.steps:
        assert step.title and step.content
        if step.id == "video_scope":
            assert step.requirementIds == []
        else:
            assert step.requirementIds
        if step.type == "add_component":
            assert step.component is not None
            assert step.component.position.keys() == {"x", "y"}
            assert not step.connection and not step.decision
        elif step.type == "add_connection":
            assert step.connection is not None
            assert step.connection.label and step.connection.description
            assert not step.component and not step.decision
        elif step.type == "decision_point":
            assert step.decision is not None and step.componentUpdate is None
            assert step.decision.question and step.decision.chosen and step.decision.chosenReason
            assert len(step.decision.alternatives) >= 2
            assert all(option.option and option.tradeoff for option in step.decision.alternatives)
        elif step.type == "scale_trigger":
            assert step.scaleTrigger is not None and step.componentUpdate is not None
            assert step.scaleTrigger.metric and step.scaleTrigger.action and step.scaleTrigger.impact
        else:
            assert step.component is None and step.connection is None
    assert raw["totalSteps"] == len(raw["steps"])


def test_exact_frozen_problem_brief_and_requirement_traceability():
    _, guide = load_guide()
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    assert problem["slug"] == "video-transcoding-pipeline"
    assert problem["title"] == "Design a Video Processing and Transcoding Pipeline"
    assert problem["description"] == DESCRIPTION
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert problem["hints"] == HINTS
    assert problem["companies"] == ["Google", "YouTube", "Netflix"]
    assert problem["has_guided_walkthrough"] is False

    expected_ids = {
        *(f"legacy-requirement:{index}" for index in range(1, 9)),
        *(f"legacy-constraint:{index}" for index in range(1, 6)),
    }
    mapped_ids = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert mapped_ids == expected_ids

    expected_anchors = {
        "video_scope": set(),
        "video_slo_questions": {"legacy-constraint:1"},
        "video_realtime_definition": {"legacy-constraint:2", "legacy-requirement:8"},
        "video_profile_questions": {"legacy-requirement:2", "legacy-requirement:6", "legacy-constraint:3"},
        "video_clients": {"legacy-requirement:1", "legacy-constraint:5"},
        "video_upload_api": {"legacy-requirement:1", "legacy-constraint:5"},
        "video_raw_storage": {"legacy-requirement:1", "legacy-constraint:5"},
        "video_client_api_edge": {"legacy-requirement:1", "legacy-constraint:5"},
        "video_api_storage_edge": {"legacy-requirement:1", "legacy-constraint:5"},
        "video_manifest_store": {"legacy-requirement:7", "legacy-requirement:8"},
        "video_pubsub": {"legacy-requirement:2", "legacy-requirement:7", "legacy-requirement:8"},
        "video_object_event": {"legacy-requirement:1"},
        "video_functions": {"legacy-requirement:2", "legacy-requirement:7", "legacy-requirement:8"},
        "video_events_function_edge": {"legacy-requirement:2", "legacy-requirement:7", "legacy-requirement:8"},
        "video_cloud_run": {"legacy-requirement:3", "legacy-requirement:4", "legacy-constraint:3"},
        "video_submit_custom_edge": {"legacy-requirement:3", "legacy-requirement:4", "legacy-requirement:7"},
        "video_transcoder": {"legacy-requirement:2", "legacy-requirement:6", "legacy-constraint:2", "legacy-constraint:3"},
        "video_submit_transcode_edge": {"legacy-requirement:2", "legacy-requirement:6", "legacy-requirement:7"},
        "video_record_job_edge": {"legacy-requirement:7", "legacy-requirement:8"},
        "video_output_storage": {"legacy-requirement:2", "legacy-requirement:3", "legacy-requirement:4", "legacy-requirement:6"},
        "video_custom_output_edge": {"legacy-requirement:3", "legacy-requirement:4", "legacy-requirement:7"},
        "video_transcode_output_edge": {"legacy-requirement:2", "legacy-requirement:6", "legacy-requirement:7"},
        "video_custom_completion_edge": {"legacy-requirement:3", "legacy-requirement:4", "legacy-requirement:7"},
        "video_transcode_completion_edge": {"legacy-requirement:2", "legacy-requirement:7", "legacy-requirement:8"},
        "video_completion_handler_edge": {"legacy-requirement:7", "legacy-requirement:8"},
        "video_retry_decision": {"legacy-requirement:7"},
        "video_failure_state_edge": {"legacy-requirement:7", "legacy-requirement:8"},
        "video_publish_decision": {"legacy-requirement:2", "legacy-requirement:3", "legacy-requirement:4", "legacy-requirement:5", "legacy-requirement:6"},
        "video_drm_boundary": {"legacy-requirement:5"},
        "video_transcoder_drm_edge": {"legacy-requirement:5", "legacy-requirement:6"},
        "video_cdn_boundary": {"legacy-requirement:6"},
        "video_drm_output_edge": {"legacy-requirement:5", "legacy-requirement:6"},
        "video_cdn_origin_edge": {"legacy-requirement:5", "legacy-requirement:6"},
        "video_playback_edge": {"legacy-requirement:5", "legacy-requirement:6"},
        "video_monitoring_boundary": {"legacy-requirement:8", "legacy-constraint:1", "legacy-constraint:2"},
        "video_monitoring_workers_edge": {"legacy-requirement:8", "legacy-constraint:1", "legacy-constraint:2"},
        "video_worker_monitoring_edge": {"legacy-requirement:3", "legacy-requirement:4", "legacy-requirement:8", "legacy-constraint:3"},
        "video_transcoder_monitoring_edge": {"legacy-requirement:8", "legacy-constraint:1", "legacy-constraint:2", "legacy-constraint:3"},
        "video_capacity_trigger": {"legacy-constraint:1", "legacy-constraint:2", "legacy-constraint:4"},
        "video_cost_decision": {"legacy-constraint:4"},
    }
    assert {step.id: set(step.requirementIds) for step in guide.steps} == expected_anchors


def test_media_format_coverage_and_queued_transcode_workflow_are_explicit():
    _, guide = load_guide()
    steps = {step.id: step for step in guide.steps}

    profile_text = steps["video_profile_questions"].content.casefold()
    for signal in (
        "multiple formats",
        "containers/codecs",
        "adaptive renditions",
        "output video/audio codecs",
        "hdr transfer functions",
        "resolution/bitrate ladder",
        "manifest/packaging protocol",
        "compatibility matrix",
    ):
        assert signal in profile_text

    transcoder_text = steps["video_transcoder"].content.casefold()
    for signal in (
        "owner-approved output profile",
        "containers/codecs",
        "adaptive renditions",
        "complete output set",
        "adaptive manifest",
        "4k/hdr",
        "successful submission is not proof",
    ):
        assert signal in transcoder_text

    workflow_text = " ".join(
        steps[step_id].content.casefold()
        for step_id in (
            "video_pubsub",
            "video_object_event",
            "video_events_function_edge",
            "video_submit_transcode_edge",
            "video_record_job_edge",
            "video_transcode_completion_edge",
            "video_completion_handler_edge",
        )
    )
    for signal in ("queue", "subscription", "profile version", "job identity", "redelivery", "reconcile"):
        assert signal in workflow_text

    connections = {step.connection.edgeId: step.connection for step in guide.steps if step.connection}
    assert (connections["video_object_event"].sourceNodeId, connections["video_object_event"].targetNodeId) == (
        "video_raw_storage",
        "video_events",
    )
    assert (connections["video_events_function"].sourceNodeId, connections["video_events_function"].targetNodeId) == (
        "video_events",
        "video_orchestrator",
    )
    assert (connections["video_submit_transcode"].sourceNodeId, connections["video_submit_transcode"].targetNodeId) == (
        "video_orchestrator",
        "video_transcoder",
    )
    assert (connections["video_transcode_completion"].sourceNodeId, connections["video_transcode_completion"].targetNodeId) == (
        "video_transcoder",
        "video_events",
    )
    assert (connections["video_completion_handler"].sourceNodeId, connections["video_completion_handler"].targetNodeId) == (
        "video_events",
        "video_orchestrator",
    )

    narrative = " ".join(f"{step.title} {step.content}" for step in guide.steps).casefold()
    assert "1000+ source-video hours per day" in narrative
    assert "under 2x real-time" in narrative
    assert "100gb+" in narrative
    assert "not a measured throughput or latency result" in narrative
    assert "no numeric queue-wait or end-to-end latency slo" in narrative
    assert not re.search(r"\bp\d{2}\b|\b\d+(?:\.\d+)?\s*(?:ms|milliseconds?|requests?\s*(?:/|per)\s*second|jobs?\s*(?:/|per)\s*second|workers?|instances?)\b", narrative)


def test_existing_catalog_types_select_values_and_explicit_catalog_gaps():
    raw, guide = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step.component.nodeId: step.component
        for step in guide.steps
        if step.type == "add_component"
    }
    assert len(additions) == 12
    assert {node_id for node_id, component in additions.items() if component.componentType == "custom-component"} == {
        "video_drm",
    }
    for node_id in ("video_drm",):
        assert "catalog gap" in additions[node_id].properties["componentType"].casefold()
    assert additions["video_cdn"].properties["provider"] == "Google Cloud CDN"
    assert additions["video_monitoring"].properties["stack"] == "Google Cloud Monitoring"

    assert additions["video_raw_storage"].properties["provider"] == "GCS"
    assert additions["video_output_storage"].properties["provider"] == "GCS"
    assert additions["video_transcoder"].properties["tasks"] == "Media Encoding"
    assert additions["video_custom_worker"].properties["tasks"] == "Data Processing"

    for step in raw["steps"]:
        component = step.get("component")
        if component:
            component_type = component["componentType"]
            properties = component["properties"]
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            component_type = additions[update["nodeId"]].componentType
            properties = update["properties"]
        else:
            continue

        block = catalog_block(catalog, component_type)
        assert set(properties) <= catalog_keys(block)
        if component:
            assert properties["componentName"] == component["label"]
            assert len(properties["purpose"]) >= 45
            assert component["highlightReason"]

    assert "GCS" in catalog_options(catalog_block(catalog, "object-storage"), "provider")
    assert "Media Encoding" in catalog_options(catalog_block(catalog, "processing-worker"), "tasks")
    assert "Data Processing" in catalog_options(catalog_block(catalog, "processing-worker"), "tasks")
    assert "NoSQL" in catalog_options(catalog_block(catalog, "database"), "type")

    lesson = json.dumps(raw, ensure_ascii=False).casefold()
    for owner_question in (
        "arrival distributions",
        "under 2x real-time",
        "retention duration",
        "drm systems",
        "codec",
        "budget bound",
    ):
        assert owner_question in lesson
    assert "retentiondays" not in lesson
    assert "storagegb" not in lesson


def test_replay_builds_connected_gcp_media_architecture():
    raw, _ = load_guide()
    built = build_architecture(raw)
    architecture = built["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    edges = architecture["connections"]
    assert len(nodes) == 12
    assert len(edges) == 20
    assert len(built["appliedStepIds"]) == 33
    assert set(built["explanationOnlyStepIds"]) == {
        "video_scope",
        "video_slo_questions",
        "video_realtime_definition",
        "video_profile_questions",
        "video_retry_decision",
        "video_publish_decision",
        "video_cost_decision",
    }
    assert built["provenance"]["problemId"] == PROBLEM_ID
    assert built["provenance"]["walkthroughVersion"] == "1.0-review-draft"

    neighbors = {node_id: set() for node_id in nodes}
    edge_pairs = set()
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] and edge["description"]
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
        edge_pairs.add((edge["source"], edge["target"]))
    visited = set()
    pending = deque(["video_clients"])
    while pending:
        node_id = pending.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        pending.extend(neighbors[node_id] - visited)
    assert visited == set(nodes)

    assert {
        ("video_clients", "video_upload_api"),
        ("video_clients", "video_raw_storage"),
        ("video_raw_storage", "video_events"),
        ("video_events", "video_orchestrator"),
        ("video_orchestrator", "video_custom_worker"),
        ("video_orchestrator", "video_transcoder"),
        ("video_transcoder", "video_drm"),
        ("video_drm", "video_output_storage"),
        ("video_output_storage", "video_cdn"),
    } <= edge_pairs
