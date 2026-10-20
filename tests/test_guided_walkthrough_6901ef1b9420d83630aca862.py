"""Frozen-brief and connected replay checks for the key-value review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca862"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
VERSION = "1.0.0-review-draft"
FROZEN_BRIEF = {
    "id": PROBLEM_ID,
    "title": "Design a Key-Value Store",
    "description": "Design a distributed key-value database like DynamoDB or Cassandra.",
    "requirements": [
        "Store and retrieve key-value pairs",
        "Support CRUD operations",
        "Horizontal scalability",
        "High availability and fault tolerance",
        "Configurable consistency levels",
        "Handle billions of records",
        "Support range queries",
    ],
    "constraints": [
        "Low latency reads and writes",
        "Handle node failures automatically",
        "Data should be durable",
        "Support partitioning across nodes",
        "Handle network partitions (CAP theorem)",
    ],
    "hints": [
        "Consistent hashing for data distribution",
        "Replication for availability",
        "Quorum-based consistency",
        "Merkle trees for data synchronization",
        "Gossip protocol for cluster membership",
    ],
}
STEP_TYPES = {"explanation", "add_component", "add_connection", "decision_point", "scale_trigger"}
CONNECTION_TYPES = {"http", "api-call", "database-connection", "message-queue", "data-flow"}


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"{step_id}: unknown catalog ID {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), f"{step_id}: incomplete catalog block for {component_type}"
    return catalog[match.start() : block_end]


def assert_catalog_properties(catalog: str, component_type: str, properties: dict, step_id: str):
    block = catalog_block(catalog, component_type, step_id)
    supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
    assert set(properties) <= supported, (
        f"{step_id}: unsupported {component_type} properties "
        f"{sorted(set(properties) - supported)}"
    )
    for key, value in properties.items():
        field_start = block.index(f'key: "{key}"')
        field_end = block.find("},", field_start)
        assert field_end != -1, f"{step_id}/{key}: incomplete catalog field"
        field = block[field_start:field_end]
        field_type = re.search(r'\btype:\s*"([^"]+)"', field)
        assert field_type is not None, f"{step_id}/{key}: catalog field has no type"
        kind = field_type.group(1)
        if kind in {"text", "textarea"}:
            assert isinstance(value, str), f"{step_id}/{key} must be text"
        elif kind == "boolean":
            assert type(value) is bool, f"{step_id}/{key} must be boolean"
        elif kind == "number":
            assert type(value) in {int, float}, f"{step_id}/{key} must be numeric"
        elif kind == "select":
            options = re.search(r'\boptions:\s*\[([^\]]+)\]', field)
            assert options is not None, f"{step_id}/{key}: select has no options"
            assert value in re.findall(r'"([^"]+)"', options.group(1)), (
                f"{step_id}/{key}: unsupported select value {value!r}"
            )


def test_repository_snapshot_matches_the_exact_frozen_brief():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    snapshot_brief = {
        field: problem[field]
        for field in ("id", "title", "description", "requirements", "constraints", "hints")
    }
    assert snapshot_brief == FROZEN_BRIEF


def test_schema_order_phases_and_actionable_brief_anchors():
    raw, guide = load_guide()
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == VERSION
    assert guide.requirementRevision is None
    assert set(raw) == {"problem_id", "version", "requirementRevision", "totalSteps", "phases", "steps"}
    assert guide.totalSteps == len(guide.steps) == 32
    assert [step.stepNumber for step in guide.steps] == list(range(1, 33))
    assert len({step.id for step in guide.steps}) == 32
    assert {step.type for step in guide.steps} == STEP_TYPES
    assert all(step.title.strip() and step.content.strip() for step in guide.steps)

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end <= guide.totalSteps
        assert all(step.phase == phase.name for step in guide.steps[start - 1 : end])
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    expected = {
        *(f"legacy-requirement:{i}" for i in range(1, len(FROZEN_BRIEF["requirements"]) + 1)),
        *(f"legacy-constraint:{i}" for i in range(1, len(FROZEN_BRIEF["constraints"]) + 1)),
    }
    assert {anchor for step in guide.steps for anchor in step.requirementIds} == expected
    assert all(set(step.requirementIds) <= expected for step in guide.steps)
    by_id = {step.id: step for step in guide.steps}
    anchors = {
        "legacy-requirement:1": "kv_12",
        "legacy-requirement:2": "kv_12",
        "legacy-requirement:3": "kv_11",
        "legacy-requirement:4": "kv_11",
        "legacy-requirement:5": "kv_16",
        "legacy-requirement:6": "kv_31",
        "legacy-requirement:7": "kv_19",
        "legacy-constraint:1": "kv_12",
        "legacy-constraint:2": "kv_14",
        "legacy-constraint:3": "kv_10",
        "legacy-constraint:4": "kv_11",
        "legacy-constraint:5": "kv_16",
    }
    for anchor, step_id in anchors.items():
        step = by_id[step_id]
        assert anchor in step.requirementIds
        assert step.type in {"add_component", "add_connection", "decision_point", "scale_trigger"}
        if step.type == "decision_point":
            assert step.componentUpdate

    availability_anchor = by_id[anchors["legacy-requirement:4"]]
    assert "replication factor of three" in availability_anchor.decision.chosen.casefold()
    assert "independent failure domains" in availability_anchor.decision.chosen.casefold()

    scale_anchor = by_id[anchors["legacy-requirement:6"]]
    assert scale_anchor.type == "scale_trigger"
    assert "total volume" in scale_anchor.content.casefold()
    assert "add capacity" in scale_anchor.scaleTrigger.action.casefold()

    intro = raw["steps"][0]
    for item in [FROZEN_BRIEF["title"], FROZEN_BRIEF["description"], *FROZEN_BRIEF["requirements"],
                 *FROZEN_BRIEF["constraints"], *FROZEN_BRIEF["hints"]]:
        assert item in intro["content"]
    assert "Hints are prompts, not mandates" in intro["content"]
    assert "illustrative quorum examples only" in intro["content"]


def test_unique_ordered_actions_replay_as_one_connected_graph():
    raw, _ = load_guide()
    node_ids, edge_ids, known_nodes = [], [], set()
    for step in raw["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            assert component["nodeId"] not in known_nodes
            assert set(component["position"]) == {"x", "y"}
            assert component["label"] == component["properties"]["componentName"]
            node_ids.append(component["nodeId"])
            known_nodes.add(component["nodeId"])
        elif step["type"] == "add_connection":
            connection = step["connection"]
            assert connection["connectionType"] in CONNECTION_TYPES
            assert connection["sourceNodeId"] in known_nodes
            assert connection["targetNodeId"] in known_nodes
            assert connection["label"].strip() and connection["description"].strip()
            edge_ids.append(connection["edgeId"])
        elif step["type"] == "decision_point":
            decision = step["decision"]
            assert decision["question"].strip() and decision["chosen"].strip()
            assert decision["chosenReason"].strip()
            assert len(decision["alternatives"]) >= 2
            assert all(row["option"].strip() and row["tradeoff"].strip() for row in decision["alternatives"])
            assert step["componentUpdate"]
            assert step["componentUpdate"]["nodeId"] in known_nodes

    assert len(node_ids) == len(set(node_ids)) == 9
    assert len(edge_ids) == len(set(edge_ids)) == 17
    assert not set(node_ids) & set(edge_ids)
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    edges = architecture["connections"]
    assert len(nodes) == 9 and len(edges) == 17
    assert len(replay["appliedStepIds"]) == 29
    assert len(replay["explanationOnlyStepIds"]) == 3
    assert replay["provenance"]["problemId"] == PROBLEM_ID
    assert replay["provenance"]["walkthroughVersion"] == VERSION

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] in CONNECTION_TYPES
        assert edge["label"] and edge["description"]
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached, pending = set(), deque(["kv_client"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == set(nodes)


def test_catalog_ids_and_properties_are_reusable_and_typed():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {s["component"]["nodeId"]: s["component"] for s in raw["steps"] if s.get("component")}

    # Database, backend, worker, broker, gateway, and monitoring roles all have catalog fits;
    # no custom node is needed to express the ring, range index, or Merkle repair behavior.
    assert all(component["componentType"] != "custom-component" for component in components.values())
    for step in raw["steps"]:
        component = step.get("component")
        if component:
            assert len(component["properties"]["purpose"]) >= 70
            assert component["highlightReason"].strip()
            assert_catalog_properties(catalog, component["componentType"], component["properties"], step["id"])
        update = step.get("componentUpdate")
        if update:
            assert update["nodeId"] in components
            assert_catalog_properties(catalog, components[update["nodeId"]]["componentType"], update["properties"], step["id"])


def test_key_value_partition_consistency_range_and_repair_choices():
    raw, _ = load_guide()
    replay = build_architecture(raw)
    nodes = {component["id"]: component for component in replay["architecture"]["components"]}
    decisions = {row["stepId"]: row for row in replay["acceptedDecisions"]}
    content = json.dumps(raw, ensure_ascii=False).casefold()

    assert set(decisions) == {"kv_11", "kv_16", "kv_18"}
    assert "consistent-hash" in decisions["kv_11"]["chosen"].casefold()
    assert "replication factor of three" in decisions["kv_11"]["chosen"].casefold()
    assert "one, quorum, or all" in decisions["kv_16"]["chosen"].casefold()
    assert "r=2 and w=2" in decisions["kv_16"]["chosen"].casefold()
    assert "range-partitioned index" in decisions["kv_18"]["chosen"].casefold()
    assert nodes["kv_primary"]["properties"]["sharding"] == "Hash-based"
    assert nodes["kv_primary"]["properties"]["replication"] == 3
    assert nodes["kv_primary"]["properties"]["replicationMode"] == "Semi-Sync"
    assert nodes["kv_range_index"]["properties"]["sharding"] == "Range-based"
    assert nodes["kv_range_index"]["properties"]["replication"] == 3

    for concept in (
        "put, get, update, and delete", "cap theorem", "tombstone", "merkle trees",
        "gossip protocol", "hinted handoff", "eventually consistent", "freshness watermark", "r+w>n",
    ):
        assert concept in content, f"Missing key-value-store design evidence: {concept}"
