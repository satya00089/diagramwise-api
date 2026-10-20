"""Focused structural, catalog, brief-fidelity, and safety checks for ai_009."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "ai_009"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

TITLE = "Design an AI-Powered Medical Diagnosis Assistant"
SLUG = "design-an-ai-powered-medical-diagnosis-assistant"
DESCRIPTION = (
    "Design an AI system that assists clinicians with medical image analysis, "
    "symptom assessment, and diagnostic suggestions, with explainable AI and "
    "compliance with healthcare regulations."
)
REQUIREMENTS = [
    "Analyze medical images (X-rays, MRIs, CT scans)",
    "Assess patient symptoms and history",
    "Provide differential diagnosis suggestions",
    "Explain AI reasoning to clinicians",
    "Integrate with Electronic Health Records (EHR)",
    "Support clinical decision support workflows",
    "Track and audit all AI recommendations",
    "Handle patient data privacy and consent",
]
CONSTRAINTS = [
    "Diagnostic accuracy above 95% for supported conditions",
    "Image analysis latency under 5 seconds",
    "HIPAA and GDPR compliant",
    "FDA/CE regulatory requirements",
    "Zero tolerance for critical missed diagnoses",
]
HINTS = [
    "Use specialized vision models for medical imaging",
    "Implement DICOM-compatible image processing pipelines",
    "Use FHIR standards for EHR integration",
    "Implement Grad-CAM or attention maps for explainability",
    "Deploy with on-premises option for data sovereignty",
    "Use federated learning for multi-hospital training",
]
COMPANIES = ["Google Health", "IBM Watson Health", "Tempus", "PathAI"]
ANCHORS = {
    *(f"legacy-requirement:{index}" for index in range(1, len(REQUIREMENTS) + 1)),
    *(f"legacy-constraint:{index}" for index in range(1, len(CONSTRAINTS) + 1)),
}
ACTION_TYPES = {"add_component", "add_connection", "update_component"}
CONNECTION_TYPES = {
    "api-call",
    "data-flow",
    "database-connection",
    "https",
    "message-queue",
}


def load_guide_and_problem():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    return raw, problem


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"{step_id}: unknown catalog component {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), (
        f"{step_id}: incomplete catalog definition for {component_type}"
    )
    return catalog[match.start() : block_end]


def test_exact_frozen_brief_and_existing_walkthrough_schema():
    raw, problem = load_guide_and_problem()

    assert problem["slug"] == SLUG
    assert problem["title"] == TITLE
    assert problem["description"] == DESCRIPTION
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert problem["hints"] == HINTS
    assert problem["companies"] == COMPANIES
    assert problem["has_guided_walkthrough"] is False

    guide = GuidedWalkthrough.model_validate(raw)
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 42


def test_phase_order_brief_fidelity_and_action_anchor_coverage():
    raw, _ = load_guide_and_problem()
    guide = GuidedWalkthrough.model_validate(raw)

    assert [step.stepNumber for step in guide.steps] == list(range(1, 43))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.id and step.title and step.content for step in guide.steps)

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert len(phase.stepRange) == 2
        assert start == next_step
        assert start <= end <= guide.totalSteps
        assert all(step.phase == phase.name for step in guide.steps[start - 1 : end])
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    opening = guide.steps[0].content
    for supplied_fact in [TITLE, DESCRIPTION, *REQUIREMENTS, *CONSTRAINTS, *HINTS, *COMPANIES]:
        assert supplied_fact in opening

    mapped = {anchor for step in guide.steps for anchor in step.requirementIds}
    action_mapped = {
        anchor
        for step in guide.steps
        if step.type in ACTION_TYPES
        for anchor in step.requirementIds
    }
    assert mapped == action_mapped == ANCHORS
    assert all(set(step.requirementIds) <= ANCHORS for step in guide.steps)


def test_components_use_existing_catalog_types_and_supported_properties():
    raw, _ = load_guide_and_problem()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}

    for step in raw["steps"]:
        if step["type"] != "add_component":
            continue
        component = step["component"]
        assert component["nodeId"] not in components
        assert set(component["position"]) == {"x", "y"}
        assert all(type(value) in (int, float) for value in component["position"].values())
        assert component["properties"]["componentName"] == component["label"]
        assert component["properties"]["purpose"]

        block = catalog_block(catalog, component["componentType"], step["id"])
        supported = set(re.findall(r'\bkey:\s*"([^\"]+)"', block))
        assert set(component["properties"]) <= supported, (
            f"{step['id']}: unsupported properties "
            f"{sorted(set(component['properties']) - supported)}"
        )
        components[component["nodeId"]] = component

    types = {component["componentType"] for component in components.values()}
    assert {
        "web-app",
        "api-gateway",
        "auth-service",
        "ai-orchestrator",
        "object-storage",
        "queue",
        "processing-worker",
        "backend-server",
        "ml-model",
        "model-serving",
        "model-registry",
        "database",
        "monitoring",
        "custom-component",
    } <= types

    custom = [
        component
        for component in components.values()
        if component["componentType"] == "custom-component"
    ]
    assert len(custom) == 1
    assert custom[0]["nodeId"] == "med_external_ehr"
    assert "no dedicated EHR catalog type" in custom[0]["description"]


def test_action_replay_is_connected_and_preserves_critical_paths():
    raw, _ = load_guide_and_problem()
    known_nodes = set()
    edge_ids = []

    for step in sorted(raw["steps"], key=lambda row: row["stepNumber"]):
        if step["type"] == "add_component":
            node_id = step["component"]["nodeId"]
            assert node_id not in known_nodes
            known_nodes.add(node_id)
        elif step["type"] == "add_connection":
            edge = step["connection"]
            assert edge["sourceNodeId"] in known_nodes, step["id"]
            assert edge["targetNodeId"] in known_nodes, step["id"]
            assert edge["connectionType"] in CONNECTION_TYPES
            assert edge["label"] and edge["description"]
            edge_ids.append(edge["edgeId"])

    assert len(edge_ids) == len(set(edge_ids))
    graph = build_architecture(raw)["architecture"]
    nodes = {component["id"] for component in graph["components"]}
    assert nodes == known_nodes
    assert len(graph["connections"]) == len(edge_ids)

    neighbors = {node_id: set() for node_id in nodes}
    directed = {node_id: set() for node_id in nodes}
    for edge in graph["connections"]:
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
        directed[edge["source"]].add(edge["target"])

    reached = set()
    pending = deque(["med_clinician_client"])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    assert reached == nodes

    def reaches(source: str, target: str) -> bool:
        seen = set()
        pending_nodes = [source]
        while pending_nodes:
            current = pending_nodes.pop()
            if current == target:
                return True
            if current not in seen:
                seen.add(current)
                pending_nodes.extend(directed[current] - seen)
        return False

    assert reaches("med_clinician_client", "med_api_gateway")
    assert reaches("med_api_gateway", "med_workflow")
    assert reaches("med_workflow", "med_analysis_queue")
    assert reaches("med_analysis_queue", "med_dicom_worker")
    assert reaches("med_dicom_worker", "med_model_serving")
    assert reaches("med_model_registry", "med_model_serving")
    assert reaches("med_model_serving", "med_vision_model")
    assert reaches("med_workflow", "med_fhir_adapter")
    assert reaches("med_fhir_adapter", "med_external_ehr")
    assert reaches("med_workflow", "med_differential_service")
    assert reaches("med_workflow", "med_audit_queue")
    assert reaches("med_audit_queue", "med_audit_store")
    assert reaches("med_workflow", "med_api_gateway")
    assert reaches("med_api_gateway", "med_clinician_client")


def test_clinical_assistive_scope_and_unverified_claims_stay_explicit():
    raw, _ = load_guide_and_problem()
    text = json.dumps(raw, ensure_ascii=False).casefold()

    for phrase in (
        "not autonomous diagnosis",
        "clinician remains responsible",
        "not evidence of achieved accuracy",
        "no validation cohort",
        "no dedicated ehr component type",
        "does not by itself prove",
        "not itself fda/ce authorization",
        "do not state that this architecture is hipaa/gdpr compliant",
        "federated learning",
        "on-premises",
        "abstain",
        "under-5-second",
    ):
        assert phrase in text

    assert "95% accurate" in text
    assert "zero critical misses" in text
    assert "approved intended-use and evaluation scope" in text
