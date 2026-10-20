"""Frozen-brief, catalog, replay, and P2P safety checks for the BitTorrent review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca87d"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
TITLE = "Create a Distributed File Transfer System like Bittorrent"
DESCRIPTION = "Design a peer-to-peer file sharing system for distributing large files efficiently."
REQUIREMENTS = [
    "Peer-to-peer file distribution",
    "Split files into chunks",
    "Tracker for peer discovery",
    "Support seeding and leeching",
    "Verify chunk integrity",
    "Optimize download from multiple peers",
    "Handle millions of swarms",
    "Resume interrupted downloads",
]
CONSTRAINTS = [
    "Efficient bandwidth utilization",
    "Handle peer churn (joining/leaving)",
    "Prevent malicious peers",
    "Fair resource sharing",
    "Scalable tracker architecture",
]
HINTS = [
    "Chunking and hashing for integrity",
    "Tit-for-tat algorithm for fairness",
    "Distributed hash table for trackerless",
    "Rarest piece first algorithm",
    "Magnet links for metadata",
]
STEP_TYPES = {
    "explanation", "add_component", "add_connection", "decision_point", "scale_trigger",
}
CONNECTION_TYPES = {
    "http", "api-call", "database-connection", "message-queue", "data-flow",
}
ANCHORS = {
    *(f"legacy-requirement:{index}" for index in range(1, len(REQUIREMENTS) + 1)),
    *(f"legacy-constraint:{index}" for index in range(1, len(CONSTRAINTS) + 1)),
}


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def frozen_problem():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def authored_text(raw):
    parts = [step["content"] for step in raw["steps"]]
    parts.extend(
        step["component"]["properties"]["purpose"]
        for step in raw["steps"] if step.get("component")
    )
    parts.extend(
        " ".join(
            [step["decision"]["chosen"], step["decision"]["chosenReason"]]
            + [alternative["tradeoff"] for alternative in step["decision"]["alternatives"]]
        )
        for step in raw["steps"] if step.get("decision")
    )
    parts.extend(
        " ".join((step["connection"]["label"], step["connection"]["description"]))
        for step in raw["steps"] if step.get("connection")
    )
    return " ".join(parts).casefold()


def test_schema_exact_frozen_brief_and_action_anchor_coverage():
    problem = frozen_problem()
    raw, guide = load_guide()

    assert problem["title"] == TITLE
    assert problem["description"] == DESCRIPTION
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert problem["hints"] == HINTS
    assert problem["has_guided_walkthrough"] is False
    assert guide.problem_id == PROBLEM_ID
    assert guide.version.endswith("-review")
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 42
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES and step.content.strip() for step in guide.steps)

    actual_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert actual_anchors == ANCHORS
    graph_actions = [
        step for step in guide.steps
        if step.type in {"add_component", "add_connection", "decision_point"}
    ]
    for anchor in ANCHORS:
        assert any(anchor in step.requirementIds for step in graph_actions), (
            f"{anchor} appears only in lesson text, not a graph action or decision"
        )

    request = make_request(problem, raw, build_architecture(raw))
    assert request["problem"]["title"] == TITLE
    assert request["problem"]["requirements"].splitlines() == REQUIREMENTS
    assert request["problem"]["constraints"].splitlines() == CONSTRAINTS


def test_phase_ranges_and_ordered_replay_form_one_connected_graph():
    raw, guide = load_guide()
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

    assert len(nodes) == 6
    assert len(edges) == 7

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    replay_nodes = {node["id"]: node for node in architecture["components"]}
    replay_edges = {(edge["source"], edge["target"]): edge for edge in architecture["connections"]}
    assert set(replay_nodes) == set(nodes)
    assert len(architecture["connections"]) == len(edges)

    for expected in (
        ("bt_downloader", "bt_tracker_gateway"),
        ("bt_tracker_gateway", "bt_tracker"),
        ("bt_tracker", "bt_swarm_registry"),
        ("bt_tracker", "bt_downloader"),
        ("bt_seeders", "bt_downloader"),
        ("bt_downloader", "bt_seeders"),
        ("bt_tracker", "bt_observability"),
    ):
        assert expected in replay_edges

    neighbors = {node_id: set() for node_id in replay_nodes}
    for edge in architecture["connections"]:
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["bt_downloader"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == set(replay_nodes)


def test_component_catalog_types_properties_and_values_are_supported():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = [step["component"] for step in raw["steps"] if step.get("component")]
    assert len(components) == 6

    for step in raw["steps"]:
        component = step.get("component")
        if not component:
            continue
        assert component["componentType"] != "custom-component"
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
            assert field_type is not None, f"{step['id']}/{key}: missing catalog property type"
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
                    f"{step['id']}/{key}: unsupported select value {value!r}"
                )


def test_walkthrough_covers_integrity_discovery_security_availability_and_privacy():
    raw, _ = load_guide()
    text = authored_text(raw)

    for signal in (
        "infohash", "magnet", "bounded peer sample", "expiring peer lease",
        "seeding", "leeching", "piece blocks", "sha-256", "verified-piece bitmap",
        "rarest-piece-first", "tit-for-tat", "optimistic-unchoke", "resume",
        "malicious peer", "malicious publisher", "quarantine", "no reachable peer",
        "millions of swarms", "hot swarms", "ip address", "anonymity",
        "does not hide", "tracker failure", "fairness", "review draft",
    ):
        assert signal in text, f"missing domain guidance: {signal}"

    assert "does not prove" in text
    assert "no numerical slo or capacity guarantee" in text
