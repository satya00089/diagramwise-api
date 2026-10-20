"""Frozen-brief, catalog, and local graph checks for the NLP pipeline draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "ml_006"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": "ml_006",
    "title": "Design a Natural Language Processing Pipeline",
    "slug": "design-a-natural-language-processing-pipeline",
    "description": "Design an NLP pipeline that processes unstructured text through entity extraction, relation extraction, sentiment analysis, topic modeling, and text classification at scale.",
    "difficulty": "Medium",
    "category": "ML - NLP",
    "domain": "aiml",
    "estimated_time": "45-60 minutes",
    "requirements": [
        "Extract named entities (people, organizations, locations)",
        "Identify relationships between entities",
        "Classify documents into categories",
        "Perform sentiment and opinion analysis",
        "Extract key phrases and topics",
        "Handle multiple languages",
        "Process structured and unstructured text",
        "Provide API for batch and real-time processing",
    ],
    "constraints": [
        "Entity extraction F1-score above 90%",
        "Classification accuracy above 85%",
        "Process 10k+ documents per hour in batch",
        "Real-time processing under 500ms per document",
        "Support at least 10 languages",
    ],
    "hints": [
        "Use transformer-based models (BERT, RoBERTa) for NER",
        "Implement SpaCy for fast entity extraction",
        "Use fine-tuned models per domain for accuracy",
        "Implement text preprocessing (tokenization, normalization)",
        "Use BERTopic or LDA for topic modeling",
        "Deploy models behind a FastAPI service",
    ],
    "tags": ["ml", "nlp", "ner", "text-classification", "sentiment-analysis", "transformers"],
    "companies": ["Google", "Amazon", "Hugging Face", "spaCy"],
    "has_guided_walkthrough": False,
}
STEP_TYPES = {"explanation", "add_component", "add_connection", "decision_point", "scale_trigger"}
CONNECTION_TYPES = {"api-call", "data-flow", "event-stream", "message-queue"}
EXPECTED_COMPONENT_TYPES = {
    "nlp_api": "api-gateway",
    "nlp_storage": "object-storage",
    "nlp_queue": "queue",
    "nlp_batch_worker": "backend-server",
    "nlp_preprocess": "stream-processor",
    "nlp_ner": "model-serving",
    "nlp_relations": "model-serving",
    "nlp_classification": "model-serving",
    "nlp_sentiment": "model-serving",
    "nlp_topics": "model-serving",
    "nlp_aggregate": "backend-server",
    "nlp_monitoring": "monitoring",
}


def load_guide() -> tuple[dict, GuidedWalkthrough]:
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def catalog_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'(?m)^    id:\s*"{re.escape(component_type)}"\s*,', catalog)
    assert match, f"Unknown component catalog ID {component_type!r}"
    end = re.search(r"(?m)^  \},\s*$", catalog[match.end() :])
    assert end, f"Could not delimit component catalog ID {component_type!r}"
    return catalog[match.start() : match.end() + end.start()]


def expected_anchors() -> set[str]:
    return {
        *(f"legacy-requirement:{index}" for index in range(1, len(FROZEN_BRIEF["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(FROZEN_BRIEF["constraints"]) + 1)),
    }


def test_frozen_brief_identity_requirements_and_constraints_are_covered_exactly():
    raw, guide = load_guide()
    assert guide.problem_id == FROZEN_BRIEF["id"]
    assert raw["version"].endswith("review-draft")

    serialized = json.dumps(raw, ensure_ascii=False)
    for field in ("title", "description", "difficulty", "category", "estimated_time"):
        assert FROZEN_BRIEF[field] in serialized
    for field in ("requirements", "constraints", "hints"):
        for brief_item in FROZEN_BRIEF[field]:
            assert brief_item in serialized, f"Missing frozen {field[:-1]}: {brief_item}"

    all_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    graph_action_anchors = {
        anchor
        for step in guide.steps
        if step.type in {"add_component", "add_connection"}
        for anchor in step.requirementIds
    }
    assert all_anchors == expected_anchors()
    assert graph_action_anchors == expected_anchors()


def test_steps_phases_and_connection_actions_are_ordered_and_valid():
    raw, guide = load_guide()
    assert guide.totalSteps == len(guide.steps) == 45
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES for step in guide.steps)

    existing_nodes: set[str] = set()
    edge_ids: set[str] = set()
    for step in raw["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            assert component["nodeId"] not in existing_nodes
            existing_nodes.add(component["nodeId"])
        elif step["type"] == "add_connection":
            connection = step["connection"]
            assert connection["edgeId"] not in edge_ids
            edge_ids.add(connection["edgeId"])
            assert connection["sourceNodeId"] in existing_nodes
            assert connection["targetNodeId"] in existing_nodes
            assert connection["connectionType"] in CONNECTION_TYPES
        elif step["type"] == "decision_point":
            assert step["decision"]["question"] and step["decision"]["chosen"]
        elif step["type"] == "scale_trigger":
            assert all(step["scaleTrigger"][key] for key in ("metric", "action", "impact"))

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1


def test_catalog_components_properties_and_replay_form_one_connected_graph():
    raw, guide = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step.component.nodeId: step.component
        for step in guide.steps
        if step.type == "add_component" and step.component is not None
    }
    assert {node_id: component.componentType for node_id, component in additions.items()} == EXPECTED_COMPONENT_TYPES

    for node_id, component in additions.items():
        block = catalog_block(catalog, component.componentType)
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert component.properties
        assert set(component.properties) <= supported, (
            f"{node_id} has unsupported {component.componentType} properties: "
            f"{sorted(set(component.properties) - supported)}"
        )

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    components = {component["id"] for component in architecture["components"]}
    edges = architecture["connections"]
    assert len(components) == 12
    assert len(edges) == 26
    assert components == set(EXPECTED_COMPONENT_TYPES)
    neighbors = {component_id: set() for component_id in components}
    for edge in edges:
        assert edge["type"] in CONNECTION_TYPES
        assert edge["source"] in components and edge["target"] in components
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])

    reached: set[str] = set()
    pending = deque([next(iter(components))])
    while pending:
        current = pending.popleft()
        if current in reached:
            continue
        reached.add(current)
        pending.extend(neighbors[current] - reached)
    assert reached == components
    assert len(replay["appliedStepIds"]) > len(replay["explanationOnlyStepIds"])


def test_nlp_choices_cover_all_tasks_languages_and_separate_service_targets():
    raw, _ = load_guide()
    serialized = json.dumps(raw, ensure_ascii=False).casefold()
    for phrase in (
        "named entity recognition",
        "relation extraction",
        "document classification",
        "sentiment and opinion",
        "key phrase and topic",
        "at least ten languages",
        "structured and unstructured",
        "10k+ documents per hour",
        "under 500ms per document",
        "f1-score above 90%",
        "accuracy above 85%",
        "xlm-r",
        "spacy",
        "bertopic",
        "real-time",
        "batch",
    ):
        assert phrase in serialized

    decisions = [step["decision"]["chosen"] for step in raw["steps"] if step["type"] == "decision_point"]
    assert any("language-aware routing" in choice and "domain-fine-tuned" in choice for choice in decisions)
    assert any("Run NER first and relation extraction" in choice for choice in decisions)
    assert any("F1 above 90%" in choice and "accuracy above 85%" in choice for choice in decisions)


def test_quality_and_latency_constraints_are_anchored_to_the_matching_tasks():
    raw, _ = load_guide()
    steps = {step["id"]: step for step in raw["steps"]}

    def anchors(step_id: str) -> set[str]:
        return set(steps[step_id].get("requirementIds", []))

    entity_f1 = "legacy-constraint:1"
    classification_accuracy = "legacy-constraint:2"
    language_coverage = "legacy-constraint:5"
    realtime_latency = "legacy-constraint:4"

    assert entity_f1 in anchors("nlp_ner")
    assert classification_accuracy not in anchors("nlp_ner")
    assert classification_accuracy in anchors("nlp_classification")
    assert entity_f1 not in anchors("nlp_classification")
    assert entity_f1 not in anchors("nlp_relations")
    assert entity_f1 not in anchors("nlp_sentiment")
    assert entity_f1 in anchors("nlp_ner_monitoring")
    assert classification_accuracy not in anchors("nlp_ner_monitoring")
    assert classification_accuracy in anchors("nlp_classification_monitoring")
    assert entity_f1 not in anchors("nlp_classification_monitoring")
    assert {entity_f1, classification_accuracy} <= anchors("nlp_quality_gate")

    assert language_coverage in anchors("nlp_routing_choice")
    assert classification_accuracy not in anchors("nlp_routing_choice")
    for step_id in ("nlp_batch_worker", "nlp_storage_worker", "nlp_queue_monitoring"):
        assert realtime_latency not in anchors(step_id)
    assert realtime_latency in anchors("nlp_api_monitoring")
