"""Structural, frozen-brief, catalog, and graph checks for the mlops_002 draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "mlops_002"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
ACTION_TYPES = {"add_component", "add_connection", "update_component"}
CONNECTION_TYPES = {
    "api-call", "data-flow", "database-connection", "event-stream",
    "http", "message-queue", "tcp", "websocket",
}


def load_data():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8-sig"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    return raw, problem


def catalog_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match, f"unknown catalog component {component_type!r}"
    end = catalog.find("\n  },", match.start())
    assert end > match.start(), f"incomplete catalog block for {component_type}"
    return catalog[match.start() : end]


def reaches(edges: list[dict], source: str, target: str) -> bool:
    adjacency: dict[str, set[str]] = {}
    for edge in edges:
        adjacency.setdefault(edge["source"], set()).add(edge["target"])
    pending = [source]
    seen = set()
    while pending:
        current = pending.pop()
        if current == target:
            return True
        if current not in seen:
            seen.add(current)
            pending.extend(adjacency.get(current, set()) - seen)
    return False


def test_frozen_brief_schema_phases_and_action_anchor_coverage():
    raw, problem = load_data()
    text = json.dumps(raw, ensure_ascii=False)
    assert problem["has_guided_walkthrough"] is False
    assert raw["problem_id"] == PROBLEM_ID
    assert raw["version"] == "1.0.0-review-draft"
    for key in ("title", "description", "requirements", "constraints", "hints"):
        values = problem[key] if isinstance(problem[key], list) else [problem[key]]
        assert all(value in text for value in values), f"frozen {key} missing from draft"

    guide = GuidedWalkthrough.model_validate(raw)
    assert guide.totalSteps == len(guide.steps) == 44
    assert [step.stepNumber for step in guide.steps] == list(range(1, 45))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert {step.type for step in guide.steps} <= {
        "explanation", "add_component", "add_connection", "decision_point", "scale_trigger"
    }
    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(step.phase == phase.name for step in guide.steps[start - 1 : end])
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    expected = {
        *(f"legacy-requirement:{i}" for i in range(1, len(problem["requirements"]) + 1)),
        *(f"legacy-constraint:{i}" for i in range(1, len(problem["constraints"]) + 1)),
    }
    actual = {anchor for step in raw["steps"] for anchor in step.get("requirementIds", [])}
    action_anchors = {
        anchor for step in raw["steps"] if step["type"] in ACTION_TYPES
        for anchor in step.get("requirementIds", [])
    }
    assert actual == action_anchors == expected


def test_nodes_use_only_catalog_ids_and_supported_typed_properties():
    raw, _ = load_data()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    nodes = {}
    for step in raw["steps"]:
        if step["type"] != "add_component":
            continue
        component = step["component"]
        assert component["nodeId"] not in nodes
        assert set(component["position"]) == {"x", "y"}
        assert all(type(value) in (int, float) for value in component["position"].values())
        properties = component["properties"]
        assert {"componentName", "purpose"} <= set(properties)
        block = catalog_block(catalog, component["componentType"])
        supported = set(re.findall(r'\bkey:\s*"([^\"]+)"', block))
        assert set(properties) <= supported, f"{step['id']}: unsupported properties"
        for key, value in properties.items():
            field_match = re.search(rf'\{{\s*key:\s*"{re.escape(key)}".*?\n\s*\}}', block, re.S)
            assert field_match, f"{step['id']}: missing catalog field {key}"
            field = field_match.group()
            kind = re.search(r'\btype:\s*"([^\"]+)"', field)
            assert kind, f"{step['id']}: untyped catalog field {key}"
            if kind.group(1) == "select":
                options = re.search(r'\boptions:\s*\[([^\]]*)\]', field, re.S)
                assert options and value in re.findall(r'"([^\"]+)"', options.group(1))
            elif kind.group(1) == "number":
                assert type(value) in (int, float)
            elif kind.group(1) == "boolean":
                assert type(value) is bool
            elif kind.group(1) in {"text", "textarea"}:
                assert isinstance(value, str)
        nodes[component["nodeId"]] = component

    assert len(nodes) == 15
    assert nodes["fs_feature_store"]["componentType"] == "feature-store"
    assert nodes["fs_online_cache"]["componentType"] == "cache"
    assert nodes["fs_pit_join"]["componentType"] == "custom-component"


def test_ordered_actions_replay_to_one_dual_store_feature_graph():
    raw, _ = load_data()
    known_nodes = set()
    edge_ids = set()
    for step in sorted(raw["steps"], key=lambda row: row["stepNumber"]):
        if step["type"] == "add_component":
            node_id = step["component"]["nodeId"]
            assert node_id not in known_nodes
            known_nodes.add(node_id)
        elif step["type"] == "add_connection":
            edge = step["connection"]
            assert edge["sourceNodeId"] in known_nodes
            assert edge["targetNodeId"] in known_nodes
            assert edge["sourceNodeId"] != edge["targetNodeId"]
            assert edge["edgeId"] not in edge_ids
            assert edge["connectionType"] in CONNECTION_TYPES
            assert edge["label"].strip() and edge["description"].strip()
            edge_ids.add(edge["edgeId"])

    replay = build_architecture(raw)
    graph = replay["architecture"]
    ids = {node["id"] for node in graph["components"]}
    edges = graph["connections"]
    assert len(ids) == 15 and len(edges) == len(edge_ids) == 23
    neighbors = {node_id: set() for node_id in ids}
    for edge in edges:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["fs_sources"])
    while pending:
        node = pending.popleft()
        if node not in reached:
            reached.add(node)
            pending.extend(neighbors[node] - reached)
    assert reached == ids
    assert len(replay["appliedStepIds"]) == 15 + 23
    assert reaches(edges, "fs_sources", "fs_stream_compute")
    assert reaches(edges, "fs_sources", "fs_batch_compute")
    assert reaches(edges, "fs_transform_contract", "fs_stream_compute")
    assert reaches(edges, "fs_transform_contract", "fs_batch_compute")
    assert reaches(edges, "fs_batch_compute", "fs_feature_store")
    assert reaches(edges, "fs_feature_store", "fs_online_cache")
    assert reaches(edges, "fs_feature_store", "fs_offline_store")
    assert reaches(edges, "fs_offline_store", "fs_pit_join")
    assert reaches(edges, "fs_pit_join", "fs_training")
    assert reaches(edges, "fs_serving", "fs_online_cache")
    assert reaches(edges, "fs_catalog_ui", "fs_metadata_db")


def test_latency_scale_skew_and_backfill_are_targets_to_measure():
    text = json.dumps(load_data()[0], ensure_ascii=False).casefold()
    for phrase in (
        "under 10ms", "100k+ requests/second", "10k+ features", "100+ entities",
        "zero skew", "backfill completion sla", "capacity is not inferred from component properties",
        "not a proven capacity", "golden-record parity", "the brief leaves these unspecified",
    ):
        assert phrase in text
