"""Focused structural contract for the cloud_gcp_009 contact-center review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_gcp_009"
TITLE = "Design an AI-Powered Contact Center Solution"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

DESCRIPTION = (
    "Design a contact center that handles voice and text conversations, provides "
    "conversational AI, transcribes speech, and analyzes customer sentiment."
)
REQUIREMENTS = [
    "Implement virtual agents",
    "Transcribe customer calls",
    "Analyze conversation sentiment",
    "Provide agent assistance",
    "Detect customer intent",
    "Route calls intelligently",
    "Generate conversation insights",
    "Monitor agent performance",
]
CONSTRAINTS = [
    "Response latency under 2 seconds",
    "Support 10k+ concurrent calls",
    "Transcription accuracy above 95%",
    "Intent recognition accuracy above 90%",
    "Reduce call handling time by 30%",
]
HINTS = [
    "Contact Center AI for platform",
    "Dialogflow for conversational AI",
    "Speech-to-Text for transcription",
    "Text-to-Speech for responses",
    "Natural Language API for sentiment",
    "BigQuery for analytics",
]


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def load_frozen_problem():
    problems = json.loads(PROBLEMS_FIXTURE_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def catalog_block(catalog: str, component_type: str) -> str:
    match = re.search(
        rf'(?m)^    id:\s*"{re.escape(component_type)}"', catalog
    )
    assert match, f"unknown catalog component type: {component_type}"
    end = catalog.find("\n  },", match.start())
    assert end > match.start(), f"could not bound catalog definition: {component_type}"
    return catalog[match.start() : end]


def catalog_keys(block: str) -> set[str]:
    return set(re.findall(r'\bkey:\s*"([^"]+)"', block))


def catalog_options(block: str, key: str) -> set[str]:
    marker = re.search(rf'\bkey:\s*"{re.escape(key)}"', block)
    assert marker, f"catalog property missing: {key}"
    prop_end = re.search(r"\n      },", block[marker.end() :])
    section = block[marker.end() : marker.end() + prop_end.start()] if prop_end else block[marker.end() :]
    options = re.search(r"options:\s*\[([\s\S]*?)\]", section)
    assert options, f"{key} is not a catalog select property"
    return set(re.findall(r'"([^"]+)"', options.group(1)))


def test_schema_step_order_phase_ranges_and_action_ids():
    raw, guide = load_guide()
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0-review"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 61
    assert [step.stepNumber for step in guide.steps] == list(range(1, 62))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert len({phase.name for phase in guide.phases}) == len(guide.phases)

    expected_start = 1
    for phase in guide.phases:
        assert len(phase.stepRange) == 2
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
    component_ids = []
    connection_ids = []
    for step in guide.steps:
        assert step.title and step.content and step.requirementIds
        if step.type == "add_component":
            assert step.component is not None
            assert step.component.position.keys() == {"x", "y"}
            component_ids.append(step.component.nodeId)
            assert not step.connection and not step.decision
        elif step.type == "add_connection":
            assert step.connection is not None
            assert step.connection.label and step.connection.description
            connection_ids.append(step.connection.edgeId)
            assert not step.component and not step.decision
        elif step.type == "decision_point":
            assert step.decision is not None and step.componentUpdate is not None
            assert step.decision.question and step.decision.chosen and step.decision.chosenReason
            assert len(step.decision.alternatives) >= 2
            assert all(option.option and option.tradeoff for option in step.decision.alternatives)
        elif step.type == "scale_trigger":
            assert step.scaleTrigger is not None and step.componentUpdate is not None
            assert step.scaleTrigger.metric and step.scaleTrigger.action and step.scaleTrigger.impact
        else:
            assert step.component is None and step.connection is None

    assert len(component_ids) == len(set(component_ids)) == 18
    assert len(connection_ids) == len(set(connection_ids)) == 34
    assert raw["totalSteps"] == len(raw["steps"])


def test_all_supplied_legacy_anchors_are_mapped_to_specific_actions():
    _, guide = load_guide()
    expected_ids = {
        *(f"legacy-requirement:{index}" for index in range(1, len(REQUIREMENTS) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(CONSTRAINTS) + 1)),
    }
    mapped_ids = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert mapped_ids == expected_ids

    # Each item from the supplied live brief has a concrete non-intro action.
    anchor_actions = {
        "legacy-requirement:1": "contact_10_google_contact_ai",
        "legacy-requirement:2": "contact_10_google_contact_ai",
        "legacy-requirement:3": "contact_10_google_contact_ai",
        "legacy-requirement:4": "contact_10_google_contact_ai",
        "legacy-requirement:5": "contact_10_google_contact_ai",
        "legacy-requirement:6": "contact_06_orchestrator",
        "legacy-requirement:7": "contact_17_warehouse",
        "legacy-requirement:8": "contact_19_monitoring",
        "legacy-constraint:1": "contact_52_latency_budget",
        "legacy-constraint:2": "contact_57_call_capacity_trigger",
        "legacy-constraint:3": "contact_53_model_quality_gate",
        "legacy-constraint:4": "contact_53_model_quality_gate",
        "legacy-constraint:5": "contact_56_handling_time_measurement",
    }
    by_id = {step.id: step for step in guide.steps}
    for anchor, step_id in anchor_actions.items():
        assert anchor in by_id[step_id].requirementIds
        assert by_id[step_id].type != "explanation"

    assert len(REQUIREMENTS) == 8 and len(CONSTRAINTS) == 5


def test_guide_is_compared_with_the_exact_frozen_problem_brief():
    problem = load_frozen_problem()
    assert problem["id"] == PROBLEM_ID
    assert problem["title"] == TITLE
    assert problem["description"] == DESCRIPTION
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert problem["hints"] == HINTS


def test_five_nonfunctional_targets_have_distinct_unverified_metric_gates():
    _, guide = load_guide()
    by_id = {step.id: step for step in guide.steps}
    constraint_ids = {f"legacy-constraint:{index}" for index in range(1, 6)}

    metric_gates = {
        "contact_52_latency_budget": {"legacy-constraint:1"},
        "contact_57_call_capacity_trigger": {"legacy-constraint:2"},
        "contact_53_model_quality_gate": {
            "legacy-constraint:3",
            "legacy-constraint:4",
        },
        "contact_56_handling_time_measurement": {"legacy-constraint:5"},
    }
    for step_id, expected_constraints in metric_gates.items():
        assert set(by_id[step_id].requirementIds) & constraint_ids == expected_constraints

    speech_intent_telemetry = by_id["contact_45_ai_quality_telemetry"]
    assert set(speech_intent_telemetry.requirementIds) & constraint_ids == {
        "legacy-constraint:3",
        "legacy-constraint:4",
    }
    assert set(speech_intent_telemetry.requirementIds) & {
        "legacy-requirement:2",
        "legacy-requirement:5",
    } == {"legacy-requirement:2", "legacy-requirement:5"}

    latency = by_id["contact_52_latency_budget"].content.casefold()
    capacity_step = by_id["contact_57_call_capacity_trigger"]
    capacity = " ".join(
        (capacity_step.content, capacity_step.scaleTrigger.impact)
    ).casefold()
    quality = by_id["contact_53_model_quality_gate"].content.casefold()
    handling = by_id["contact_56_handling_time_measurement"].content.casefold()
    assert "under 2 seconds" in latency and "does not define percentile" in latency
    assert "10,000 concurrent calls" in capacity and "remains unverified" in capacity
    assert "transcription accuracy must exceed 95%" in quality
    assert "intent-recognition accuracy must exceed 90%" in quality
    assert "independent gates" in quality and "not measured results" in quality
    assert "30% reduction" in handling and "not attributable" in handling

    # Handling-time reduction belongs on outcome analytics, not agent controls
    # or generic event/backlog processing. None of the targets is a result claim.
    for step_id in (
        "contact_15_insights_worker",
        "contact_17_warehouse",
        "contact_19_monitoring",
        "contact_39_bigquery_outputs",
        "contact_49_agent_outcome_telemetry",
        "contact_56_handling_time_measurement",
    ):
        assert "legacy-constraint:5" in by_id[step_id].requirementIds
    for step_id in (
        "contact_11_agent_desktop",
        "contact_31_agent_commands",
        "contact_47_event_telemetry",
        "contact_48_worker_telemetry",
        "contact_58_backlog_trigger",
    ):
        assert "legacy-constraint:5" not in by_id[step_id].requirementIds


def test_only_catalog_components_properties_and_select_values_are_used():
    raw, guide = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step.component.nodeId: step.component
        for step in guide.steps
        if step.type == "add_component"
    }
    assert len(additions) == 18
    custom_ids = {
        node_id
        for node_id, component in additions.items()
        if component.componentType == "custom-component"
    }
    assert custom_ids == {"cc_channels", "cc_google_ai"}
    assert "catalog gap" in additions["cc_channels"].properties["componentType"].casefold()
    assert "catalog gap" in additions["cc_google_ai"].properties["componentType"].casefold()

    for step in raw["steps"]:
        component = step.get("component")
        if component:
            node_id = component["nodeId"]
            component_type = component["componentType"]
            properties = component["properties"]
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            node_id = update["nodeId"]
            component_type = additions[node_id].componentType
            properties = update["properties"]
        else:
            continue

        block = catalog_block(catalog, component_type)
        assert set(properties) <= catalog_keys(block), (
            f"{step['id']} uses unsupported properties: {set(properties) - catalog_keys(block)}"
        )
        if component:
            assert properties["componentName"] == component["label"]
            assert len(properties["purpose"]) >= 45
            assert component["highlightReason"]

    select_values = {
        "cc_ingress": ("type", "Global"),
        "cc_api": ("authentication", "OAuth 2.0"),
        "cc_auth": ("sessions", "redis"),
        "cc_limiter": ("algorithm", "Token Bucket"),
        "cc_limiter_backend": ("backend", "Redis"),
        "cc_ai_gateway": ("platform", "Custom"),
        "cc_agent_ui": ("framework", "React"),
        "cc_presence": ("engine", "redis"),
        "cc_presence_strategy": ("cacheStrategy", "cache-aside"),
        "cc_state": ("type", "NoSQL"),
        "cc_state_replication": ("replicationMode", "Sync"),
        "cc_archive": ("provider", "GCS"),
        "cc_warehouse": ("platform", "BigQuery"),
        "cc_retry": ("backoff", "exponential"),
        "cc_monitoring": ("stack", "Prometheus + Grafana"),
    }
    option_components = {
        "cc_ingress": "loadbalancer",
        "cc_api": "api-gateway",
        "cc_auth": "auth-service",
        "cc_limiter": "rate-limiter",
        "cc_limiter_backend": "rate-limiter",
        "cc_ai_gateway": "ai-gateway",
        "cc_agent_ui": "web-app",
        "cc_presence": "cache",
        "cc_presence_strategy": "cache",
        "cc_state": "database",
        "cc_state_replication": "database",
        "cc_archive": "object-storage",
        "cc_warehouse": "data-warehouse",
        "cc_retry": "queue",
        "cc_monitoring": "monitoring",
    }
    for key, (property_name, value) in select_values.items():
        block = catalog_block(catalog, option_components[key])
        assert value in catalog_options(block, property_name), (key, property_name, value)


def test_ordered_replay_builds_the_complete_connected_contact_center_graph():
    raw, _ = load_guide()
    built = build_architecture(raw)
    architecture = built["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    edges = architecture["connections"]
    assert len(nodes) == 18
    assert len(edges) == 34
    assert len(built["appliedStepIds"]) == 59
    assert len(built["explanationOnlyStepIds"]) == 2
    assert len(built["acceptedDecisions"]) == 5
    assert built["provenance"]["problemId"] == PROBLEM_ID
    assert built["provenance"]["walkthroughVersion"] == "1.0-review"

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] and edge["description"]
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    visited = set()
    pending = deque(["cc_channels"])
    while pending:
        node_id = pending.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        pending.extend(neighbors[node_id] - visited)
    assert visited == set(nodes)

    edge_pairs = {(edge["source"], edge["target"]) for edge in edges}
    assert {
        ("cc_channels", "cc_ingress"),
        ("cc_ingress", "cc_api"),
        ("cc_api", "cc_auth"),
        ("cc_auth", "cc_api"),
        ("cc_api", "cc_orchestrator"),
        ("cc_api", "cc_limiter"),
        ("cc_limiter", "cc_orchestrator"),
        ("cc_channels", "cc_google_ai"),
        ("cc_orchestrator", "cc_ai_gateway"),
        ("cc_ai_gateway", "cc_breaker"),
        ("cc_breaker", "cc_google_ai"),
        ("cc_google_ai", "cc_orchestrator"),
        ("cc_orchestrator", "cc_agent_ui"),
        ("cc_agent_ui", "cc_api"),
        ("cc_orchestrator", "cc_presence"),
        ("cc_orchestrator", "cc_state"),
        ("cc_orchestrator", "cc_events"),
        ("cc_events", "cc_worker"),
        ("cc_worker", "cc_archive"),
        ("cc_worker", "cc_warehouse"),
        ("cc_worker", "cc_retry"),
        ("cc_retry", "cc_worker"),
    } <= edge_pairs

    assert nodes["cc_state"]["properties"]["replicationMode"] == "Sync"
    assert nodes["cc_presence"]["properties"]["ttl"] == 5
    assert nodes["cc_ai_gateway"]["properties"]["caching"] is False
    assert nodes["cc_worker"]["properties"]["autoscale"] is True
    assert nodes["cc_archive"]["properties"]["provider"] == "GCS"
    assert nodes["cc_warehouse"]["properties"]["platform"] == "BigQuery"


def test_domain_specific_content_distinguishes_targets_from_proven_results():
    raw, _ = load_guide()
    lesson = json.dumps(raw, ensure_ascii=False).casefold()
    for evidence in (
        "brief facts",
        "provisional design assumptions",
        "contact center ai",
        "dialogflow cx",
        "speech-to-text",
        "text-to-speech",
        "natural language api",
        "bigquery",
        "partial transcript",
        "human handoff",
        "idempotency",
        "outbox",
        "dead-letter",
        "replay",
        "consent",
        "least privilege",
        "10,000 concurrent",
        "95%",
        "90%",
        "30%",
        "after-call work",
        "case mix",
        "load-test",
        "no browser replay, ai assessment gate, publication",
        "voice and text",
        "virtual-agent",
        "streaming speech-to-text",
        "sentiment",
        "agent-assist",
        "intent detection",
        "routing",
        "conversation insights",
        "agent performance",
    ):
        assert evidence in lesson, f"missing domain-specific guidance: {evidence}"
    assert all(hint.split(" for ")[0].casefold() in lesson for hint in HINTS)

