"""Frozen-brief, catalog, replay, and crawler-policy checks for the local draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca864"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": "6901ef1b9420d83630aca864",
    "title": "Design Web Crawler",
    "description": (
        "Design a web crawler that can discover and download billions of web pages efficiently."
    ),
    "requirements": [
        "Crawl billions of web pages",
        "Respect robots.txt and crawl rate limits",
        "Handle different content types (HTML, PDF, images)",
        "Detect and avoid duplicate content",
        "Handle dynamic content (JavaScript)",
        "Prioritize important pages",
        "Distributed crawling architecture",
        "Store crawled data efficiently",
    ],
    "constraints": [
        "Avoid infinite loops and spider traps",
        "Handle network failures and timeouts",
        "Respect website politeness policies",
        "Efficient URL frontier management",
        "Handle billions of URLs",
    ],
    "hints": [
        "URL frontier with priority queue",
        "Bloom filter for duplicate detection",
        "Consistent hashing for URL distribution",
        "DNS caching to reduce latency",
        "Politeness policy per domain",
    ],
}

STEP_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "decision_point",
    "scale_trigger",
}
ACTION_TYPES = {"add_component", "add_connection"}
CONNECTION_TYPES = {
    "http",
    "api-call",
    "database-connection",
    "message-queue",
    "data-flow",
}
EXPECTED_PHASES = [
    ("Define scope and normalize discovery", 1, 6),
    ("Distribute a durable priority frontier", 7, 14),
    ("Gate fetches on policy and origin capacity", 15, 30),
    ("Process, deduplicate, and store content", 31, 45),
    ("Recover and scale by measured pressure", 46, 48),
]


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    return raw, GuidedWalkthrough.model_validate(raw), problem


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"{step_id}: unknown catalog component {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), f"{step_id}: incomplete component catalog entry"
    return catalog[match.start() : block_end]


def assert_supported_properties(catalog: str, component: dict, step_id: str) -> None:
    block = catalog_block(catalog, component["componentType"], step_id)
    supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
    properties = component["properties"]
    assert set(properties) <= supported, (
        f"{step_id}: unsupported {component['componentType']} properties "
        f"{sorted(set(properties) - supported)}"
    )

    for key, value in properties.items():
        field_start = re.search(rf'\{{\s*key:\s*"{re.escape(key)}"', block)
        assert field_start, f"{step_id}: missing catalog property {component['componentType']}.{key}"
        field_end = block.find("},", field_start.start())
        assert field_end > field_start.start(), f"{step_id}: incomplete property {key}"
        field = block[field_start.start() : field_end]
        field_type = re.search(r'\btype:\s*"([^"]+)"', field)
        assert field_type, f"{step_id}: property {component['componentType']}.{key} has no type"
        kind = field_type.group(1)
        if kind in {"text", "textarea"}:
            assert isinstance(value, str), f"{step_id}/{key} must be text"
        elif kind == "boolean":
            assert type(value) is bool, f"{step_id}/{key} must be boolean"
        elif kind == "number":
            assert type(value) in {int, float}, f"{step_id}/{key} must be numeric"
        elif kind == "select":
            options = re.search(r'\boptions:\s*\[([^\]]*)\]', field, re.DOTALL)
            assert options, f"{step_id}/{key}: catalog select options are missing"
            allowed = set(re.findall(r'"([^"]+)"', options.group(1)))
            assert value in allowed, f"{step_id}/{key}: unsupported select option {value!r}"


def test_exact_frozen_brief_schema_and_phase_order():
    raw, guide, problem = load_guide()

    assert {key: problem[key] for key in FROZEN_BRIEF} == FROZEN_BRIEF
    assert problem["has_guided_walkthrough"] is False
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 48
    assert raw["totalSteps"] == len(raw["steps"])
    assert [(phase.name, *phase.stepRange) for phase in guide.phases] == EXPECTED_PHASES
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES for step in guide.steps)
    assert all(step.title.strip() and step.content.strip() for step in guide.steps)

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end <= guide.totalSteps
        assert all(step.phase == phase.name for step in guide.steps[start - 1 : end])
        next_step = end + 1
    assert next_step == guide.totalSteps + 1


def test_every_frozen_requirement_and_constraint_has_an_action_anchor():
    _, guide, _ = load_guide()
    expected = {
        *(f"legacy-requirement:{index}" for index in range(1, 9)),
        *(f"legacy-constraint:{index}" for index in range(1, 6)),
    }
    all_anchors = set()
    action_anchors = set()

    for step in guide.steps:
        anchors = set(step.requirementIds)
        assert len(anchors) == len(step.requirementIds), f"{step.id}: repeated anchor"
        assert anchors <= expected, f"{step.id}: unknown anchors {sorted(anchors - expected)}"
        all_anchors.update(anchors)
        if step.type in ACTION_TYPES:
            action_anchors.update(anchors)

    assert all_anchors == expected
    assert action_anchors == expected


def test_action_anchors_are_specific_to_the_behavior_each_step_implements():
    _, guide, _ = load_guide()
    anchors_by_step = {step.id: set(step.requirementIds) for step in guide.steps}

    assert anchors_by_step["wc_24"] == {
        "legacy-requirement:2",
        "legacy-constraint:3",
    }
    assert anchors_by_step["wc_38"] == {"legacy-requirement:3"}
    assert anchors_by_step["wc_44"] == {
        "legacy-requirement:3",
        "legacy-requirement:8",
    }
    assert anchors_by_step["wc_priority_feedback"] == {
        "legacy-requirement:6",
        "legacy-constraint:4",
    }
    assert anchors_by_step["wc_52"] == {"legacy-requirement:3"}


def test_guide_does_not_invent_numeric_service_level_targets():
    raw, _, _ = load_guide()
    text = json.dumps(raw, ensure_ascii=True)
    numeric_slo = re.compile(
        r"\b(?:p\d{2}|\d+(?:\.\d+)?\s*(?:ms|milliseconds?|seconds?|minutes?|hours?|days?|"
        r"requests?/s|qps|percent|%))(?=$|[^\w])",
        re.IGNORECASE,
    )

    assert numeric_slo.search("p99 latency")
    assert numeric_slo.search("95% availability")
    assert numeric_slo.search("20 ms response-time target")
    assert numeric_slo.search(text) is None


def test_components_use_catalog_ids_and_supported_editable_properties():
    raw, _, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = [
        (step["id"], step["component"])
        for step in raw["steps"]
        if step.get("type") == "add_component"
    ]

    assert components
    assert all(component["componentType"] != "custom-component" for _, component in components), (
        "No custom component is needed because catalog concepts cover this crawler design."
    )
    for step_id, component in components:
        assert set(component["position"]) == {"x", "y"}
        assert all(type(value) in {int, float} for value in component["position"].values())
        assert component["properties"]["componentName"] == component["label"]
        assert len(component["properties"]["purpose"]) >= 70
        assert component["highlightReason"].strip()
        assert_supported_properties(catalog, component, step_id)


def test_actions_replay_in_order_with_valid_edges_and_one_connected_graph():
    raw, guide, _ = load_guide()
    component_steps = {}
    edge_ids = set()
    action_ids = []
    edge_pairs = []

    for step in guide.steps:
        if step.type == "add_component":
            component = step.component
            assert component is not None
            assert component.nodeId not in component_steps
            component_steps[component.nodeId] = component
            action_ids.append(step.id)
        elif step.type == "add_connection":
            connection = step.connection
            assert connection is not None
            assert connection.edgeId not in edge_ids
            assert connection.sourceNodeId in component_steps, (
                f"{step.id}: source must be added before its edge"
            )
            assert connection.targetNodeId in component_steps, (
                f"{step.id}: target must be added before its edge"
            )
            assert connection.connectionType in CONNECTION_TYPES, (
                f"{step.id}: unsupported edge type {connection.connectionType}"
            )
            assert connection.label.strip() and connection.description.strip()
            edge_ids.add(connection.edgeId)
            edge_pairs.append((connection.sourceNodeId, connection.targetNodeId))
            action_ids.append(step.id)

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    replay_nodes = {node["id"] for node in architecture["components"]}
    replay_edges = architecture["connections"]
    assert replay["appliedStepIds"] == action_ids
    assert replay_nodes == set(component_steps)
    assert len(replay_edges) == len(edge_ids)
    assert {edge["id"] for edge in replay_edges} == edge_ids

    neighbors = {node_id: set() for node_id in component_steps}
    for source, target in edge_pairs:
        neighbors[source].add(target)
        neighbors[target].add(source)
    reached = set()
    pending = deque([next(iter(component_steps))])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    assert reached == set(component_steps)


def test_crawler_policy_rate_failure_and_content_paths_are_explicit():
    raw, _, _ = load_guide()
    text = json.dumps(raw, ensure_ascii=True).casefold()
    components = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step.get("type") == "add_component"
    }
    edges = {
        step["connection"]["edgeId"]: (
            step["connection"]["sourceNodeId"],
            step["connection"]["targetNodeId"],
        )
        for step in raw["steps"]
        if step.get("type") == "add_connection"
    }

    for behavior in (
        "robots.txt",
        "shared per-host token",
        "retry-after",
        "crawl-delay",
        "connect timeout",
        "read timeout",
        "bounded exponential backoff",
        "jitter",
        "dead-letter",
        "redirect loop",
        "crawl-budget",
        "false positive",
        "content-type",
        "html",
        "pdf",
        "image",
        "javascript",
        "consistent hashing",
        "billions of urls",
    ):
        assert behavior in text, f"missing crawler behavior: {behavior}"

    assert edges["wc_policy_rate_gate"] == ("wc_robots_policy", "wc_host_rate_gate")
    assert edges["wc_frontier_rate_gate"] == ("wc_frontier", "wc_host_rate_gate")
    assert edges["wc_gate_fetchers"] == ("wc_host_rate_gate", "wc_fetchers")
    assert edges["wc_gate_renderer"] == ("wc_host_rate_gate", "wc_js_renderer")
    assert edges["wc_fetchers_origins"] == ("wc_fetchers", "wc_origins")
    assert edges["wc_renderer_origins"] == ("wc_js_renderer", "wc_origins")
    assert edges["wc_retry_normalizer"] == ("wc_retry_queue", "wc_normalizer")
    assert components["wc_host_rate_gate"]["componentType"] == "rate-limiter"
    assert components["wc_retry_queue"]["componentType"] == "queue"
    assert "false positive" in components["wc_bloom"]["properties"]["purpose"].casefold()

