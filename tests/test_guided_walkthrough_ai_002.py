"""Contract, palette, and action-replay checks for ai_002's guided walkthrough."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / "ai_002.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": "ai_002",
    "slug": "design-a-real-time-ai-content-moderation-system",
    "title": "Design a Real-time AI Content Moderation System",
    "description": (
        "Design an AI-powered content moderation system that detects harmful content "
        "across text, images, and video in real-time, supports multiple languages, "
        "and provides human-in-the-loop review workflows."
    ),
    "category": "AI - Content Safety",
    "domain": "aiml",
    "difficulty": "Hard",
    "estimated_time": "60-90 minutes",
    "requirements": [
        "Classify text for toxicity, hate speech, and spam",
        "Detect NSFW and violent imagery",
        "Process video frames for harmful content",
        "Support 50+ languages",
        "Implement human review queues for edge cases",
        "Provide appeal and feedback mechanisms",
        "Generate moderation audit trails",
        "Update detection models without downtime",
    ],
    "constraints": [
        "Moderation latency under 200ms for text",
        "Image classification under 500ms",
        "False positive rate below 1%",
        "Process 10M+ items per day",
        "Support real-time streaming content",
    ],
    "hints": [
        "Use multi-modal models for text and image classification",
        "Implement cascade filtering (fast rules then ML models)",
        "Use embedding similarity for known harmful content",
        "Queue borderline cases for human review",
        "Implement feedback loops to improve model accuracy",
        "Use content hashing for duplicate detection",
    ],
    "companies": ["Meta", "Google", "OpenAI", "TikTok"],
}
ANCHORS = {
    *(f"legacy-requirement:{number}" for number in range(1, 9)),
    *(f"legacy-constraint:{number}" for number in range(1, 6)),
}
ACTION_TYPES = {"add_component", "add_connection", "update_component"}
CONNECTION_TYPES = {"api-call", "data-flow"}
SELECT_VALUES = {
    ("api-gateway", "authentication"): {"OAuth 2.0", "JWT", "API Key", "Basic Auth"},
    ("auth-service", "sessions"): {"redis", "database", "none"},
    ("embedding-service", "model"): {
        "text-embedding-3-large",
        "text-embedding-3-small",
        "ada-002",
        "bge-large",
        "e5-large",
        "all-MiniLM-L6-v2",
        "Self-hosted",
    },
    ("ml-model", "modelType"): {
        "Classification", "Regression", "NLP", "Computer Vision", "Recommendation",
        "Forecasting", "Clustering", "Anomaly Detection",
    },
    ("ml-model", "framework"): {
        "TensorFlow", "PyTorch", "Scikit-learn", "XGBoost", "Keras", "ONNX",
    },
    ("model-serving", "platform"): {
        "TensorFlow Serving", "TorchServe", "MLflow", "Seldon Core", "KServe", "Custom API",
    },
}


def load_guide() -> dict:
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"{step_id}: unknown palette component {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), f"{step_id}: incomplete catalog entry {component_type}"
    return catalog[match.start() : block_end]


def test_schema_and_exact_live_brief_are_preserved():
    raw = load_guide()
    guide = GuidedWalkthrough.model_validate(raw)

    assert guide.problem_id == FROZEN_BRIEF["id"]
    assert guide.version == "1.0"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 57
    assert "has_guided_walkthrough" not in raw
    opening = guide.steps[0].content
    for field in ("title", "slug", "description", "category", "domain", "difficulty", "estimated_time"):
        assert FROZEN_BRIEF[field] in opening
    for supplied_fact in [
        *FROZEN_BRIEF["requirements"],
        *FROZEN_BRIEF["constraints"],
        *FROZEN_BRIEF["hints"],
        *FROZEN_BRIEF["companies"],
    ]:
        assert supplied_fact in opening


def test_every_requirement_and_constraint_is_on_a_replayable_action():
    guide = load_guide()
    assert [step["stepNumber"] for step in guide["steps"]] == list(range(1, 58))
    assert len({step["id"] for step in guide["steps"]}) == guide["totalSteps"]
    assert all(step["title"].strip() and step["content"].strip() for step in guide["steps"])

    mapped = {anchor for step in guide["steps"] for anchor in step.get("requirementIds", [])}
    actionable = {
        anchor
        for step in guide["steps"]
        if step["type"] in ACTION_TYPES
        for anchor in step.get("requirementIds", [])
    }
    assert mapped == actionable == ANCHORS

    next_step = 1
    for phase in guide["phases"]:
        start, end = phase["stepRange"]
        assert len(phase["stepRange"]) == 2
        assert start == next_step
        assert start <= end <= guide["totalSteps"]
        assert all(step["phase"] == phase["name"] for step in guide["steps"][start - 1 : end])
        next_step = end + 1
    assert next_step == guide["totalSteps"] + 1


def test_component_ids_properties_and_select_values_match_palette():
    guide = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}

    for step in guide["steps"]:
        if step["type"] != "add_component":
            continue
        component = step["component"]
        component_type = component["componentType"]
        assert component_type != "custom-component", f"{step['id']}: unexpected custom node"
        assert component["nodeId"] not in components
        assert set(component["position"]) == {"x", "y"}
        assert all(type(value) in (int, float) for value in component["position"].values())
        assert component["properties"]["componentName"] == component["label"]
        assert component["properties"]["purpose"].strip()

        block = catalog_block(catalog, component_type, step["id"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert set(component["properties"]) <= supported, (
            f"{step['id']}: unsupported properties "
            f"{sorted(set(component['properties']) - supported)}"
        )
        for (expected_type, property_name), allowed in SELECT_VALUES.items():
            if component_type == expected_type and property_name in component["properties"]:
                assert component["properties"][property_name] in allowed, (
                    f"{step['id']}: invalid {property_name} catalog selection"
                )
        components[component["nodeId"]] = component

    assert len(components) == 20
    assert "custom-component" not in {component["componentType"] for component in components.values()}


def test_ordered_actions_replay_to_one_connected_graph():
    guide = load_guide()
    known_nodes = set()
    edge_ids = set()

    for step in sorted(guide["steps"], key=lambda row: row["stepNumber"]):
        if step["type"] == "add_component":
            node_id = step["component"]["nodeId"]
            assert node_id not in known_nodes
            known_nodes.add(node_id)
        elif step["type"] == "add_connection":
            edge = step["connection"]
            assert edge["edgeId"] not in edge_ids
            assert edge["sourceNodeId"] in known_nodes
            assert edge["targetNodeId"] in known_nodes
            assert edge["connectionType"] in CONNECTION_TYPES
            assert edge["label"].strip() and edge["description"].strip()
            edge_ids.add(edge["edgeId"])

    replay = build_architecture(guide)
    graph = replay["architecture"]
    nodes = {component["id"] for component in graph["components"]}
    edges = graph["connections"]
    assert nodes == known_nodes
    assert len(edges) == len(edge_ids) == 35
    assert len(replay["appliedStepIds"]) == 55
    assert len(replay["explanationOnlyStepIds"]) == 2
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in edges)

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque(["mod_publishing_client"])
    while pending:
        node_id = pending.popleft()
        if node_id in reached:
            continue
        reached.add(node_id)
        pending.extend(neighbors[node_id] - reached)
    assert reached == nodes


def test_false_positive_release_gate_connects_quality_analytics_to_model_release():
    guide = load_guide()
    gate = next(step for step in guide["steps"] if step["id"] == "mod_53_quality_to_release_gate")

    assert gate["type"] == "add_connection"
    assert gate["connection"]["sourceNodeId"] == "mod_quality_analytics"
    assert gate["connection"]["targetNodeId"] == "mod_model_training"
    assert "upper 95% confidence bound" in gate["content"]
    assert "blocks promotion" in gate["content"]
    assert "rolls back" in gate["content"]
    assert "FP/(FP+TN)" in gate["content"]
    assert "FPR=FP/(FP+TN)" in gate["connection"]["description"]
    assert "upper 95% confidence bound below 1%" in gate["connection"]["description"]


def test_assessment_critical_path_and_cache_policy_are_encoded_on_existing_nodes():
    guide = load_guide()
    components = {
        step["component"]["nodeId"]: step["component"]
        for step in guide["steps"]
        if step["type"] == "add_component"
    }

    orchestrator = components["mod_orchestrator"]["properties"]["purpose"]
    cache = components["mod_hash_cache"]["properties"]["purpose"]
    serving = components["mod_model_serving"]["properties"]["purpose"]
    assert "200ms response" in orchestrator
    assert "best-effort" in orchestrator
    assert "pending/review" in orchestrator
    assert "active policy and model versions" in cache
    assert "treated as misses" in cache
    assert "invalidate mismatched cache entries" in serving


def test_fifty_plus_language_requirement_is_explicit_on_the_canvas_model():
    guide = load_guide()
    text_model = next(
        step["component"]
        for step in guide["steps"]
        if step.get("component", {}).get("nodeId") == "mod_text_model"
    )

    assert "50+ languages" in text_model["properties"]["purpose"]
    assert "human review" in text_model["properties"]["purpose"]
