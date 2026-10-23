"""AI-assisted graph interpretation for the bounded local simulator."""

from __future__ import annotations

import asyncio
import json
import logging

from pydantic import ValidationError

from app.models.simulation_models import (
    SimulationComponentRole,
    SimulationConnectionCheck,
    SimulationPreparationDraft,
    SimulationPreparationRequest,
    SimulationPreparationResponse,
    SimulationRole,
    SimulationRoute,
)
from app.services.llm_client import create_llm_provider
from app.services.llm_port import LLMPort, LLMRequest
from app.utils.config import Settings, get_settings


logger = logging.getLogger(__name__)

KNOWN_CATALOG_ROLES: dict[str, SimulationRole] = {
    "client": "client",
    "frontend": "client",
    "api-gateway": "ingress",
    "load-balancer": "ingress",
    "web-server": "compute",
    "application-server": "compute",
    "microservice": "compute",
    "backend": "compute",
    "cache": "cache",
    "database": "database",
}


class SimulationPreparationError(RuntimeError):
    """Raised when the diagram cannot be safely interpreted for simulation."""


class SimulationPreparationService:
    MAX_TIMEOUT_SECONDS = 35.0

    def __init__(
        self,
        llm: LLMPort | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm
        configured_timeout = float(
            getattr(self.settings, "llm_assessment_timeout_seconds", 45.0)
        )
        self.timeout_seconds = min(
            max(configured_timeout, 1.0), self.MAX_TIMEOUT_SECONDS
        )

    async def prepare(
        self, request: SimulationPreparationRequest
    ) -> SimulationPreparationResponse:
        """Map a diagram into supported paths and validate all references."""

        deterministic = self._prepare_simple_graph(request)
        if deterministic is not None:
            return deterministic

        system_prompt = """
You prepare architecture diagrams for a small educational request-capacity simulator.
Return only the exact JSON object requested by the supplied schema. Do not write code,
invent components, invent connections, infer measured capacity, or make cloud-provider
performance claims.

Use only these component roles: client, ingress, compute, cache, database, queue, other.
Only client, ingress, compute, cache, and database have behavior in this first model.
Classify every supplied component from its catalog type, label, properties, and problem
context. Use `other` when evidence is insufficient; never silently treat an unknown
component as unlimited-capacity pass-through.

Check every supplied connection in context. The status `incompatible` means the edge
cannot perform its apparent job in this scenario; `uncertain` means the evidence is not
enough to decide. An API gateway or other ingress connected directly to Redis/cache or a
database bypasses application logic and is incompatible for this redirect/create-link
model. A cache or database should be reached from a compute component. Do not claim
that this is a universal cloud-product limitation: explain that it is unsupported by
this scenario model. Do not mark an edge incompatible only because it is unusual.

Provide one directed `redirect` route and one directed `create-link` route, in execution
order, using only the exact supplied node and edge IDs. Each route must start at a client,
include a compute component, and end at exactly one database. A redirect route may pass
through at most one cache before the database. A create-link route must not pass through a
cache in this model. If a route cannot be supported by the graph, return empty node_ids
and edge_ids for that operation and add a concise unresolved item. Paths must not invent
missing application layers. A read replica or second database is unsupported because
this model has no replica routing or freshness behavior.

Distinguish explicit graph facts from assumptions. Keep the result concise and tied to
the supplied IDs. An exercise ID and revision are context only; do not derive numeric
workload or capacity from unstructured prose. The simulator will calculate capacity from
editable educational profiles; do not provide numeric capacity, latency, failure-rate,
or reliability claims.
""".strip()
        user_prompt = (
            "Prepare this graph for the URL-shortener redirect/create-link capacity model. "
            "Return one JSON "
            "object that follows this schema exactly:\n"
            + json.dumps(SimulationPreparationDraft.model_json_schema())
            + "\nDiagram input:\n"
            + request.model_dump_json(exclude_none=True)
        )

        try:
            llm = self.llm or create_llm_provider(self.settings)
            response = await asyncio.wait_for(
                llm.generate(
                    LLMRequest(
                        task="simulation-preparation",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        max_tokens=min(
                            int(self.settings.llm_assessment_max_tokens), 5000
                        ),
                        response_format={"type": "json_object"},
                        temperature=0.0,
                        reasoning_effort=getattr(
                            self.settings,
                            "llm_assessment_reasoning_effort",
                            None,
                        ),
                        tags=("diagramwise", "simulation", "preparation"),
                        metadata={
                            "component_count": len(request.components),
                            "connection_count": len(request.connections),
                            "problem_title": request.problem.title
                            if request.problem
                            else None,
                        },
                    )
                ),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError as error:
            raise SimulationPreparationError(
                "AI preparation timed out. Retry after the diagram is stable."
            ) from error
        except Exception as error:
            logger.warning(
                "Simulation preparation failed error_type=%s", type(error).__name__
            )
            raise SimulationPreparationError(
                "AI could not prepare this diagram. No simulation metrics were produced."
            ) from error

        if response.refusal_present:
            raise SimulationPreparationError(
                "AI could not prepare this diagram. No simulation metrics were produced."
            )
        if not response.content:
            raise SimulationPreparationError(
                "AI returned no simulation preparation. Retry the check."
            )

        try:
            raw = json.loads(response.content)
            draft = SimulationPreparationDraft.model_validate(raw)
        except (json.JSONDecodeError, ValidationError, TypeError) as error:
            logger.warning(
                "Simulation preparation output rejected error_type=%s",
                type(error).__name__,
            )
            raise SimulationPreparationError(
                "AI returned an unsupported preparation. Retry the check."
            ) from error

        return self._validate_graph_mapping(request, draft)

    @classmethod
    def _prepare_simple_graph(
        cls, request: SimulationPreparationRequest
    ) -> SimulationPreparationResponse | None:
        """Use catalog roles when the read/write paths are unambiguous."""
        roles: dict[str, SimulationRole] = {}
        for component in request.components:
            role = KNOWN_CATALOG_ROLES.get(component.type.casefold().replace("_", "-"))
            if role is None:
                return None
            roles[component.id] = role

        outgoing: dict[str, list[tuple[str, str]]] = {}
        for edge in request.connections:
            # Canvas defaults carry empty label fields. Anything with behavioral
            # meaning needs the interpreter's semantic compatibility check.
            if (
                edge.type not in {"api-call", "http", "tcp", "database-connection"}
                or edge.label
                or edge.description
                or any(
                    key not in {"label", "hasLabel", "type", "purpose", "description"}
                    or (key == "hasLabel" and value is not False)
                    or (key == "type" and value != edge.type)
                    or (key in {"label", "purpose", "description"} and value is not None and value != "")
                    for key, value in edge.properties.items()
                )
            ):
                return None
            outgoing.setdefault(edge.source, []).append((edge.target, edge.id))

        paths: list[tuple[list[str], list[str]]] = []
        explored = 0
        def walk(nodes: list[str], edges: list[str]) -> None:
            nonlocal explored
            explored += 1
            if explored > 500 or len(paths) > 2 or len(nodes) > 10:
                return
            if roles[nodes[-1]] == "database":
                paths.append((nodes, edges))
                return
            for target, edge_id in outgoing.get(nodes[-1], []):
                if target not in nodes:
                    walk([*nodes, target], [*edges, edge_id])

        for node_id, role in roles.items():
            if role == "client":
                walk([node_id], [])
        if explored > 500 or len(paths) > 2:
            return None

        direct: list[tuple[list[str], list[str]]] = []
        cached: list[tuple[list[str], list[str]]] = []
        for nodes, edges in paths:
            path_roles = [roles[node] for node in nodes]
            if (
                "compute" not in path_roles
                or path_roles[0] != "client"
                or path_roles[-1] != "database"
                or any(role not in {"client", "ingress", "compute", "cache", "database"} for role in path_roles)
                or "client" in path_roles[1:]
                or "database" in path_roles[:-1]
            ):
                continue
            if "cache" in path_roles:
                if path_roles.count("cache") == 1 and path_roles[-2] == "cache" and path_roles.index("compute") < len(path_roles) - 2:
                    cached.append((nodes, edges))
            else:
                direct.append((nodes, edges))
        if len(direct) != 1 or len(cached) > 1:
            return None

        redirect_nodes, redirect_edges = cached[0] if cached else direct[0]
        create_nodes, create_edges = direct[0]
        selected_edges = set(redirect_edges) | set(create_edges)
        if any(
            edge.id not in selected_edges
            and not (roles[edge.source] == "ingress" and roles[edge.target] in {"cache", "database"})
            for edge in request.connections
        ):
            return None
        draft = SimulationPreparationDraft(
            component_roles=[
                SimulationComponentRole(
                    node_id=component.id,
                    role=roles[component.id],
                    evidence=f"Catalog type {component.type}",
                ) for component in request.components
            ],
            connection_checks=[
                SimulationConnectionCheck(
                    edge_id=edge.id,
                    status="supported",
                    explanation="Directed graph connection between catalog components.",
                ) for edge in request.connections
            ],
            routes=[
                SimulationRoute(operation="redirect", node_ids=redirect_nodes, edge_ids=redirect_edges,
                                explanation="Unique directed redirect path through catalog components."),
                SimulationRoute(operation="create-link", node_ids=create_nodes, edge_ids=create_edges,
                                explanation="Unique directed link-creation path through catalog components."),
            ],
            assumptions=["Each uncached redirect reads once; each link creation writes once."],
            unresolved=[],
            summary="The directed catalog paths support the URL-shortener capacity model.",
        )
        return cls._validate_graph_mapping(request, draft)

    @staticmethod
    def _validate_graph_mapping(
        request: SimulationPreparationRequest,
        draft: SimulationPreparationDraft,
    ) -> SimulationPreparationResponse:
        component_by_id = {component.id: component for component in request.components}
        connection_by_id = {connection.id: connection for connection in request.connections}
        role_by_id = {item.node_id: item.role for item in draft.component_roles}
        check_by_id = {item.edge_id: item for item in draft.connection_checks}
        blockers: list[str] = []
        unresolved = list(draft.unresolved)

        if len(role_by_id) != len(draft.component_roles) or set(role_by_id) != set(
            component_by_id
        ):
            raise SimulationPreparationError(
                "AI did not classify every diagram component exactly once. Retry the check."
            )
        if len(check_by_id) != len(draft.connection_checks) or set(check_by_id) != set(
            connection_by_id
        ):
            raise SimulationPreparationError(
                "AI did not check every diagram connection exactly once. Retry the check."
            )
        routes_by_operation = {route.operation: route for route in draft.routes}
        if len(routes_by_operation) != len(draft.routes) or set(
            routes_by_operation
        ) != {"redirect", "create-link"}:
            raise SimulationPreparationError(
                "AI did not return one redirect route and one create-link route. Retry the check."
            )

        # Core catalog roles have explicit identities, so retain those facts even if
        # the model proposes a conflicting interpretation. Provider-specific aliases
        # and custom nodes remain the interpreter's responsibility.
        for role_item in draft.component_roles:
            component_type = component_by_id[role_item.node_id].type.casefold().replace(
                "_", "-"
            )
            known_role = KNOWN_CATALOG_ROLES.get(component_type)
            if known_role and role_item.role != known_role:
                role_item.role = known_role
                role_item.evidence = (
                    f"Catalog type {component_by_id[role_item.node_id].type}"
                )
                role_by_id[role_item.node_id] = known_role

        # Enforce a small role-level boundary independent of model judgment. This is
        # specific to the supported request model, not a universal component-pair catalog.
        for edge in request.connections:
            source_role = role_by_id[edge.source]
            target_role = role_by_id[edge.target]
            if source_role == "ingress" and target_role in {"cache", "database"}:
                source = component_by_id[edge.source].label
                target = component_by_id[edge.target].label
                reason = (
                    f"{source} connects directly to {target}. This model requires "
                    "application logic between ingress and a cache or database."
                )
                check_by_id[edge.id].status = "incompatible"
                check_by_id[edge.id].explanation = reason

        for edge_id, check in check_by_id.items():
            edge = connection_by_id[edge_id]
            if check.status == "incompatible":
                blockers.append(
                    f"{component_by_id[edge.source].label} → "
                    f"{component_by_id[edge.target].label}: {check.explanation}"
                )
            elif check.status == "uncertain":
                unresolved.append(
                    f"Connection {component_by_id[edge.source].label} → "
                    f"{component_by_id[edge.target].label}: {check.explanation}"
                )

        for operation, route in routes_by_operation.items():
            operation_label = operation
            if not route.node_ids or not route.edge_ids:
                blockers.append(
                    f"AI could not map a supported {operation_label} route through this graph."
                )
                continue
            if len(route.node_ids) != len(route.edge_ids) + 1:
                raise SimulationPreparationError(
                    f"AI returned a malformed {operation_label} route. Retry the check."
                )
            if len(route.node_ids) != len(set(route.node_ids)):
                blockers.append(
                    f"The {operation_label} route contains a loop that this model does not support."
                )
            if any(node_id not in component_by_id for node_id in route.node_ids):
                raise SimulationPreparationError(
                    f"AI invented a component in the {operation_label} route. Retry the check."
                )
            roles = [role_by_id[node_id] for node_id in route.node_ids]
            if roles[0] != "client" or roles[-1] != "database" or "compute" not in roles:
                blockers.append(
                    f"The {operation_label} route must run from a client through application "
                    "logic to a database for this model."
                )
            database_positions = [
                index for index, role in enumerate(roles) if role == "database"
            ]
            if len(database_positions) != 1:
                blockers.append(
                    f"The {operation_label} route must contain exactly one database; "
                    "replica routing is not modeled."
                )
            cache_positions = [
                index for index, role in enumerate(roles) if role == "cache"
            ]
            if operation == "create-link" and cache_positions:
                blockers.append(
                    "The create-link route cannot pass through a cache in this model."
                )
            if operation == "redirect":
                if len(cache_positions) > 1:
                    blockers.append(
                        "The redirect route supports at most one cache in this model."
                    )
                elif cache_positions and (
                    cache_positions[0] != len(roles) - 2
                    or "compute" not in roles[:cache_positions[0]]
                ):
                    blockers.append(
                        "The redirect cache must follow application logic and directly precede the database."
                    )
            if any(role in {"other", "queue"} for role in roles):
                blockers.append(
                    f"The {operation_label} route contains a component role not modeled yet."
                )
            for index, edge_id in enumerate(route.edge_ids):
                edge = connection_by_id.get(edge_id)
                if edge is None:
                    raise SimulationPreparationError(
                        f"AI invented a connection in the {operation_label} route. Retry the check."
                    )
                if (edge.source, edge.target) != (
                    route.node_ids[index],
                    route.node_ids[index + 1],
                ):
                    raise SimulationPreparationError(
                        f"AI returned a disconnected {operation_label} route. Retry the check."
                    )
                if check_by_id[edge_id].status != "supported":
                    blockers.append(
                        f"The {operation_label} route uses a connection that is not validated."
                    )

        # Preserve the model's declared role and edge order for stable UI rendering.
        checked_roles = [
            draft_role
            for draft_role in draft.component_roles
            if draft_role.node_id in component_by_id
        ]
        checked_edges = [
            check_by_id[edge.id] for edge in request.connections
        ]
        status = (
            "blocked"
            if blockers
            else "needs_review"
            if unresolved
            else "ready"
        )
        return SimulationPreparationResponse(
            status=status,
            component_roles=checked_roles,
            connection_checks=checked_edges,
            routes=[
                routes_by_operation["redirect"],
                routes_by_operation["create-link"],
            ],
            assumptions=draft.assumptions,
            unresolved=list(dict.fromkeys(unresolved)),
            summary=draft.summary,
            blockers=list(dict.fromkeys(blockers)),
        )
