import pytest

from app.models.simulation_models import (
    SimulationPreparationDraft,
    SimulationPreparationRequest,
)
from app.services.simulation_preparation import (
    SimulationPreparationError,
    SimulationPreparationService,
)


def graph_with_optional_direct_cache_edge():
    components = [
        {"id": "client", "type": "client", "label": "Clients"},
        {"id": "gateway", "type": "api-gateway", "label": "API Gateway"},
        {"id": "app", "type": "microservice", "label": "Application service"},
        {"id": "db", "type": "database", "label": "PostgreSQL"},
        {"id": "redis", "type": "cache", "label": "Redis"},
    ]
    connections = [
        {"id": "client-gateway", "source": "client", "target": "gateway"},
        {"id": "gateway-app", "source": "gateway", "target": "app"},
        {"id": "app-db", "source": "app", "target": "db"},
        {"id": "gateway-redis", "source": "gateway", "target": "redis"},
    ]
    roles = [
        {"node_id": "client", "role": "client", "evidence": "Client"},
        {"node_id": "gateway", "role": "ingress", "evidence": "API gateway"},
        {"node_id": "app", "role": "compute", "evidence": "Application service"},
        {"node_id": "db", "role": "database", "evidence": "PostgreSQL"},
        {"node_id": "redis", "role": "cache", "evidence": "Redis cache"},
    ]
    checks = [
        {"edge_id": edge["id"], "status": "supported", "explanation": "Valid for this path."}
        for edge in connections
    ]
    route = {
        "node_ids": ["client", "gateway", "app", "db"],
        "edge_ids": ["client-gateway", "gateway-app", "app-db"],
        "explanation": "The request reaches application logic and the database.",
    }
    draft = {
        "component_roles": roles,
        "connection_checks": checks,
        "routes": [
            {"operation": "redirect", **route},
            {"operation": "create-link", **route},
        ],
        "assumptions": ["Redirect reads and link writes have equal modeled cost."],
        "unresolved": [],
        "summary": "The redirect and create-link paths are supported by the graph.",
    }
    return components, connections, draft


def validate_preparation(components, connections, draft):
    request = SimulationPreparationRequest(
        contractVersion="1",
        scenarioId="url-shortener-capacity",
        problem={"id": "url-shortener-exercise", "slug": "url-shortener-like-bit-ly"},
        components=components,
        connections=connections,
    )
    prepared_draft = SimulationPreparationDraft.model_validate(draft)
    return SimulationPreparationService._validate_graph_mapping(
        request,
        prepared_draft,
    )


def test_direct_ingress_to_cache_connection_is_incompatible():
    components, connections, draft = graph_with_optional_direct_cache_edge()

    result = validate_preparation(components, connections, draft)

    direct_edge = next(
        item for item in result.connection_checks if item.edge_id == "gateway-redis"
    )
    assert result.status == "blocked"
    assert direct_edge.status == "incompatible"
    assert "application logic" in direct_edge.explanation
    assert any("API Gateway → Redis" in blocker for blocker in result.blockers)


def test_valid_directed_read_write_path_is_ready():
    components, connections, draft = graph_with_optional_direct_cache_edge()
    components = components[:-1]
    components[0]["type"] = "frontend"
    components[2]["type"] = "backend"
    connections = connections[:-1]
    draft["component_roles"] = draft["component_roles"][:-1]
    draft["connection_checks"] = draft["connection_checks"][:-1]
    draft["component_roles"][0]["role"] = "other"
    draft["component_roles"][2]["role"] = "other"

    result = validate_preparation(components, connections, draft)

    assert result.status == "ready"
    assert [route.operation for route in result.routes] == [
        "redirect",
        "create-link",
    ]
    assert result.routes[0].node_ids == ["client", "gateway", "app", "db"]
    assert result.component_roles[0].role == "client"
    assert result.component_roles[2].role == "compute"


def test_ai_cannot_invent_a_connection_for_a_simulation_route():
    components, connections, draft = graph_with_optional_direct_cache_edge()
    components = components[:-1]
    connections = connections[:-1]
    draft["component_roles"] = draft["component_roles"][:-1]
    draft["connection_checks"] = draft["connection_checks"][:-1]
    draft["routes"][0]["edge_ids"][-1] = "invented-edge"

    with pytest.raises(SimulationPreparationError, match="invented a connection"):
        validate_preparation(components, connections, draft)
