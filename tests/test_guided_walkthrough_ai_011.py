"""Frozen-brief, catalog-property, and connected-replay checks for ai_011."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "ai_011"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

# Captured from the strongly consistent live DynamoDB item. This deliberately
# lives with this candidate test rather than changing the shared fixture file.
FROZEN_BRIEF = {
    "id": "ai_011",
    "slug": "design-an-ai-powered-legal-document-analysis-platform",
    "title": "Design an AI-Powered Legal Document Analysis Platform",
    "description": (
        "Design a platform that uses AI to analyze legal documents, extract clauses, "
        "identify risks, compare contracts, and provide natural language summaries "
        "for legal professionals."
    ),
    "category": "AI - Legal Tech",
    "domain": "aiml",
    "difficulty": "Hard",
    "estimated_time": "60-90 minutes",
    "requirements": [
        "Extract key clauses from contracts",
        "Identify non-standard and risky terms",
        "Compare multiple contract versions",
        "Generate natural language summaries",
        "Search across document repositories semantically",
        "Support regulatory compliance checks",
        "Handle due diligence document review",
        "Maintain audit trail of all analyses",
    ],
    "constraints": [
        "Clause extraction accuracy above 95%",
        "Process 1000+ page documents under 2 minutes",
        "Support common document formats (PDF, DOCX, images)",
        "Handle legal terminology across jurisdictions",
        "Data confidentiality and access controls",
    ],
    "hints": [
        "Fine-tune LLMs on legal corpora",
        "Use Named Entity Recognition for legal entities",
        "Implement document chunking preserving clause boundaries",
        "Use RAG for cross-document comparison",
        "Implement OCR pipeline for scanned documents",
        "Use attention visualization for clause highlighting",
    ],
    "companies": ["Ironclad", "Kira Systems", "LegalSifter", "Thomson Reuters"],
    "has_guided_walkthrough": False,
}
ANCHORS = {
    *(f"legacy-requirement:{number}" for number in range(1, 9)),
    *(f"legacy-constraint:{number}" for number in range(1, 6)),
}
ACTION_TYPES = {"add_component", "add_connection", "update_component"}
CONNECTION_TYPES = {"api-call", "data-flow"}
EXPECTED_COMPONENT_TYPES = {
    "web-app",
    "api-gateway",
    "auth-service",
    "backend-server",
    "object-storage",
    "queue",
    "processing-worker",
    "ai-orchestrator",
    "model-serving",
    "ml-model",
    "embedding-service",
    "vector-database",
    "database",
    "model-training",
    "monitoring",
}
SELECT_VALUES = {
    ("api-gateway", "authentication"): {"OAuth 2.0", "JWT", "API Key", "Basic Auth"},
    ("auth-service", "sessions"): {"redis", "database", "none"},
    ("object-storage", "provider"): {"S3", "Azure Blob", "GCS", "MinIO"},
    ("queue", "backoff"): {"fixed", "linear", "exponential"},
    ("processing-worker", "tasks"): {
        "Media Encoding", "Thumbnail Generation", "Data Processing", "ML Inference"
    },
    ("ai-orchestrator", "framework"): {
        "LangChain", "LlamaIndex", "Haystack", "Semantic Kernel", "Custom"
    },
    ("model-serving", "platform"): {
        "TensorFlow Serving", "TorchServe", "MLflow", "Seldon Core", "KServe", "Custom API"
    },
    ("ml-model", "modelType"): {
        "Classification", "Regression", "NLP", "Computer Vision", "Recommendation",
        "Forecasting", "Clustering", "Anomaly Detection"
    },
    ("ml-model", "framework"): {
        "TensorFlow", "PyTorch", "Scikit-learn", "XGBoost", "Keras", "ONNX"
    },
    ("embedding-service", "model"): {
        "text-embedding-3-large", "text-embedding-3-small", "ada-002", "bge-large",
        "e5-large", "all-MiniLM-L6-v2", "Self-hosted"
    },
    ("vector-database", "engine"): {
        "Pinecone", "Weaviate", "Milvus", "Qdrant", "Chroma", "FAISS", "pgvector"
    },
    ("vector-database", "indexType"): {"HNSW", "IVF", "Flat", "LSH"},
    ("database", "type"): {"RDBMS", "NoSQL", "NewSQL", "Time-Series", "Graph"},
    ("database", "engine"): {
        "postgresql", "mysql", "mongodb", "cassandra", "dynamodb", "cockroachdb"
    },
    ("database", "workload"): {"OLTP", "OLAP", "Hybrid"},
    ("model-training", "computeType"): {"CPU", "GPU", "TPU", "Distributed"},
    ("monitoring", "stack"): {
        "Prometheus + Grafana", "Datadog", "New Relic", "CloudWatch"
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


def test_schema_and_captured_live_brief_are_preserved():
    raw = load_guide()
    guide = GuidedWalkthrough.model_validate(raw)
    opening = guide.steps[0].content

    assert guide.problem_id == FROZEN_BRIEF["id"]
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 39
    assert "has_guided_walkthrough" not in raw
    for field in ("title", "slug", "description", "category", "domain", "difficulty", "estimated_time"):
        assert FROZEN_BRIEF[field] in opening
    for supplied_fact in [
        *FROZEN_BRIEF["requirements"],
        *FROZEN_BRIEF["constraints"],
        *FROZEN_BRIEF["hints"],
        *FROZEN_BRIEF["companies"],
    ]:
        assert supplied_fact in opening
    assert FROZEN_BRIEF["has_guided_walkthrough"] is False


def test_every_requirement_and_constraint_is_anchored_to_replayable_actions():
    guide = load_guide()
    assert [step["stepNumber"] for step in guide["steps"]] == list(range(1, 40))
    assert len({step["id"] for step in guide["steps"]}) == guide["totalSteps"]
    assert all(step["title"] and step["content"] for step in guide["steps"])

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


def test_components_use_existing_catalog_ids_and_supported_properties():
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
        assert component["properties"]["purpose"]

        block = catalog_block(catalog, component_type, step["id"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert set(component["properties"]) <= supported, (
            f"{step['id']}: unsupported properties "
            f"{sorted(set(component['properties']) - supported)}"
        )
        for (expected_type, property_name), values in SELECT_VALUES.items():
            if component_type == expected_type and property_name in component["properties"]:
                assert component["properties"][property_name] in values, (
                    f"{step['id']}: invalid {property_name} catalog selection"
                )
        components[component["nodeId"]] = component

    assert {component["componentType"] for component in components.values()} == EXPECTED_COMPONENT_TYPES
    assert len(components) == 15


def test_replayed_graph_is_connected_and_contains_required_paths():
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
            assert edge["label"] and edge["description"]
            edge_ids.add(edge["edgeId"])

    replay = build_architecture(guide)
    graph = replay["architecture"]
    nodes = {component["id"] for component in graph["components"]}
    assert nodes == known_nodes
    assert len(graph["connections"]) == len(edge_ids) == 21

    neighbors = {node_id: set() for node_id in nodes}
    directed = {node_id: set() for node_id in nodes}
    for edge in graph["connections"]:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
        directed[edge["source"]].add(edge["target"])

    reached = set()
    pending = deque(["legal_doc_workspace"])
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

    assert reaches("legal_doc_workspace", "legal_analysis_api")
    assert reaches("legal_analysis_api", "legal_analysis_queue")
    assert reaches("legal_analysis_queue", "legal_ingestion_worker")
    assert reaches("legal_ingestion_worker", "legal_analysis_orchestrator")
    assert reaches("legal_analysis_orchestrator", "legal_model_serving")
    assert reaches("legal_model_serving", "legal_clause_model")
    assert reaches("legal_analysis_orchestrator", "legal_embedding_service")
    assert reaches("legal_embedding_service", "legal_semantic_index")
    assert reaches("legal_analysis_api", "legal_metadata_audit_db")
    assert reaches("legal_model_validation", "legal_clause_model")

