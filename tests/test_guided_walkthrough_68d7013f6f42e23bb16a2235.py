"""Contract and replay checks for the Distributed Cache review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "68d7013f6f42e23bb16a2235"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": PROBLEM_ID,
    "title": "Distributed Cache System",
    "description": "Design a distributed caching system like Redis or Memcached that provides fast data access.",
    "requirements": [
        "Store and retrieve key-value pairs",
        "Distribute data across multiple nodes",
        "Handle node failures gracefully",
        "Support different eviction policies (LRU, LFU, TTL)",
        "Provide high availability and consistency",
        "Support different data types",
        "Handle millions of requests per second",
    ],
    "constraints": [
        "Sub-millisecond response times",
        "Memory-efficient storage",
        "Handle hot keys and uneven load",
        "Minimize data loss during failures",
        "Support both read and write operations",
    ],
    "hints": [
        "Consistent hashing for data distribution",
        "Replication for fault tolerance",
        "Memory management and eviction policies",
        "Client-side load balancing",
        "Monitoring and alerting systems",
    ],
}

STEP_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "decision_point",
    "update_component",
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
ANCHORS = {
    *(f"legacy-requirement:{index}" for index in range(1, 8)),
    *(f"legacy-constraint:{index}" for index in range(1, 6)),
}
ACTION_ANCHOR_EVIDENCE = {
    "legacy-requirement:1": {"cache_02_clients", "cache_07_client_sdk", "cache_08_primary_route", "cache_17_typed_values"},
    "legacy-requirement:2": {"cache_03_router", "cache_08_primary_route", "cache_14_ring_membership", "cache_21_throughput_scale"},
    "legacy-requirement:3": {"cache_05_replicas", "cache_09_replication_path", "cache_15_failover_policy", "cache_22_failure_exercise"},
    "legacy-requirement:4": {"cache_04_primaries", "cache_18_eviction_policy", "cache_20_memory_pressure"},
    "legacy-requirement:5": {"cache_04_primaries", "cache_05_replicas", "cache_09_replication_path", "cache_16_read_write_consistency"},
    "legacy-requirement:6": {"cache_02_clients", "cache_07_client_sdk", "cache_17_typed_values"},
    "legacy-requirement:7": {"cache_02_clients", "cache_06_monitoring", "cache_14_ring_membership", "cache_21_throughput_scale"},
    "legacy-constraint:1": {"cache_04_primaries", "cache_08_primary_route", "cache_21_throughput_scale"},
    "legacy-constraint:2": {"cache_04_primaries", "cache_18_eviction_policy", "cache_20_memory_pressure"},
    "legacy-constraint:3": {"cache_03_router", "cache_06_monitoring", "cache_14_ring_membership", "cache_19_hot_key_policy"},
    "legacy-constraint:4": {"cache_05_replicas", "cache_09_replication_path", "cache_15_failover_policy", "cache_22_failure_exercise"},
    "legacy-constraint:5": {"cache_02_clients", "cache_07_client_sdk", "cache_08_primary_route", "cache_16_read_write_consistency"},
}


def load_raw_and_snapshot():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    snapshot = next(problem for problem in problems if problem["id"] == PROBLEM_ID)
    return raw, snapshot


def catalog_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"Unknown frontend component catalog ID: {component_type}"
    end = catalog.find("\n  },", match.start())
    assert end > match.start(), f"Incomplete catalog definition: {component_type}"
    return catalog[match.start() : end]


def assert_catalog_properties(catalog: str, component_type: str, properties: dict, step_id: str):
    block = catalog_block(catalog, component_type)
    supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
    assert set(properties) <= supported, (
        f"{step_id}: unsupported {component_type} properties "
        f"{sorted(set(properties) - supported)}"
    )

    for key, value in properties.items():
        start = re.search(rf'\{{\s*key:\s*"{re.escape(key)}"', block)
        assert start, f"{step_id}: missing {component_type}.{key} definition"
        end = block.find("},", start.start())
        assert end >= 0, f"{step_id}: incomplete {component_type}.{key} definition"
        field = block[start.start() : end]
        type_match = re.search(r'\btype:\s*"([^"]+)"', field)
        assert type_match, f"{step_id}: {component_type}.{key} has no catalog type"
        field_type = type_match.group(1)

        if field_type == "boolean":
            assert type(value) is bool, f"{step_id}: {key} must be boolean"
        elif field_type == "number":
            assert type(value) in (int, float), f"{step_id}: {key} must be numeric"
        elif field_type in {"text", "textarea"}:
            assert isinstance(value, str), f"{step_id}: {key} must be text"
        elif field_type == "select":
            options = re.search(r"\boptions:\s*\[([^\]]*)\]", field, re.DOTALL)
            assert options, f"{step_id}: {key} has no catalog options"
            allowed = set(re.findall(r'"([^"]+)"', options.group(1)))
            assert value in allowed, f"{step_id}: {key}={value!r} not in {sorted(allowed)}"


def is_actionable(step) -> bool:
    if step.type == "add_component":
        return step.component is not None
    if step.type == "add_connection":
        return step.connection is not None
    if step.type in {"decision_point", "update_component"}:
        return step.componentUpdate is not None and (
            step.type != "decision_point" or step.decision is not None
        )
    if step.type == "scale_trigger":
        return step.scaleTrigger is not None and step.componentUpdate is not None
    return False


def test_frozen_brief_schema_phases_and_actionable_anchor_coverage():
    raw, snapshot = load_raw_and_snapshot()
    snapshot_brief = {key: snapshot[key] for key in FROZEN_BRIEF}
    assert snapshot_brief == FROZEN_BRIEF

    guide = GuidedWalkthrough.model_validate(raw)
    assert set(raw) == {"problem_id", "version", "requirementRevision", "totalSteps", "phases", "steps"}
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 23
    assert [step.stepNumber for step in guide.steps] == list(range(1, 24))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert {step.type for step in guide.steps} == STEP_TYPES
    assert [phase.name for phase in guide.phases] == [
        "Frame the cache contract",
        "Place and route keys",
        "Protect acknowledged data",
        "Control memory and skew",
        "Scale from evidence",
    ]

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step
        assert start <= end <= guide.totalSteps
        assert all(step.phase == phase.name for step in guide.steps[start - 1 : end])
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    for step in guide.steps:
        assert step.title and step.content
        assert set(step.requirementIds) <= ANCHORS
        if step.type == "add_component":
            assert step.component and step.component.label == step.component.properties["componentName"]
            assert set(step.component.position) == {"x", "y"}
        elif step.type == "add_connection":
            assert step.connection
            assert step.connection.connectionType in CONNECTION_TYPES
            assert step.connection.label and step.connection.description
        elif step.type == "decision_point":
            assert step.decision and step.decision.question and step.decision.chosen
            assert step.decision.chosenReason and step.decision.alternatives
            assert all(row.option and row.tradeoff for row in step.decision.alternatives)
        elif step.type == "scale_trigger":
            assert step.scaleTrigger
            assert all((step.scaleTrigger.metric, step.scaleTrigger.action, step.scaleTrigger.impact))
        if step.componentUpdate:
            assert step.componentUpdate.properties

    intro = guide.steps[0].content
    for item in [FROZEN_BRIEF["title"], FROZEN_BRIEF["description"], *FROZEN_BRIEF["requirements"], *FROZEN_BRIEF["constraints"], *FROZEN_BRIEF["hints"]]:
        assert item in intro

    mapped = {anchor for step in guide.steps for anchor in step.requirementIds}
    actionable = {
        anchor
        for step in guide.steps
        if is_actionable(step)
        for anchor in step.requirementIds
    }
    assert mapped == actionable == ANCHORS

    by_id = {step.id: step for step in guide.steps}
    for anchor, evidence_ids in ACTION_ANCHOR_EVIDENCE.items():
        assert evidence_ids <= by_id.keys()
        assert any(
            anchor in by_id[step_id].requirementIds and is_actionable(by_id[step_id])
            for step_id in evidence_ids
        ), f"No concrete action covers {anchor}"

    memory_step = by_id["cache_20_memory_pressure"]
    assert set(memory_step.requirementIds) == {
        "legacy-requirement:4",
        "legacy-constraint:2",
    }


def test_catalog_components_properties_and_ordered_replay_form_one_connected_graph():
    raw, _ = load_raw_and_snapshot()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}
    node_types = {}
    edge_ids = []

    for step in raw["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            assert component["nodeId"] not in components
            assert_catalog_properties(catalog, component["componentType"], component["properties"], step["id"])
            components[component["nodeId"]] = component
            node_types[component["nodeId"]] = component["componentType"]
        if step.get("connection"):
            edge_ids.append(step["connection"]["edgeId"])
        update = step.get("componentUpdate")
        if update:
            assert update["nodeId"] in components, f"{step['id']}: update precedes its component"
            assert_catalog_properties(catalog, node_types[update["nodeId"]], update["properties"], step["id"])

    assert len(components) == len({row["nodeId"] for row in components.values()}) == 5
    assert set(node_types.values()) == {"backend-server", "loadbalancer", "cache", "monitoring"}
    assert len(edge_ids) == len(set(edge_ids)) == 7

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    edges = architecture["connections"]
    assert len(nodes) == len(components)
    assert len(edges) == len(edge_ids)
    modeled_steps = GuidedWalkthrough.model_validate(raw).steps
    assert replay["appliedStepIds"] == [step.id for step in modeled_steps if is_actionable(step)]
    assert replay["explanationOnlyStepIds"] == [
        step.id for step in modeled_steps if not is_actionable(step)
    ]

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] in CONNECTION_TYPES
        assert edge["label"] and edge["description"]
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])

    reached = set()
    pending = deque(["dc_clients"])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    assert reached == set(nodes)


def test_cache_walkthrough_preserves_problem_specific_design_signals():
    raw, _ = load_raw_and_snapshot()
    serialized = json.dumps(raw, ensure_ascii=False).casefold()
    for signal in (
        "consistent hashing",
        "client-side",
        "replication",
        "fencing",
        "read-your-writes",
        "sub-millisecond",
        "millions of requests per second",
        "memory pressure",
        "hot key",
        "request coalescing",
        "lru",
        "lfu",
        "ttl",
        "strings",
        "counters",
        "collections",
        "persistence",
        "acknowledged writes",
    ):
        assert signal in serialized, f"Missing cache design signal: {signal}"

    assert "no numeric alert thresholds" in serialized
    assert "30% headroom" in serialized
    assert "70% scale-out threshold" in serialized
    assert all(component["componentType"] != "custom-component" for step in raw["steps"] if (component := step.get("component")))


def test_applied_canvas_retains_assessment_evidence_not_just_lesson_text():
    raw, _ = load_raw_and_snapshot()
    architecture = build_architecture(raw)["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    clients = nodes["dc_clients"]["properties"]
    router = nodes["dc_router"]["properties"]["purpose"].casefold()
    primaries = nodes["dc_primaries"]["properties"]
    primary_purpose = primaries["purpose"].casefold()
    replicas = nodes["dc_replicas"]["properties"]
    replica_purpose = replicas["purpose"].casefold()

    assert clients["retry"] is True and clients["bulkOps"] is True
    assert all(signal in clients["purpose"].casefold() for signal in (
        "strings/bytes", "counters", "hashes", "collections", "tenant namespaces", "tls"
    ))
    assert all(signal in router for signal in (
        "membership epoch", "read-your-writes", "hot key", "freshness requirement"
    ))
    assert primaries["encryption"] is True
    assert all(signal in primary_purpose for signal in (
        "below one millisecond", "millions of requests per second", "lru or lfu", "ttl", "unreplicated writes"
    ))
    assert replicas["encryption"] is True
    assert all(signal in replica_purpose for signal in (
        "fence", "freshness contract", "acknowledged-but-unreplicated", "zero-loss"
    ))


def test_cache_acceptance_concerns_and_anchor_boundaries_stay_distinct():
    raw, snapshot = load_raw_and_snapshot()
    assert snapshot["has_guided_walkthrough"] is False
    steps = {step["id"]: step for step in raw["steps"]}
    anchors = {step_id: set(step.get("requirementIds", [])) for step_id, step in steps.items()}

    latency = "legacy-constraint:1"
    throughput = "legacy-requirement:7"
    hot_key_skew = "legacy-constraint:3"
    data_loss = "legacy-constraint:4"
    consistency = "legacy-requirement:5"

    throughput_step = steps["cache_21_throughput_scale"]
    throughput_text = " ".join(
        [throughput_step["content"], throughput_step["scaleTrigger"]["metric"], throughput_step["scaleTrigger"]["action"]]
    ).casefold()
    assert latency in anchors["cache_21_throughput_scale"]
    assert throughput in anchors["cache_21_throughput_scale"]
    assert "independent acceptance concerns" in throughput_text
    assert "test request latency and sustained throughput separately" in throughput_text
    assert "choose p99 as the latency acceptance percentile" in throughput_text
    assert "both p99 targets pass" in throughput_text
    assert "unavailable rate" in throughput_text
    assert "target/(0.70 x safe per-shard throughput)" in throughput_text
    assert "70% of tested safe per-shard throughput" in throughput_text

    eviction_text = " ".join(
        [steps["cache_18_eviction_policy"]["content"], steps["cache_18_eviction_policy"]["decision"]["chosen"]]
    ).casefold()
    assert {"legacy-requirement:4", "legacy-constraint:2"} <= anchors["cache_18_eviction_policy"]
    assert all(term in eviction_text for term in ("lru", "lfu", "ttl"))
    assert "separately" in eviction_text and "capacity pressure" in eviction_text
    assert "no cache hit-ratio target" in eviction_text

    hot_key = steps["cache_19_hot_key_policy"]
    hot_key_text = " ".join([hot_key["content"], hot_key["decision"]["chosen"]]).casefold()
    assert hot_key_skew in anchors["cache_19_hot_key_policy"]
    assert throughput not in anchors["cache_19_hot_key_policy"]
    assert "fairness is distinct from aggregate throughput" in hot_key_text
    assert "starves unrelated traffic" in hot_key_text
    assert "deduplicated" in hot_key_text and "deterministic merge" in hot_key_text
    assert "single-key write ceiling" in hot_key_text

    failover_text = " ".join(
        [steps["cache_15_failover_policy"]["content"], steps["cache_15_failover_policy"]["decision"]["chosenReason"]]
    ).casefold()
    consistency_text = " ".join(
        [steps["cache_16_read_write_consistency"]["content"], steps["cache_16_read_write_consistency"]["decision"]["chosen"]]
    ).casefold()
    assert consistency in anchors["cache_15_failover_policy"]
    assert consistency in anchors["cache_16_read_write_consistency"]
    assert latency not in anchors["cache_15_failover_policy"]
    assert data_loss in anchors["cache_15_failover_policy"]
    assert data_loss not in anchors["cache_16_read_write_consistency"]
    assert data_loss not in anchors["cache_20_memory_pressure"]
    assert "write availability" in failover_text
    assert "separately" in failover_text
    assert "names no model" in consistency_text
    assert "read-your-writes as the default" in consistency_text
    assert "explicitly bounded-staleness" in consistency_text
    assert "minority cannot accept protected writes" in consistency_text
    assert "two of three copies" in steps["cache_15_failover_policy"]["decision"]["chosen"].casefold()
    assert "default reads and read-your-writes go to the fenced primary" in steps["cache_10_replica_reads"]["content"].casefold()

    serialized = json.dumps(raw, ensure_ascii=False).casefold()
    assert re.search(r"\b(?:replication|replica) factor\s*(?::|=|of)?\s*\d+\b", serialized) is None
    assert re.search(r"\b(?:failover|recovery)\s+(?:in|within|under)\s+\d+(?:\.\d+)?\s*(?:ms|milliseconds?|s|seconds?|minutes?)\b", serialized) is None
    assert re.search(r"\b(?:cache\s+)?hit[ -]ratio\s*(?::|=|of)?\s*\d+(?:\.\d+)?\s*%?", serialized) is None
    assert "zero loss is guaranteed" not in serialized
