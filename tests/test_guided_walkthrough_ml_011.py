"""Frozen-brief, catalog, quality-anchor, and replay checks for ml_011."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "ml_011"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

LIVE_BRIEF = {
    "title": "Design a Knowledge Graph Construction and Query System",
    "description": (
        "Design a system that automatically constructs knowledge graphs from "
        "unstructured data, performs entity resolution, supports graph-based "
        "reasoning, and answers complex queries over the graph."
    ),
    "requirements": [
        "Extract entities and relations from text",
        "Perform entity resolution and deduplication",
        "Build and update graph schema dynamically",
        "Support graph-based queries and traversals",
        "Implement graph embeddings for link prediction",
        "Visualize graph relationships",
        "Handle temporal and versioned facts",
        "Integrate with LLMs for natural language querying",
    ],
    "constraints": [
        "Entity resolution precision above 95%",
        "Relation extraction F1-score above 80%",
        "Query latency under 500ms",
        "Scale to 100M+ nodes and edges",
        "Handle real-time graph updates",
    ],
    "hints": [
        "Use NER + relation extraction pipelines for graph construction",
        "Implement graph databases (Neo4j, ArangoDB) for storage",
        "Use TransE/RotatE for knowledge graph embeddings",
        "Implement entity linking with candidate generation + re-ranking",
        "Use GNN (Graph Neural Networks) for node classification",
        "Implement Text-to-Cypher/SPARQL for natural language queries",
    ],
}

STEP_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "decision_point",
    "scale_trigger",
}
CONNECTION_TYPES = {
    "api-call",
    "data-flow",
    "database-connection",
    "event-stream",
}


def live_brief_block() -> str:
    lines = [
        f"Title: {LIVE_BRIEF['title']}",
        f"Description: {LIVE_BRIEF['description']}",
        "Requirements:",
        *(f"- {item}" for item in LIVE_BRIEF["requirements"]),
        "Constraints:",
        *(f"- {item}" for item in LIVE_BRIEF["constraints"]),
        "Hints:",
        *(f"- {item}" for item in LIVE_BRIEF["hints"]),
    ]
    return "\n".join(lines)


def load_guide() -> tuple[dict, GuidedWalkthrough]:
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def expected_anchors() -> set[str]:
    return {
        *(f"legacy-requirement:{index}" for index in range(1, len(LIVE_BRIEF["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(LIVE_BRIEF["constraints"]) + 1)),
    }


def catalog_block(catalog: str, component_type: str) -> str:
    match = re.search(
        rf'(?ms)^  \{{\r?\n    id: "{re.escape(component_type)}",(?P<body>.*?)^  \}},',
        catalog,
    )
    assert match, f"Unknown component catalog ID {component_type!r}"
    return match.group("body")


def test_live_brief_is_verbatim_and_guide_uses_public_version_one():
    raw, guide = load_guide()
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0"
    assert raw["totalSteps"] == len(guide.steps)
    assert guide.steps[0].content.startswith(live_brief_block() + "\n\n")
    assert "review-draft" not in json.dumps(raw).casefold()
    assert "unpublished" not in json.dumps(raw).casefold()


def test_steps_phases_and_every_brief_item_has_a_replayable_action_anchor():
    raw, guide = load_guide()
    assert guide.totalSteps == len(guide.steps) == 52
    assert [step.stepNumber for step in guide.steps] == list(range(1, 53))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES for step in guide.steps)

    expected = expected_anchors()
    all_mapped = {anchor for step in guide.steps for anchor in step.requirementIds}
    action_mapped = {
        anchor
        for step in guide.steps
        if step.type in {"add_component", "add_connection"}
        for anchor in step.requirementIds
    }
    assert all_mapped == expected
    assert action_mapped == expected

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(guide.steps[number - 1].phase == phase.name for number in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1


def test_components_use_existing_catalog_types_and_supported_properties():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = [
        step["component"]
        for step in raw["steps"]
        if step["type"] == "add_component"
    ]
    assert len(components) == 18
    assert all(component["componentType"] != "custom-component" for component in components)

    graph_store = next(component for component in components if component["nodeId"] == "kg_graph_store")
    assert graph_store["componentType"] == "database"
    assert graph_store["properties"]["type"] == "Graph"

    for step in raw["steps"]:
        if step["type"] != "add_component":
            continue
        component = step["component"]
        properties = component["properties"]
        assert properties["componentName"] == component["label"]
        assert len(properties["purpose"]) >= 70
        block = catalog_block(catalog, component["componentType"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert set(properties) <= supported, (
            f"{step['id']} uses unsupported {component['componentType']} properties: "
            f"{sorted(set(properties) - supported)}"
        )


def test_ordered_actions_replay_to_one_connected_catalog_graph():
    raw, _ = load_guide()
    nodes = {}
    edge_ids = set()
    pairs = []

    for step in raw["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            assert component["nodeId"] not in nodes
            assert set(component["position"]) >= {"x", "y"}
            nodes[component["nodeId"]] = component
        elif step["type"] == "add_connection":
            connection = step["connection"]
            assert connection["edgeId"] not in edge_ids
            assert connection["connectionType"] in CONNECTION_TYPES
            assert connection["sourceNodeId"] in nodes
            assert connection["targetNodeId"] in nodes
            edge_ids.add(connection["edgeId"])
            pairs.append((connection["sourceNodeId"], connection["targetNodeId"]))

    assert len(nodes) == 18
    assert len(edge_ids) == 28
    neighbors = {node_id: set() for node_id in nodes}
    for source, target in pairs:
        neighbors[source].add(target)
        neighbors[target].add(source)
    reached = set()
    pending = deque(["kg_ingestion_api"])
    while pending:
        node_id = pending.popleft()
        if node_id not in reached:
            reached.add(node_id)
            pending.extend(neighbors[node_id] - reached)
    assert reached == set(nodes)

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    assert len(architecture["components"]) == len(nodes)
    assert len(architecture["connections"]) == len(edge_ids)
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in architecture["connections"])


def test_acceptance_targets_and_safety_decisions_are_explicit():
    raw, _ = load_guide()
    text = json.dumps(raw, ensure_ascii=False).casefold()
    for phrase in (
        "entity resolution precision above 95%",
        "relation extraction f1-score above 80%",
        "query latency under 500ms",
        "scale to 100m+ nodes and edges",
        "handle real-time graph updates",
        "valid-time and recorded-time",
        "never execute model-produced query text directly",
        "cypher/sparql",
        "human review",
        "not results the architecture can promise",
    ):
        assert phrase in text, f"Walkthrough does not explicitly cover {phrase!r}"
