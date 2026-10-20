"""Frozen-brief, catalog, problem-signal, and replay checks for the typeahead review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca85e"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": PROBLEM_ID,
    "title": "Design Typeahead Suggestion/Autocomplete",
    "description": "Design an autocomplete system that provides real-time search suggestions as users type.",
    "requirements": [
        "Provide suggestions as user types",
        "Return top N most relevant suggestions",
        "Support fuzzy matching and typo tolerance",
        "Personalized suggestions based on user history",
        "Update suggestions in real-time",
        "Handle billions of queries per day",
        "Support multiple languages",
    ],
    "constraints": [
        "Ultra-low latency (<100ms)",
        "High throughput for read operations",
        "Suggestions should be relevant and ranked",
        "Handle partial queries efficiently",
        "Memory-efficient data structures",
    ],
    "hints": [
        "Trie data structure for prefix matching",
        "Cache popular queries",
        "Precompute top suggestions",
        "Use machine learning for ranking",
        "Distributed trie across multiple servers",
    ],
}
STEP_TYPES = {"explanation", "add_component", "add_connection", "decision_point", "scale_trigger"}
CONNECTION_TYPES = {"http", "api-call", "database-connection", "message-queue", "data-flow"}
ACTION_TYPES = {"add_component", "add_connection"}
EXPECTED_ANCHOR_STEPS = {
    "legacy-requirement:1": {
        "ta_02_client", "ta_03_gateway", "ta_04_read_api", "ta_prefix_index",
        "ta_09_client_gateway", "ta_10_gateway_api", "ta_12_api_index",
        "ta_17_api_client", "ta_35_scale_latency",
    },
    "legacy-requirement:2": {
        "ta_02_client", "ta_04_read_api", "ta_05_prefix_cache", "ta_prefix_index",
        "ta_ranker", "ta_09_client_gateway", "ta_11_api_cache", "ta_12_api_index",
        "ta_14_api_ranker", "ta_15_index_ranker", "ta_16_ranker_api",
        "ta_17_api_client", "ta_33_memory_tradeoff", "ta_35_scale_latency",
    },
    "legacy-requirement:3": {
        "ta_prefix_index", "ta_ranker", "ta_12_api_index", "ta_14_api_ranker",
        "ta_15_index_ranker", "ta_16_ranker_api", "ta_31_fuzzy_tradeoff",
        "ta_35_scale_latency",
    },
    "legacy-requirement:4": {
        "ta_02_client", "ta_ranker", "ta_08_profile_store", "ta_13_api_history",
        "ta_14_api_ranker", "ta_20_event_stream", "ta_25_api_events",
        "ta_21_indexer", "ta_26_events_indexer", "ta_29_indexer_history",
        "ta_35_scale_latency",
    },
    "legacy-requirement:5": {
        "ta_18_catalog_writer", "ta_19_catalog_store", "ta_20_event_stream",
        "ta_21_indexer", "ta_22_gateway_writer", "ta_23_writer_catalog",
        "ta_24_writer_events", "ta_25_api_events", "ta_26_events_indexer",
        "ta_27_indexer_index", "ta_28_indexer_cache", "ta_30_indexer_catalog",
    },
    "legacy-requirement:6": {
        "ta_03_gateway", "ta_04_read_api", "ta_05_prefix_cache", "ta_prefix_index",
        "ta_ranker", "ta_08_profile_store", "ta_09_client_gateway", "ta_10_gateway_api",
        "ta_11_api_cache", "ta_12_api_index", "ta_13_api_history", "ta_14_api_ranker",
        "ta_15_index_ranker", "ta_16_ranker_api", "ta_17_api_client",
        "ta_34_scale_throughput",
    },
    "legacy-requirement:7": {
        "ta_02_client", "ta_03_gateway", "ta_04_read_api", "ta_05_prefix_cache",
        "ta_prefix_index", "ta_09_client_gateway", "ta_11_api_cache", "ta_12_api_index",
        "ta_14_api_ranker", "ta_15_index_ranker", "ta_ranker", "ta_17_api_client",
        "ta_19_catalog_store", "ta_21_indexer", "ta_24_writer_events",
        "ta_27_indexer_index", "ta_32_locale_tradeoff",
    },
    "legacy-constraint:1": {
        "ta_02_client", "ta_03_gateway", "ta_04_read_api", "ta_05_prefix_cache",
        "ta_prefix_index", "ta_ranker", "ta_08_profile_store", "ta_09_client_gateway",
        "ta_10_gateway_api", "ta_11_api_cache", "ta_12_api_index", "ta_13_api_history",
        "ta_14_api_ranker", "ta_15_index_ranker", "ta_16_ranker_api",
        "ta_17_api_client", "ta_20_event_stream", "ta_25_api_events",
        "ta_31_fuzzy_tradeoff", "ta_35_scale_latency",
    },
    "legacy-constraint:2": {
        "ta_03_gateway", "ta_04_read_api", "ta_05_prefix_cache", "ta_prefix_index",
        "ta_ranker", "ta_08_profile_store", "ta_09_client_gateway", "ta_10_gateway_api",
        "ta_11_api_cache", "ta_12_api_index", "ta_13_api_history", "ta_14_api_ranker",
        "ta_15_index_ranker", "ta_16_ranker_api", "ta_17_api_client",
        "ta_33_memory_tradeoff", "ta_34_scale_throughput",
    },
    "legacy-constraint:3": {
        "ta_04_read_api", "ta_05_prefix_cache", "ta_prefix_index", "ta_ranker",
        "ta_08_profile_store", "ta_11_api_cache", "ta_12_api_index", "ta_13_api_history",
        "ta_14_api_ranker", "ta_15_index_ranker", "ta_16_ranker_api",
        "ta_17_api_client", "ta_29_indexer_history", "ta_32_locale_tradeoff",
    },
    "legacy-constraint:4": {
        "ta_04_read_api", "ta_05_prefix_cache", "ta_prefix_index", "ta_11_api_cache",
        "ta_12_api_index", "ta_31_fuzzy_tradeoff", "ta_32_locale_tradeoff",
        "ta_35_scale_latency",
    },
    "legacy-constraint:5": {
        "ta_05_prefix_cache", "ta_prefix_index", "ta_08_profile_store",
        "ta_12_api_index", "ta_13_api_history", "ta_29_indexer_history",
        "ta_33_memory_tradeoff",
    },
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

    assert {field: problem[field] for field in FROZEN_BRIEF} == FROZEN_BRIEF
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 36
    assert set(raw) == {"problem_id", "version", "requirementRevision", "totalSteps", "phases", "steps"}
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES and step.content.strip() for step in guide.steps)

    expected_anchors = {
        *(f"legacy-requirement:{index}" for index in range(1, len(FROZEN_BRIEF["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(FROZEN_BRIEF["constraints"]) + 1)),
    }
    actual_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert actual_anchors == expected_anchors
    for anchor in expected_anchors:
        assert any(anchor in step.requirementIds and step.type in ACTION_TYPES for step in guide.steps), (
            f"{anchor} is only described, not tied to an actionable component or connection"
        )

    replay = build_architecture(raw)
    request = make_request(problem, raw, replay)
    assert request["problem"]["id"] == FROZEN_BRIEF["id"]
    assert request["problem"]["title"] == FROZEN_BRIEF["title"]
    assert request["problem"]["description"] == FROZEN_BRIEF["description"]
    assert request["problem"]["requirements"].splitlines() == FROZEN_BRIEF["requirements"]
    assert request["problem"]["constraints"].splitlines() == FROZEN_BRIEF["constraints"]


def test_frozen_requirement_and_constraint_anchors_match_exact_steps():
    raw, _ = load_guide()
    actual = {anchor: set() for anchor in EXPECTED_ANCHOR_STEPS}
    for step in raw["steps"]:
        for anchor in step.get("requirementIds", []):
            actual.setdefault(anchor, set()).add(step["id"])

    assert actual == EXPECTED_ANCHOR_STEPS


def test_phases_ordered_actions_and_connected_replay():
    raw, guide = load_guide()
    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    node_ids = set()
    edge_ids = set()
    for step in guide.steps:
        if step.type == "add_component":
            assert step.component is not None
            component = step.component
            assert component.nodeId not in node_ids
            assert component.position.keys() >= {"x", "y"}
            node_ids.add(component.nodeId)
        elif step.type == "add_connection":
            assert step.connection is not None
            connection = step.connection
            assert connection.edgeId not in edge_ids
            assert connection.connectionType in CONNECTION_TYPES
            assert {connection.sourceNodeId, connection.targetNodeId} <= node_ids
            edge_ids.add(connection.edgeId)
        if step.componentUpdate is not None:
            assert step.componentUpdate.nodeId in node_ids

    assert len(node_ids) == 11
    assert len(edge_ids) == 18

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    replayed_nodes = {node["id"] for node in architecture["components"]}
    neighbors = {node_id: set() for node_id in replayed_nodes}
    for edge in architecture["connections"]:
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["ta_client"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == replayed_nodes
    assert len(replay["appliedStepIds"]) + len(replay["explanationOnlyStepIds"]) == guide.totalSteps


def test_existing_catalog_ids_and_supported_properties():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"] if step.get("component")
    }
    assert additions
    assert all(component["componentType"] != "custom-component" for component in additions.values())

    for step in raw["steps"]:
        component = step.get("component")
        if component:
            component_type = component["componentType"]
            properties = component["properties"]
            assert properties["componentName"] == component["label"]
            assert len(properties["purpose"]) >= 70
            assert component["highlightReason"]
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            component_type = additions[update["nodeId"]]["componentType"]
            properties = update["properties"]
        else:
            continue

        match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
        assert match is not None, f"{step['id']}: unknown catalog ID {component_type}"
        block_end = catalog.find("\n  },", match.start())
        assert block_end != -1
        component_block = catalog[match.start():block_end]
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', component_block))
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
                    f"{step['id']}/{key}: {value!r} is not a supported catalog option"
                )


def test_replay_preserves_typeahead_specific_design_signals():
    raw, _ = load_guide()
    replay = build_architecture(raw)
    nodes = {node["id"]: node for node in replay["architecture"]["components"]}
    purposes = {node_id: node["properties"]["purpose"].casefold() for node_id, node in nodes.items()}
    all_prose = " ".join(
        [step["title"] + " " + step["content"] for step in raw["steps"]]
        + [component["properties"]["purpose"] for step in raw["steps"]
           if (component := step.get("component"))]
        + [str(step.get("decision", {})) for step in raw["steps"]]
    ).casefold()

    assert "trie" in purposes["ta_prefix_index"] or "trie" in all_prose
    assert "fuzzy" in purposes["ta_prefix_index"] and "typo" in purposes["ta_prefix_index"]
    assert "precomputed" in purposes["ta_prefix_cache"]
    assert "popular" in purposes["ta_prefix_cache"]
    assert "top n" in purposes["ta_ranker"]
    assert "machine-learning" in all_prose or "machine learning" in all_prose
    assert "user-history" in purposes["ta_ranker"] or "user history" in purposes["ta_ranker"]
    assert "real-time" in all_prose
    assert "billions of queries per day" in all_prose
    assert "multiple languages" in all_prose and "locale" in purposes["ta_prefix_index"]
    assert "<100ms" in all_prose
    assert "assume" in all_prose and "unspecified" in all_prose

    measured_targets = re.findall(
        r"\b\d+(?:\.\d+)?\s*(?:ms|milliseconds?|seconds?|minutes?|hours?|days?|rps|qps)\b",
        all_prose,
    )
    assert {re.sub(r"\s+", "", value) for value in measured_targets} <= {"100ms"}
    numeric_thresholds = re.findall(
        r"(?<!\w)(?:<=|>=|<|>)\s*\d+(?:\.\d+)?\s*[a-zA-Z%/]+",
        all_prose,
    )
    assert {re.sub(r"\s+", "", value).casefold() for value in numeric_thresholds} == {"<100ms"}
