"""Frozen-brief, catalog, requirement-anchor, and replay checks for the downloader draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca889"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
FROZEN_BRIEF_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"


def load_frozen_brief():
    problems = json.loads(FROZEN_BRIEF_PATH.read_text(encoding="utf-8"))
    matches = [problem for problem in problems if problem.get("id") == PROBLEM_ID]
    assert len(matches) == 1, f"Expected one frozen brief for {PROBLEM_ID}"
    return matches[0]


FROZEN_BRIEF = load_frozen_brief()

EXPECTED_ANCHORS = {
    *(f"legacy-requirement:{number}" for number in range(1, len(FROZEN_BRIEF["requirements"]) + 1)),
    *(f"legacy-constraint:{number}" for number in range(1, len(FROZEN_BRIEF["constraints"]) + 1)),
}
ACTION_TYPES = {"add_component", "add_connection"}
REVIEWED_STEP_ANCHORS = {
    "downloader_03_no_capacity_guess": {"legacy-requirement:6"},
    "downloader_10_gateway": {"legacy-requirement:1", "legacy-requirement:3", "legacy-constraint:2"},
    "downloader_11_control": {"legacy-requirement:1", "legacy-requirement:2", "legacy-requirement:3", "legacy-constraint:4"},
    "downloader_14_limiter": {"legacy-requirement:8"},
    "downloader_19_route": {"legacy-requirement:1", "legacy-constraint:3"},
    "downloader_20_manifest_write": {"legacy-requirement:2", "legacy-requirement:7", "legacy-constraint:4"},
    "downloader_21_dispatch": {"legacy-requirement:7", "legacy-constraint:1", "legacy-constraint:4"},
    "downloader_22_consume": {"legacy-requirement:2", "legacy-constraint:4"},
    "downloader_25_checkpoint": {"legacy-requirement:2", "legacy-requirement:3", "legacy-constraint:1", "legacy-constraint:4"},
    "downloader_26_api_budget": {"legacy-requirement:8"},
    "downloader_27_worker_budget": {"legacy-requirement:8", "legacy-constraint:4"},
    "downloader_28_result_capability": {"legacy-requirement:5"},
    "downloader_29_deliver_artifact": {"legacy-requirement:1", "legacy-requirement:2", "legacy-requirement:6", "legacy-constraint:2", "legacy-constraint:5"},
    "downloader_30_progress_response": {"legacy-requirement:3", "legacy-constraint:1"},
    "downloader_31_api_metrics": set(),
    "downloader_32_worker_metrics": {"legacy-requirement:5", "legacy-requirement:7", "legacy-constraint:1"},
    "downloader_33_queue_metrics": {"legacy-requirement:7"},
    "downloader_35_resume_validator": {"legacy-requirement:2", "legacy-constraint:1"},
    "downloader_37_integrity": {"legacy-requirement:3", "legacy-requirement:5", "legacy-requirement:6", "legacy-constraint:2"},
    "downloader_38_atomic_publish": {"legacy-requirement:2", "legacy-requirement:5", "legacy-constraint:5"},
    "downloader_39_thread_safety": {"legacy-requirement:2", "legacy-requirement:4", "legacy-constraint:4"},
    "downloader_40_retry": {"legacy-requirement:2", "legacy-requirement:7", "legacy-constraint:1"},
}
NUMERIC_CAPACITY_PROMISE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:"
    r"(?:rps|qps|requests?\s*(?:/|per)\s*(?:s|sec|second)|"
    r"(?:downloads?|jobs?|workers?|chunks?|files?)\s*(?:/|per)\s*(?:s|sec|second|minute|hour))|"
    r"(?:ms|milliseconds?)\s*(?:latency|response time|completion time|timeout)|"
    r"(?:mb|gb|tb|mib|gib|tib)\s*(?:/|per)\s*(?:s|sec|second)|"
    r"(?:mb|gb|tb|mib|gib|tib)\b|"
    r"%\s*(?:availability|uptime|success rate|error rate))",
    re.IGNORECASE,
)
CONNECTION_TYPES = {
    "https",
    "api-call",
    "database-connection",
    "message-queue",
    "data-flow",
}
EXPECTED_PHASES = [
    ("Define the download contract", 1, 7),
    ("Place the client, control plane, and transfer services", 8, 17),
    ("Connect submission, transfer, and delivery", 18, 33),
    ("Make recovery and portability testable", 34, 44),
]


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(
        rf"(?ms)^\s{{4}}id: \"{re.escape(component_type)}\",.*?^\s{{2}}\}},",
        catalog,
    )
    assert match, f"{step_id}: unknown component catalog ID {component_type}"
    return match.group(0)


def reachable(start: str, neighbors: dict[str, set[str]]) -> set[str]:
    reached = set()
    pending = deque([start])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    return reached


def test_exact_live_brief_review_status_phases_and_actionable_anchors():
    raw, guide = load_guide()

    assert FROZEN_BRIEF["has_guided_walkthrough"] is False
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 44
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert [(phase.name, *phase.stepRange) for phase in guide.phases] == EXPECTED_PHASES

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end <= guide.totalSteps
        assert all(step.phase == phase.name for step in guide.steps[start - 1 : end])
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    all_anchors = set()
    action_anchors = set()
    steps_by_id = {step.id: step for step in guide.steps}
    for step_id, expected_anchors in REVIEWED_STEP_ANCHORS.items():
        assert set(steps_by_id[step_id].requirementIds) == expected_anchors, step_id
    for step in guide.steps:
        anchors = set(step.requirementIds)
        assert len(anchors) == len(step.requirementIds), f"{step.id}: repeated anchor"
        assert anchors <= EXPECTED_ANCHORS, f"{step.id}: unknown anchors {anchors - EXPECTED_ANCHORS}"
        all_anchors.update(anchors)
        if step.type in ACTION_TYPES:
            action_anchors.update(anchors)
    assert all_anchors == action_anchors == EXPECTED_ANCHORS


def test_catalog_nodes_and_ordered_actions_replay_to_one_end_to_end_graph():
    raw, guide = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}
    edge_ids = set()
    action_ids = []

    for step in guide.steps:
        if step.type == "add_component":
            component = step.component
            assert component is not None
            assert component.nodeId not in components
            assert set(component.position) == {"x", "y"}
            assert component.properties["componentName"] == component.label
            assert len(component.properties["purpose"]) >= 60
            block = catalog_block(catalog, component.componentType, step.id)
            supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
            assert set(component.properties) <= supported, (
                f"{step.id}: unsupported properties {set(component.properties) - supported}"
            )
            components[component.nodeId] = component
            action_ids.append(step.id)
        elif step.type == "add_connection":
            connection = step.connection
            assert connection is not None
            assert connection.edgeId not in edge_ids
            assert connection.sourceNodeId in components
            assert connection.targetNodeId in components
            assert connection.connectionType in CONNECTION_TYPES
            assert connection.label and connection.description
            edge_ids.add(connection.edgeId)
            action_ids.append(step.id)

    custom_nodes = [node for node in components.values() if node.componentType == "custom-component"]
    assert len(components) == 10
    assert len(edge_ids) == 16
    assert len(custom_nodes) == 1
    assert custom_nodes[0].nodeId == "downloader_origins"

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    edges = architecture["connections"]
    assert len(nodes) == 10
    assert len(edges) == 16
    assert replay["appliedStepIds"] == action_ids
    assert replay["explanationOnlyStepIds"]

    neighbors = {node_id: set() for node_id in nodes}
    directed = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
        directed[edge["source"]].add(edge["target"])
    assert reachable("downloader_client", neighbors) == set(nodes)

    def reaches(source: str, target: str) -> bool:
        return target in reachable(source, directed)

    assert reaches("downloader_client", "download_gateway")
    assert reaches("download_gateway", "download_control_api")
    assert reaches("download_control_api", "download_queue")
    assert reaches("download_queue", "transfer_workers")
    assert reaches("transfer_workers", "downloader_origins")
    assert reaches("transfer_workers", "verified_download_store")
    assert reaches("verified_download_store", "downloader_client")
    assert reaches("transfer_workers", "download_manifest")


def test_frozen_brief_reaches_assessment_payload_and_guide_explains_failure_semantics():
    raw, _ = load_guide()
    replay = build_architecture(raw)
    request = make_request(FROZEN_BRIEF, raw, replay)
    assert request["problem"]["requirements"].splitlines() == FROZEN_BRIEF["requirements"]
    assert request["problem"]["constraints"].splitlines() == FROZEN_BRIEF["constraints"]

    prose = json.dumps(raw, ensure_ascii=False).casefold()
    for phrase in (
        "http range",
        "ftp",
        "source validator",
        "bounded buffer",
        "sha-256",
        "idempotency key",
        "exponential backoff",
        "bandwidth",
        "cross-platform",
        "thread-safe",
        "ssrf",
        "no numeric capacity target",
        "no dedicated external-origin/source node",
    ):
        assert phrase in prose, f"Missing downloader design topic: {phrase}"


def test_guide_does_not_promise_unsupported_numeric_capacity_or_slos():
    raw, _ = load_guide()
    prose = json.dumps(raw, ensure_ascii=False)
    assert not NUMERIC_CAPACITY_PROMISE.search(prose)
