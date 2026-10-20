"""Structural, frozen-brief, catalog, and replay checks for ai_003."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / "ai_003.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": "ai_003",
    "slug": "semantic-search-engine",
    "title": "Design an AI-Powered Semantic Search Engine",
    "description": (
        "Design a search engine that understands natural language queries, uses "
        "vector embeddings for semantic similarity, supports hybrid search with "
        "keyword matching, and provides relevance ranking."
    ),
    "category": "AI - Search & Retrieval",
    "domain": "aiml",
    "difficulty": "Hard",
    "estimated_time": "60-90 minutes",
    "requirements": [
        "Convert documents into vector embeddings",
        "Support semantic similarity search",
        "Implement hybrid search (vector + keyword)",
        "Handle multi-modal search (text, images)",
        "Provide faceted filtering and aggregations",
        "Support real-time index updates",
        "Implement query understanding and expansion",
        "Rank results by relevance",
    ],
    "constraints": [
        "Search latency under 100ms for 100M+ documents",
        "Support 10k+ queries per second",
        "Embedding generation under 50ms",
        "Index update latency under 5 seconds",
        "Cost-effective storage for billions of vectors",
    ],
    "hints": [
        "Use vector databases (Pinecone, Weaviate, Milvus)",
        "Generate embeddings with sentence transformers",
        "Implement ANN (Approximate Nearest Neighbor) search",
        "Use HNSW or IVF indexes for fast retrieval",
        "Combine BM25 with vector scores for hybrid ranking",
        "Cache frequent queries and embeddings",
    ],
    "companies": ["Google", "Elastic", "Pinecone", "Algolia"],
    "has_guided_walkthrough": False,
}

STEP_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "decision_point",
    "scale_trigger",
    "update_component",
}
ACTION_TYPES = {"add_component", "add_connection", "update_component"}
CONNECTION_TYPES = {
    "api-call",
    "data-flow",
    "database-connection",
    "message-queue",
}


def load_problem() -> dict:
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == "ai_003")


def load_guide() -> dict:
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"{step_id}: unknown palette component {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), f"{step_id}: incomplete catalog entry {component_type}"
    return catalog[match.start() : block_end]


def test_schema_and_frozen_problem_row_are_preserved():
    problem = load_problem()
    for field, expected in FROZEN_BRIEF.items():
        assert problem.get(field) == expected

    raw = load_guide()
    guide = GuidedWalkthrough.model_validate(raw)
    assert guide.problem_id == FROZEN_BRIEF["id"]
    assert guide.version == "1.0"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps)
    assert "has_guided_walkthrough" not in raw

    opening = guide.steps[0].content
    for field in (
        "title",
        "slug",
        "description",
        "category",
        "domain",
        "difficulty",
        "estimated_time",
    ):
        assert FROZEN_BRIEF[field] in opening
    for supplied_fact in (
        *FROZEN_BRIEF["requirements"],
        *FROZEN_BRIEF["constraints"],
        *FROZEN_BRIEF["hints"],
        *FROZEN_BRIEF["companies"],
    ):
        assert supplied_fact in opening


def test_every_frozen_requirement_and_constraint_has_an_apply_action():
    guide = load_guide()
    assert [step["stepNumber"] for step in guide["steps"]] == list(
        range(1, guide["totalSteps"] + 1)
    )
    assert len({step["id"] for step in guide["steps"]}) == guide["totalSteps"]
    assert all(
        step["type"] in STEP_TYPES and step["title"].strip() and step["content"].strip()
        for step in guide["steps"]
    )

    expected_anchors = {
        *(f"legacy-requirement:{index}" for index in range(1, 9)),
        *(f"legacy-constraint:{index}" for index in range(1, 6)),
    }
    mapped = {
        anchor for step in guide["steps"] for anchor in step.get("requirementIds", [])
    }
    actionable = {
        anchor
        for step in guide["steps"]
        if step["type"] in ACTION_TYPES
        for anchor in step.get("requirementIds", [])
    }
    assert mapped == actionable == expected_anchors

    next_step = 1
    for phase in guide["phases"]:
        start, end = phase["stepRange"]
        assert len(phase["stepRange"]) == 2
        assert start == next_step
        assert start <= end <= guide["totalSteps"]
        assert all(
            step["phase"] == phase["name"]
            for step in guide["steps"][start - 1 : end]
        )
        next_step = end + 1
    assert next_step == guide["totalSteps"] + 1


def test_all_added_components_and_properties_exist_in_the_palette():
    guide = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}

    for step in guide["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            component_type = component["componentType"]
            assert component_type != "custom-component"
            assert component["nodeId"] not in components
            assert set(component["position"]) == {"x", "y"}
            assert all(type(value) in (int, float) for value in component["position"].values())
            assert component["properties"]["componentName"] == component["label"]
            assert component["properties"]["purpose"].strip()

            block = catalog_block(catalog, component_type, step["id"])
            supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
            properties = component["properties"]
            assert set(properties) <= supported, (
                f"{step['id']}: unsupported properties {sorted(set(properties) - supported)}"
            )

            for property_name, value in properties.items():
                property_schema = re.search(
                    rf'\{{\s*key:\s*"{re.escape(property_name)}"(?P<body>.*?)(?=\n\s*\{{|\n\s*\],)',
                    block,
                    re.DOTALL,
                )
                if property_schema and re.search(
                    r'\btype:\s*"select"', property_schema["body"]
                ):
                    options = re.search(
                        r'options:\s*\[([^\]]*)\]',
                        property_schema["body"],
                        re.DOTALL,
                    )
                    if options:
                        allowed = set(re.findall(r'"([^"]+)"', options[1]))
                        assert value in allowed, (
                            f"{step['id']}: invalid {component_type}.{property_name}={value!r}"
                        )
            components[component["nodeId"]] = component

        if step.get("componentUpdate"):
            update = step["componentUpdate"]
            assert update["nodeId"] in components
            component = components[update["nodeId"]]
            block = catalog_block(catalog, component["componentType"], step["id"])
            supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
            assert set(update["properties"]) <= supported

    assert len(components) == 13
    assert "custom-component" not in {
        component["componentType"] for component in components.values()
    }


def test_quantified_slo_security_recovery_and_cost_assumptions_are_explicit():
    guide = load_guide()
    targets = guide["steps"][1]["content"]
    assert "95ms" in targets and "5ms headroom" in targets
    assert "0% cache-hit baseline" in targets
    assert "ceil(10,000 / (0.70 x measured per-replica QPS))" in targets
    assert "4.5s" in targets and "202 response" in targets
    assert "3.07TB" in targets and "0.768TB" in targets

    components = {
        step["component"]["nodeId"]: step["component"]
        for step in guide["steps"]
        if step["type"] == "add_component"
    }
    gateway = components["semantic_search_gateway"]["properties"]["purpose"]
    coordinator = components["semantic_search_api"]["properties"]["purpose"]
    cache = components["semantic_search_cache"]["properties"]["purpose"]
    worker = components["semantic_index_worker"]["properties"]["purpose"]
    monitoring = components["semantic_search_monitoring"]["properties"]["purpose"]
    assert "OAuth/OIDC" in gateway and "per-tenant" in gateway
    assert "never trust client-supplied scope" in coordinator
    assert "ACL version" in cache and "0% cache-hit capacity baseline" in coordinator
    assert "atomic active-generation switch" in worker
    assert "p50/p95/p99" in monitoring and "backpressure/replay" in monitoring


def test_ordered_actions_replay_to_one_connected_multimodal_graph():
    guide = load_guide()
    known_nodes = set()
    edge_ids = set()
    edge_pairs = []

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
            edge_pairs.append((edge["sourceNodeId"], edge["targetNodeId"]))

    replay = build_architecture(guide)
    architecture = replay["architecture"]
    actual_nodes = {component["id"] for component in architecture["components"]}
    assert actual_nodes == known_nodes
    assert len(architecture["connections"]) == len(edge_ids) == 28
    assert len(replay["appliedStepIds"]) == 41
    assert len(replay["explanationOnlyStepIds"]) == 4

    neighbors = {node_id: set() for node_id in known_nodes}
    for source, target in edge_pairs:
        neighbors[source].add(target)
        neighbors[target].add(source)
    reached = set()
    pending = deque(["semantic_search_client"])
    while pending:
        node_id = pending.popleft()
        if node_id in reached:
            continue
        reached.add(node_id)
        pending.extend(neighbors[node_id] - reached)
    assert reached == known_nodes

    added = {
        step["component"]["nodeId"]: step["component"]
        for step in guide["steps"]
        if step["type"] == "add_component"
    }
    encoder = added["semantic_embedding_service"]["properties"]
    vector_index = added["semantic_vector_index"]["properties"]
    assert encoder["model"] == "Self-hosted"
    assert encoder["dimensions"] == vector_index["dimensions"] == 768
    assert vector_index["indexType"] == "IVF"
