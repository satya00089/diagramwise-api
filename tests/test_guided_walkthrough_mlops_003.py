"""Focused frozen-brief, catalog, replay, and requirement-coverage checks for mlops_003."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / "mlops_003.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
CONNECTION_TYPES = {
    "api-call",
    "data-flow",
    "database-connection",
    "event-stream",
    "message-queue",
}
BRIEF = {
    "id": "mlops_003",
    "title": "Design a Model Registry and Versioning System",
    "description": "Design a model registry that tracks model versions and metadata, manages model lifecycle stages, stores model artifacts, and provides approval workflows for production promotion.",
    "requirements": [
        "Register and version ML models",
        "Store model artifacts and metadata",
        "Track training parameters and metrics",
        "Manage model lifecycle stages (dev, staging, prod)",
        "Implement approval workflows for promotion",
        "Compare model versions side-by-side",
        "Support model lineage (data, code, config)",
        "Integrate with CI/CD for automated deployment",
    ],
    "constraints": [
        "Support 10k+ model versions",
        "Artifact storage for models up to 100GB",
        "Search and query models by metrics",
        "Role-based access control for model promotion",
        "Audit trail for all model changes",
    ],
    "hints": [
        "Use MLflow or Weights & Biases as a base",
        "Store artifacts in object storage with metadata in DB",
        "Implement model cards for documentation",
        "Use Git-based versioning for model code",
        "Implement model comparison dashboards",
        "Integrate with deployment tools via webhooks",
    ],
    "has_guided_walkthrough": False,
}
EXPECTED_COMPONENT_TYPES = {
    "web-app",
    "api-gateway",
    "auth-service",
    "model-registry",
    "github",
    "ci-cd-pipeline",
    "database",
    "object-storage",
    "processing-worker",
    "message-broker",
    "monitoring",
}


def load_guide() -> dict:
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def catalog_component_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'(?m)^\s*id:\s*"{re.escape(component_type)}"', catalog)
    assert match, f"unknown component catalog ID {component_type!r}"
    end = catalog.find("\n  },", match.start())
    assert end != -1, f"could not find catalog block end for {component_type!r}"
    return catalog[match.start() : end]


def expected_anchors() -> set[str]:
    return {
        *(f"legacy-requirement:{number}" for number in range(1, len(BRIEF["requirements"]) + 1)),
        *(f"legacy-constraint:{number}" for number in range(1, len(BRIEF["constraints"]) + 1)),
    }


def test_draft_preserves_the_problem_brief_without_mutable_publication_state():
    raw = load_guide()
    text = json.dumps(raw, ensure_ascii=False)

    assert raw["problem_id"] == BRIEF["id"]
    assert raw["version"].endswith("local-review-draft")
    assert BRIEF["title"] in text
    assert BRIEF["description"] in text
    for field in ("requirements", "constraints", "hints"):
        for statement in BRIEF[field]:
            assert statement in text, f"live {field} statement missing: {statement}"
    assert "has_guided_walkthrough" not in text.casefold()
    assert "no aws write or publication was performed" not in text.casefold()


def test_schema_phases_and_each_explicit_requirement_has_a_replayable_action():
    raw = load_guide()
    guide = GuidedWalkthrough.model_validate(raw)

    assert guide.problem_id == BRIEF["id"]
    assert guide.totalSteps == len(guide.steps) == 43
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    expected = expected_anchors()
    actual = {anchor for step in raw["steps"] for anchor in step["requirementIds"]}
    assert actual == expected
    graph_actions = {"add_component", "add_connection", "update_component"}
    for anchor in expected:
        assert any(
            step["type"] in graph_actions and anchor in step["requirementIds"]
            for step in raw["steps"]
        ), f"{anchor} is not attached to an applied design action"


def test_every_node_uses_an_existing_catalog_id_and_supported_properties():
    raw = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = [step["component"] for step in raw["steps"] if step["type"] == "add_component"]

    assert len(additions) == 11
    assert {component["componentType"] for component in additions} == EXPECTED_COMPONENT_TYPES
    assert len({component["nodeId"] for component in additions}) == len(additions)
    assert all(component["componentType"] != "custom-component" for component in additions)

    for component in additions:
        block = catalog_component_block(catalog, component["componentType"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        properties = set(component["properties"])
        assert {"componentName", "purpose"} <= properties
        assert properties <= supported, f"{component['nodeId']} has unsupported properties: {properties - supported}"
        assert component["label"].strip() and component["description"].strip()
        assert component["highlightReason"].strip()


def test_ordered_actions_replay_into_one_connected_versioned_registry_graph():
    raw = load_guide()
    seen_nodes: set[str] = set()
    edge_ids: set[str] = set()

    for step in sorted(raw["steps"], key=lambda row: row["stepNumber"]):
        if step["type"] == "add_component":
            node_id = step["component"]["nodeId"]
            assert node_id not in seen_nodes
            seen_nodes.add(node_id)
        elif step["type"] == "add_connection":
            edge = step["connection"]
            assert edge["sourceNodeId"] in seen_nodes
            assert edge["targetNodeId"] in seen_nodes
            assert edge["sourceNodeId"] != edge["targetNodeId"]
            assert edge["edgeId"] not in edge_ids
            assert edge["connectionType"] in CONNECTION_TYPES
            assert edge["label"].strip() and edge["description"].strip()
            edge_ids.add(edge["edgeId"])

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    component_ids = {component["id"] for component in architecture["components"]}
    edges = architecture["connections"]
    assert component_ids == seen_nodes
    assert len(component_ids) == 11
    assert len(edges) == len(edge_ids) == 15
    assert len(replay["appliedStepIds"]) == len(component_ids) + len(edges)
    assert all(edge["source"] in component_ids and edge["target"] in component_ids for edge in edges)

    neighbors = {component_id: set() for component_id in component_ids}
    for edge in edges:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached: set[str] = set()
    pending = deque([next(iter(component_ids))])
    while pending:
        current = pending.popleft()
        if current in reached:
            continue
        reached.add(current)
        pending.extend(neighbors[current] - reached)
    assert reached == component_ids


def test_architecture_lessons_match_registry_storage_and_governance_behavior():
    text = json.dumps(load_guide(), ensure_ascii=False).casefold()
    for phrase in (
        "immutable object version",
        "transactional outbox",
        "exact approved artifact digest",
        "compare-and-swap",
        "multipart",
        "metric predicates",
        "the prompt does not specify",
    ):
        assert phrase in text
