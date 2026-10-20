"""Focused contract for the cloud_gcp_010 intelligent-document review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_gcp_010"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
FROZEN_BRIEFS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"


def load_frozen_brief():
    rows = json.loads(FROZEN_BRIEFS_PATH.read_text(encoding="utf-8"))
    matches = [row for row in rows if row.get("id") == PROBLEM_ID]
    assert len(matches) == 1, f"Expected one frozen brief for {PROBLEM_ID}"
    return matches[0]


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


def catalog_options(block: str, key: str) -> set[str] | None:
    marker = re.search(rf'\bkey:\s*"{re.escape(key)}"', block)
    assert marker, f"catalog property missing: {key}"
    remainder = block[marker.end() :]
    prop_end = re.search(r"\n      },", remainder)
    section = remainder[: prop_end.start()] if prop_end else remainder
    options = re.search(r"options:\s*\[([\s\S]*?)\]", section)
    if not options:
        return None
    return set(re.findall(r'"([^"]+)"', options.group(1)))


def test_frozen_live_brief_and_all_requirement_anchors_are_preserved():
    raw, guide = load_guide()
    brief = load_frozen_brief()
    assert guide.problem_id == PROBLEM_ID
    assert brief["id"] == PROBLEM_ID
    assert guide.version == "1.0-review"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 49

    introduction = raw["steps"][0]["content"]
    assert f"Live brief: {brief['title']}." in introduction
    assert f"Description: {brief['description']}" in introduction
    for heading, field in (
        ("Explicit requirements", "requirements"),
        ("Explicit constraints", "constraints"),
        ("Supplied hints", "hints"),
    ):
        frozen_list = "; ".join(brief[field])
        assert f"{heading}: {frozen_list}." in introduction

    expected_ids = {
        *(f"legacy-requirement:{index}" for index in range(1, len(brief["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(brief["constraints"]) + 1)),
    }
    mapped_ids = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert mapped_ids == expected_ids

    requirement_ids = {
        value: f"legacy-requirement:{index}"
        for index, value in enumerate(brief["requirements"], start=1)
    }
    constraint_ids = {
        value: f"legacy-constraint:{index}"
        for index, value in enumerate(brief["constraints"], start=1)
    }
    concrete_anchors = {
        requirement_ids["Extract text from documents"]: "idp_19_document_ai",
        requirement_ids["Classify document types"]: "idp_19_document_ai",
        requirement_ids["Extract entities and fields"]: "idp_19_document_ai",
        requirement_ids["Process invoices and receipts"]: "idp_19_document_ai",
        requirement_ids["Validate extracted data"]: "idp_21_validation_function",
        requirement_ids["Store structured results"]: "idp_24_firestore_results",
        requirement_ids["Handle various document formats"]: "idp_47_format_and_cost_gate",
        requirement_ids["Monitor processing accuracy"]: "idp_36_bigquery_quality",
        constraint_ids["Processing time under 10 seconds per doc"]: "idp_44_latency_contract",
        constraint_ids["Support 100k+ documents per day"]: "idp_46_capacity_trigger",
        constraint_ids["Extraction accuracy above 95%"]: "idp_45_accuracy_gate",
        constraint_ids["Handle PDFs, images, and scanned docs"]: "idp_19_document_ai",
        constraint_ids["Cost-effective at scale"]: "idp_47_format_and_cost_gate",
    }
    by_id = {step.id: step for step in guide.steps}
    for anchor, step_id in concrete_anchors.items():
        assert anchor in by_id[step_id].requirementIds
        assert by_id[step_id].type != "explanation"


def test_step_order_phases_and_explicit_action_payloads_are_well_formed():
    raw, guide = load_guide()
    assert [step.stepNumber for step in guide.steps] == list(range(1, 50))
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
    assert raw["totalSteps"] == len(raw["steps"])

    allowed = {"explanation", "add_component", "add_connection", "decision_point", "scale_trigger"}
    assert {step.type for step in guide.steps} == allowed
    for step in guide.steps:
        assert step.title and step.content and step.requirementIds
        if step.type == "add_component":
            assert step.component is not None
            assert set(step.component.position) == {"x", "y"}
            assert not step.connection and not step.decision
        elif step.type == "add_connection":
            assert step.connection is not None
            assert step.connection.label and step.connection.description
            assert not step.component and not step.decision
        elif step.type == "decision_point":
            assert step.decision is not None and step.componentUpdate is not None
            assert step.decision.question and step.decision.chosen and step.decision.chosenReason
            assert len(step.decision.alternatives) >= 2
            assert all(option.option and option.tradeoff for option in step.decision.alternatives)
        elif step.type == "scale_trigger":
            assert step.scaleTrigger is not None and step.componentUpdate is not None
            assert step.scaleTrigger.metric and step.scaleTrigger.action and step.scaleTrigger.impact


def test_components_reuse_catalog_ids_and_only_document_ai_is_custom():
    raw, guide = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step.component.nodeId: step.component
        for step in guide.steps
        if step.type == "add_component"
    }
    assert len(additions) == 15
    custom = {
        node_id: component
        for node_id, component in additions.items()
        if component.componentType == "custom-component"
    }
    assert set(custom) == {"idp_document_ai"}
    assert "catalog gap" in custom["idp_document_ai"].properties["componentType"].casefold()
    assert "document ai" in custom["idp_document_ai"].properties["technology"].casefold()

    for step in raw["steps"]:
        component = step.get("component")
        if component:
            node_id = component["nodeId"]
            component_type = component["componentType"]
            properties = component["properties"]
            assert properties["componentName"] == component["label"]
            assert len(properties["purpose"]) >= 45
            assert component["highlightReason"]
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            node_id = update["nodeId"]
            assert node_id in additions
            component_type = additions[node_id].componentType
            properties = update["properties"]
        else:
            continue

        block = catalog_block(catalog, component_type)
        keys = catalog_keys(block)
        assert set(properties) <= keys, (
            f"{step['id']} uses unsupported {component_type} properties: {set(properties) - keys}"
        )
        for key, value in properties.items():
            if isinstance(value, str):
                marker = re.search(rf'\bkey:\s*"{re.escape(key)}"', block)
                if marker and re.search(r"options:\s*\[", block[marker.end() :]):
                    options = catalog_options(block, key)
                    if options is not None:
                        assert value in options, (
                            f"{step['id']} uses unsupported {component_type}.{key} option {value!r}"
                        )


def test_replay_builds_one_connected_end_to_end_pipeline():
    raw, _ = load_guide()
    built = build_architecture(raw)
    architecture = built["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    edges = architecture["connections"]
    assert len(nodes) == 15
    assert len(edges) == 23
    assert len(built["appliedStepIds"]) == 46
    assert len(built["explanationOnlyStepIds"]) == 3
    assert len(built["acceptedDecisions"]) == 7
    assert built["provenance"]["problemId"] == PROBLEM_ID
    assert built["provenance"]["walkthroughVersion"] == "1.0-review"

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] and edge["description"]
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    visited = set()
    pending = deque(["idp_submitter_portal"])
    while pending:
        node_id = pending.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        pending.extend(neighbors[node_id] - visited)
    assert visited == set(nodes)

    edge_pairs = {(edge["source"], edge["target"]) for edge in edges}
    assert {
        ("idp_submitter_portal", "idp_api_gateway"),
        ("idp_identity", "idp_api_gateway"),
        ("idp_api_gateway", "idp_upload_coordinator"),
        ("idp_upload_coordinator", "idp_raw_documents"),
        ("idp_submitter_portal", "idp_raw_documents"),
        ("idp_raw_documents", "idp_processing_events"),
        ("idp_processing_events", "idp_processing_worker"),
        ("idp_processing_worker", "idp_document_ai"),
        ("idp_document_ai", "idp_validate_results"),
        ("idp_validate_results", "idp_structured_results"),
        ("idp_validate_results", "idp_human_review_queue"),
        ("idp_human_review_queue", "idp_reviewer_workspace"),
        ("idp_reviewer_workspace", "idp_api_gateway"),
        ("idp_api_gateway", "idp_validate_results"),
        ("idp_validate_results", "idp_failure_queue"),
        ("idp_failure_queue", "idp_processing_events"),
        ("idp_validate_results", "idp_quality_warehouse"),
        ("idp_quality_warehouse", "idp_pipeline_monitoring"),
        ("idp_structured_results", "idp_api_gateway"),
        ("idp_api_gateway", "idp_submitter_portal"),
    } <= edge_pairs


def test_domain_content_distinguishes_targets_from_measured_evidence():
    brief = load_frozen_brief()
    _, guide = load_guide()
    steps = {step.id: step for step in guide.steps}
    introduction = steps["idp_01_live_brief"].content

    assert brief["constraints"][0] in introduction
    assert brief["constraints"][1] in introduction
    assert brief["constraints"][2] in introduction

    latency = steps["idp_44_latency_contract"].content.casefold()
    assert "does not define percentile, page count, file size" in latency
    assert "provisional acceptance" in latency
    assert "include queue wait/retries" in latency
    assert "do not claim a ten-second guarantee" in latency
    assert "load tests cover that envelope" in latency

    capacity = steps["idp_46_capacity_trigger"].content.casefold()
    assert "1.16 documents/second if arrivals are uniform" in capacity
    assert "peak burst" in capacity and "are not supplied" in capacity
    assert "load-test realistic and burst workloads" in capacity

    accuracy = steps["idp_45_accuracy_gate"]
    assert "representative human-labeled holdout" in accuracy.content.casefold()
    assert "sample counts and confidence intervals" in accuracy.content.casefold()
    assert "exceeds 95%" in accuracy.content.casefold()
    assert "confidence scores and successful http responses are not labels" in (
        accuracy.decision.chosenReason.casefold()
    )

    formats_and_cost = steps["idp_47_format_and_cost_gate"].content.casefold()
    assert "allowlist formats supported by the selected processor" in formats_and_cost
    assert "where that processor supports them" in formats_and_cost
    assert "cost per successfully validated document, including retries and human review" in (
        formats_and_cost
    )

    closeout = steps["idp_48_no_claimed_results"].content.casefold()
    assert "not proof of capacity, latency, cost, or >95% extraction accuracy" in closeout
    assert "publish the measured results with sample coverage" in closeout

