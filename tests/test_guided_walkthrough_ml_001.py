"""Structural checks for the ml_001 recommendation-system walkthrough draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "ml_001"
GUIDE_PATH = ROOT / "data/guided-walkthroughs/ml_001.json"
PROBLEMS_PATH = ROOT / "tests/fixtures/walkthroughs/problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic/src/config/components.ts"

TITLE = "Design a Real-time Recommendation System"
DESCRIPTION = (
    "Design a recommendation system that generates personalized recommendations "
    "using collaborative filtering, content-based approaches, and deep learning, "
    "serving predictions with sub-100ms latency."
)
REQUIREMENTS = [
    "Implement collaborative filtering algorithms",
    "Build content-based recommendation models",
    "Serve personalized recommendations in real-time",
    "Handle the cold-start problem for new users/items",
    "Track user interactions for model feedback",
    "Support multiple recommendation strategies",
    "Implement diversity and novelty in recommendations",
    "Provide explainable recommendations",
]
CONSTRAINTS = [
    "Recommendation latency under 50ms",
    "Support 10M+ users and 1M+ items",
    "Update user preferences within 5 minutes",
    "CTR improvement above 20% vs baseline",
    "Handle sparse user-item interaction matrices",
]
HINTS = [
    "Use two-tower models for candidate retrieval",
    "Implement ANN indexes for fast similarity search",
    "Use feature stores for real-time user features",
    "Implement a ranking model as a second stage",
    "Use embedding tables for users and items",
    "Implement online learning for real-time updates",
]
COMPANIES = ["Netflix", "Spotify", "Amazon", "YouTube"]
EXPECTED_ANCHORS = {
    *(f"legacy-requirement:{index}" for index in range(1, 9)),
    *(f"legacy-constraint:{index}" for index in range(1, 6)),
}
ACTION_TYPES = {"add_component", "add_connection", "update_component"}
CONNECTION_TYPES = {
    "api-call",
    "data-flow",
    "database-connection",
    "event-stream",
    "http",
    "message-queue",
}
EXPECTED_COMPONENT_TYPES = {
    "analytics",
    "api-gateway",
    "backend-server",
    "cache",
    "database",
    "feature-store",
    "ml-model",
    "model-registry",
    "model-serving",
    "model-training",
    "monitoring",
    "queue",
    "stream-processor",
    "vector-database",
    "web-app",
}
EXPECTED_NODE_IDS = {
    "rec_client",
    "rec_gateway",
    "rec_orchestrator",
    "rec_cache",
    "rec_features",
    "rec_serving",
    "rec_ann_index",
    "rec_events",
    "rec_preference_stream",
    "rec_interaction_store",
    "rec_training",
    "rec_collaborative_model",
    "rec_content_model",
    "rec_ranker_model",
    "rec_registry",
    "rec_experiment_analytics",
    "rec_monitoring",
}

# Each legacy anchor must be carried by an applied action whose own text and
# payload make the corresponding frozen-brief idea observable.
ANCHOR_EVIDENCE = {
    "legacy-requirement:1": ("collaborative filtering",),
    "legacy-requirement:2": ("content-based",),
    "legacy-requirement:3": ("personalized recommendations", "real-time"),
    "legacy-requirement:4": ("cold-start",),
    "legacy-requirement:5": ("impression", "click"),
    "legacy-requirement:6": ("multiple recommendation strategies",),
    "legacy-requirement:7": ("diversity", "novelty"),
    "legacy-requirement:8": ("explainable",),
    "legacy-constraint:1": ("under 50ms",),
    "legacy-constraint:2": ("10m+ users", "1m+ items"),
    "legacy-constraint:3": ("within 5 minutes",),
    "legacy-constraint:4": ("ctr", "above 20%", "baseline"),
    "legacy-constraint:5": ("sparse user-item interaction",),
}


def load_problem_and_guide() -> tuple[dict, dict]:
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    return problem, json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"{step_id}: unknown catalog component {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), f"{step_id}: incomplete catalog entry"
    return catalog[match.start() : block_end]


def assert_catalog_properties(
    catalog: str, component_type: str, properties: dict, step_id: str
) -> None:
    block = catalog_block(catalog, component_type, step_id)
    for key, value in properties.items():
        field_start = re.search(rf'\{{\s*key:\s*"{re.escape(key)}"', block)
        assert field_start, f"{step_id}: {component_type}.{key} is not catalogued"
        field_end = block.find("},", field_start.start())
        assert field_end != -1, f"{step_id}: incomplete catalog field {key}"
        field = block[field_start.start() : field_end]
        field_type = re.search(r'\btype:\s*"([^\"]+)"', field)
        assert field_type, f"{step_id}: catalog field {key} has no type"

        kind = field_type.group(1)
        if kind == "boolean":
            assert type(value) is bool, f"{step_id}/{key} must be boolean"
        elif kind == "number":
            assert type(value) in (int, float), f"{step_id}/{key} must be numeric"
        elif kind in {"text", "textarea"}:
            assert isinstance(value, str), f"{step_id}/{key} must be text"
        elif kind == "select":
            options = re.search(r'\boptions:\s*\[([^\]]*)\]', field, re.DOTALL)
            assert options, f"{step_id}/{key}: catalog options are missing"
            allowed = set(re.findall(r'"([^\"]+)"', options.group(1)))
            assert value in allowed, f"{step_id}/{key}: unsupported value {value!r}"


def action_evidence(step: dict) -> str:
    parts = [step.get("content", ""), json.dumps(step, ensure_ascii=False)]
    return " ".join(parts).casefold()


def test_frozen_problem_row_matches_the_reviewed_brief():
    problem, _ = load_problem_and_guide()

    assert problem["id"] == PROBLEM_ID
    assert problem["title"] == TITLE
    assert problem["description"] == DESCRIPTION
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert problem["hints"] == HINTS
    assert problem["companies"] == COMPANIES
    assert problem["has_guided_walkthrough"] is False


def test_schema_phases_and_every_frozen_requirement_have_an_applied_action():
    _, raw = load_problem_and_guide()
    guide = GuidedWalkthrough.model_validate(raw)

    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps)
    assert [step.stepNumber for step in guide.steps] == list(
        range(1, guide.totalSteps + 1)
    )
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.id and step.title and step.content for step in guide.steps)

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert len(phase.stepRange) == 2
        assert start == next_step <= end <= guide.totalSteps
        assert all(
            guide.steps[index - 1].phase == phase.name
            for index in range(start, end + 1)
        )
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    all_anchors = {
        anchor for step in raw["steps"] for anchor in step.get("requirementIds", [])
    }
    action_steps = [step for step in raw["steps"] if step["type"] in ACTION_TYPES]
    action_anchors = {
        anchor for step in action_steps for anchor in step.get("requirementIds", [])
    }
    assert all_anchors == action_anchors == EXPECTED_ANCHORS
    for step in raw["steps"]:
        assert set(step.get("requirementIds", [])) <= EXPECTED_ANCHORS
        if step["type"] == "decision_point":
            decision = step["decision"]
            assert decision["question"] and decision["chosen"]
            assert decision["chosenReason"]
            assert len(decision["alternatives"]) >= 2

    for anchor, phrases in ANCHOR_EVIDENCE.items():
        carriers = [
            step
            for step in action_steps
            if anchor in step.get("requirementIds", [])
        ]
        assert carriers, f"{anchor} is not mapped to a canvas action"
        assert any(
            all(phrase in action_evidence(step) for phrase in phrases)
            for step in carriers
        ), f"{anchor} action does not evidence {phrases}"


def test_replay_uses_only_catalog_components_and_forms_one_connected_graph():
    _, raw = load_problem_and_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}
    edge_ids = []

    for step in raw["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            assert component["nodeId"] not in components
            assert set(component["position"]) == {"x", "y"}
            assert all(
                type(value) in (int, float)
                for value in component["position"].values()
            )
            assert component["properties"]["componentName"] == component["label"]
            assert component["properties"]["purpose"]
            assert_catalog_properties(
                catalog,
                component["componentType"],
                component["properties"],
                step["id"],
            )
            components[component["nodeId"]] = component
        elif step["type"] == "add_connection":
            connection = step["connection"]
            assert connection["sourceNodeId"] in components
            assert connection["targetNodeId"] in components
            assert connection["connectionType"] in CONNECTION_TYPES
            assert connection["label"] and connection["description"]
            edge_ids.append(connection["edgeId"])

    assert len(edge_ids) == len(set(edge_ids))
    assert set(components) == EXPECTED_NODE_IDS
    assert {
        component["componentType"] for component in components.values()
    } == EXPECTED_COMPONENT_TYPES
    assert "custom-component" not in EXPECTED_COMPONENT_TYPES

    replay = build_architecture(raw)
    graph = replay["architecture"]
    nodes = {component["id"] for component in graph["components"]}
    edges = graph["connections"]
    assert nodes == EXPECTED_NODE_IDS
    assert len(edges) == len(edge_ids)
    assert len(replay["appliedStepIds"]) == len(
        [step for step in raw["steps"] if step["type"] in ACTION_TYPES]
    )
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in edges)
    assert all(edge["type"] in CONNECTION_TYPES for edge in edges)

    neighbors = {node_id: set() for node_id in nodes}
    directed = {node_id: set() for node_id in nodes}
    for edge in edges:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
        directed[edge["source"]].add(edge["target"])

    reached = set()
    pending = deque(["rec_client"])
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

    for source, target in (
        ("rec_client", "rec_orchestrator"),
        ("rec_orchestrator", "rec_features"),
        ("rec_orchestrator", "rec_serving"),
        ("rec_serving", "rec_ann_index"),
        ("rec_training", "rec_collaborative_model"),
        ("rec_training", "rec_content_model"),
        ("rec_training", "rec_ranker_model"),
        ("rec_collaborative_model", "rec_registry"),
        ("rec_content_model", "rec_registry"),
        ("rec_ranker_model", "rec_registry"),
        ("rec_registry", "rec_serving"),
        ("rec_events", "rec_preference_stream"),
        ("rec_preference_stream", "rec_features"),
        ("rec_preference_stream", "rec_cache"),
        ("rec_interaction_store", "rec_training"),
        ("rec_events", "rec_experiment_analytics"),
    ):
        assert reaches(source, target), f"missing design path: {source} -> {target}"


def test_architecture_covers_scale_latency_freshness_ctr_and_cold_start_without_invented_traffic():
    _, raw = load_problem_and_guide()
    text = json.dumps(raw, ensure_ascii=False).casefold()

    for phrase in (
        "two-tower",
        "ann",
        "collaborative filtering",
        "content-based",
        "cold-start",
        "sparse user-item interaction",
        "diversity",
        "novelty",
        "explainable",
        "impression",
        "click",
        "under 50ms",
        "10m+ users",
        "1m+ items",
        "within 5 minutes",
        "above 20%",
        "relative lift",
        "do not invent qps",
        "provider-neutral",
    ):
        assert phrase in text, f"missing design signal or assumption: {phrase}"

