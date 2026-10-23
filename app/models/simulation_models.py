"""Contracts for preparing an architecture for the educational simulator."""

from math import isclose
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


SimulationRole = Literal[
    "client",
    "ingress",
    "compute",
    "cache",
    "database",
    "queue",
    "other",
]
CompatibilityStatus = Literal["supported", "incompatible", "uncertain"]
SimulationOperation = Literal["redirect", "create-link"]


class SimulationComponent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=160)
    type: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=240)
    properties: dict[str, object] = Field(default_factory=dict)


class SimulationConnection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=160)
    source: str = Field(min_length=1, max_length=160)
    target: str = Field(min_length=1, max_length=160)
    type: str = Field(default="api-call", max_length=80)
    label: str | None = Field(default=None, max_length=240)
    description: str | None = Field(default=None, max_length=2000)
    properties: dict[str, object] = Field(default_factory=dict)


class SimulationProblem(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(min_length=1, max_length=160)
    slug: Literal["url-shortener-like-bit-ly"]
    requirement_revision: str | None = Field(
        default=None, alias="requirementRevision", max_length=200
    )
    title: str = Field(default="System design", max_length=240)
    description: str = Field(default="", max_length=8000)
    requirements: str | None = Field(default=None, max_length=12000)
    constraints: str | None = Field(default=None, max_length=12000)


class SimulationPreparationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    contract_version: Literal["1"] = Field(alias="contractVersion")
    scenario_id: Literal["url-shortener-capacity"] = Field(alias="scenarioId")
    components: list[SimulationComponent] = Field(min_length=1, max_length=100)
    connections: list[SimulationConnection] = Field(default_factory=list, max_length=200)
    problem: SimulationProblem

    @model_validator(mode="after")
    def validate_graph_references(self) -> "SimulationPreparationRequest":
        node_ids = [component.id for component in self.components]
        edge_ids = [connection.id for connection in self.connections]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Component IDs must be unique")
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("Connection IDs must be unique")
        known_nodes = set(node_ids)
        if any(
            connection.source not in known_nodes
            or connection.target not in known_nodes
            for connection in self.connections
        ):
            raise ValueError("Every connection must reference existing components")
        if len(self.model_dump_json().encode("utf-8")) > 256 * 1024:
            raise ValueError("Simulation preparation input exceeds 256 KiB")
        return self


class SimulationComponentRole(BaseModel):
    node_id: str
    role: SimulationRole
    evidence: str = Field(max_length=500)


class SimulationConnectionCheck(BaseModel):
    edge_id: str
    status: CompatibilityStatus
    explanation: str = Field(max_length=800)


class SimulationRoute(BaseModel):
    operation: SimulationOperation
    node_ids: list[str] = Field(default_factory=list, max_length=100)
    edge_ids: list[str] = Field(default_factory=list, max_length=99)
    explanation: str = Field(default="", max_length=800)


class SimulationPreparationDraft(BaseModel):
    component_roles: list[SimulationComponentRole] = Field(max_length=100)
    connection_checks: list[SimulationConnectionCheck] = Field(max_length=200)
    routes: list[SimulationRoute] = Field(max_length=2)
    assumptions: list[str] = Field(default_factory=list, max_length=12)
    unresolved: list[str] = Field(default_factory=list, max_length=12)
    summary: str = Field(max_length=1000)


class SimulationPreparationResponse(SimulationPreparationDraft):
    contract_version: Literal["1"] = "1"
    scenario_id: Literal["url-shortener-capacity"] = "url-shortener-capacity"
    exercise_id: str | None = None
    requirement_revision: str | None = None
    status: Literal["ready", "blocked", "needs_review"]
    blockers: list[str] = Field(default_factory=list, max_length=30)


class SimulationAvailabilityResponse(BaseModel):
    enabled: bool
    contract_version: Literal["1"] = "1"
    scenario_id: Literal["url-shortener-capacity"] = "url-shortener-capacity"
    scenario_version: Literal["1"] = "1"
    model_version: Literal["capacity-v1"] = "capacity-v1"


class SimulationProfile(BaseModel):
    """Defaults are educational assumptions and never provider benchmarks."""

    role: SimulationRole
    operations_per_second: float = Field(gt=0, le=1_000_000)
    provenance: Literal["educational-default", "user"] = "educational-default"


SimulationCapacityRole = Literal["ingress", "compute", "cache", "database"]
InputProvenance = Literal["educational-default", "user"]


class SavedSimulationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    scenario_id: Literal["url-shortener-capacity"] = Field(alias="scenarioId")
    scenario_version: Literal["1"] = Field(alias="scenarioVersion")
    model_version: Literal["capacity-v1"] = Field(alias="modelVersion")
    request_rate: FiniteFloat = Field(alias="requestRate", ge=0, le=5000)
    redirect_share_percent: FiniteFloat = Field(
        alias="redirectSharePercent", ge=0, le=100
    )
    cache_hit_percent: FiniteFloat = Field(alias="cacheHitPercent", ge=0, le=100)
    profile_capacities: dict[SimulationCapacityRole, FiniteFloat] = Field(
        alias="profileCapacities"
    )
    provenance: dict[str, object]

    @model_validator(mode="after")
    def validate_provenance_and_profiles(self) -> "SavedSimulationInput":
        roles = {"ingress", "compute", "cache", "database"}
        if set(self.profile_capacities) != roles:
            raise ValueError("Saved run has an incomplete capacity profile")
        supported_capacity_ranges = {
            "ingress": (100, 20_000),
            "compute": (100, 10_000),
            "cache": (100, 50_000),
            "database": (100, 3_000),
        }
        if any(
            not supported_capacity_ranges[role][0] <= value <= supported_capacity_ranges[role][1]
            for role, value in self.profile_capacities.items()
        ):
            raise ValueError("Saved run capacity values are outside the supported range")
        if set(self.provenance) != {
            "requestRate", "redirectSharePercent", "cacheHitPercent", "profileCapacities"
        }:
            raise ValueError("Saved run has incomplete input provenance")
        if any(
            self.provenance.get(field) not in ("user", "educational-default")
            for field in ("requestRate", "redirectSharePercent", "cacheHitPercent")
        ):
            raise ValueError("Saved run contains invalid input provenance")
        capacities = self.provenance.get("profileCapacities")
        if not isinstance(capacities, dict) or set(capacities) != roles or any(
            value not in ("user", "educational-default") for value in capacities.values()
        ):
            raise ValueError("Saved run contains invalid capacity provenance")
        return self


class SavedSimulationNodeMetric(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    node_id: str = Field(alias="nodeId", min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=240)
    role: SimulationRole
    redirect_demand_per_second: FiniteFloat = Field(alias="redirectDemandPerSecond", ge=0, le=5000)
    create_link_demand_per_second: FiniteFloat = Field(alias="createLinkDemandPerSecond", ge=0, le=5000)
    demand_per_second: FiniteFloat = Field(alias="demandPerSecond", ge=0, le=5000)
    capacity_per_second: FiniteFloat = Field(alias="capacityPerSecond", ge=100, le=50_000)
    utilization: FiniteFloat = Field(ge=0, le=50)
    unit: Literal["requests/s", "ops/s"]


class SavedSimulationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    model_version: Literal["capacity-v1"] = Field(alias="modelVersion")
    request_rate: FiniteFloat = Field(alias="requestRate", ge=0, le=5000)
    redirects_per_second: FiniteFloat = Field(alias="redirectsPerSecond", ge=0, le=5000)
    link_creations_per_second: FiniteFloat = Field(alias="linkCreationsPerSecond", ge=0, le=5000)
    cache_hits_per_second: FiniteFloat = Field(alias="cacheHitsPerSecond", ge=0, le=5000)
    cache_misses_per_second: FiniteFloat = Field(alias="cacheMissesPerSecond", ge=0, le=5000)
    database_redirect_reads_per_second: FiniteFloat = Field(alias="databaseRedirectReadsPerSecond", ge=0, le=5000)
    database_link_writes_per_second: FiniteFloat = Field(alias="databaseLinkWritesPerSecond", ge=0, le=5000)
    estimated_capacity_at_mix_requests_per_second: FiniteFloat = Field(
        alias="estimatedCapacityAtMixRequestsPerSecond", gt=0, le=20_000
    )
    limiting_node_id: str = Field(alias="limitingNodeId", min_length=1, max_length=160)
    bottleneck_node_id: str | None = Field(default=None, alias="bottleneckNodeId", max_length=160)
    bottleneck_demand_per_second: FiniteFloat = Field(alias="bottleneckDemandPerSecond", ge=0, le=5000)
    bottleneck_capacity_per_second: FiniteFloat = Field(alias="bottleneckCapacityPerSecond", ge=100, le=50_000)
    node_metrics: list[SavedSimulationNodeMetric] = Field(alias="nodeMetrics", max_length=100)


class SavedSimulationRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    operation: SimulationOperation
    node_ids: list[str] = Field(alias="nodeIds", min_length=2, max_length=100)
    edge_ids: list[str] = Field(alias="edgeIds", max_length=99)
    node_labels: list[str] = Field(alias="nodeLabels", min_length=2, max_length=100)
    explanation: str = Field(max_length=800)

    @model_validator(mode="after")
    def validate_path_lengths(self) -> "SavedSimulationRoute":
        if len(self.edge_ids) != len(self.node_ids) - 1 or len(self.node_labels) != len(self.node_ids):
            raise ValueError("Saved run contains a malformed prepared path")
        return self


class SavedSimulationRole(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    node_id: str = Field(alias="nodeId", min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=240)
    role: SimulationRole


class SavedSimulationSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    input: SavedSimulationInput
    result: SavedSimulationResult
    graph_fingerprint: str = Field(alias="graphFingerprint", min_length=1, max_length=128)
    preparation_fingerprint: str = Field(alias="preparationFingerprint", min_length=1, max_length=16_384)
    prepared_routes: list[SavedSimulationRoute] = Field(alias="preparedRoutes", min_length=2, max_length=2)
    component_roles: list[SavedSimulationRole] = Field(alias="componentRoles", max_length=100)
    exercise_id: str = Field(alias="exerciseId", min_length=1, max_length=160)
    requirement_revision: str | None = Field(alias="requirementRevision", max_length=200)

    @model_validator(mode="after")
    def validate_snapshot_versions(self) -> "SavedSimulationSnapshot":
        if self.result.model_version != self.input.model_version:
            raise ValueError("Saved run input and result model versions do not match")
        routes_by_operation = {route.operation: route for route in self.prepared_routes}
        if set(routes_by_operation) != {"redirect", "create-link"}:
            raise ValueError("Saved run must include each modeled operation path")
        roles_by_node = {item.node_id: item.role for item in self.component_roles}
        labels_by_node = {item.node_id: item.label for item in self.component_roles}
        if len(roles_by_node) != len(self.component_roles):
            raise ValueError("Saved run has duplicate component roles")

        # Reconstruct the deterministic model from the saved inputs and routes.
        # This rejects forged or stale metrics before they reach DynamoDB.
        expected_demands: dict[str, dict[str, float]] = {}
        reference_rate = self.input.request_rate or 1.0
        operation_rates = {
            "redirect": reference_rate * self.input.redirect_share_percent / 100,
            "create-link": reference_rate * (100 - self.input.redirect_share_percent) / 100,
        }
        redirect_cache_node_id = None

        for operation in ("redirect", "create-link"):
            route = routes_by_operation[operation]
            route_roles = [roles_by_node.get(node_id) for node_id in route.node_ids]
            if (
                len(route.node_ids) < 3
                or len(set(route.node_ids)) != len(route.node_ids)
                or route_roles[0] != "client"
                or route_roles[-1] != "database"
                or route_roles.count("database") != 1
                or "compute" not in route_roles
                or "client" in route_roles[1:-1]
                or any(role not in {"client", "ingress", "compute", "cache", "database"} for role in route_roles)
            ):
                raise ValueError("Saved run contains an unsupported prepared path")
            if any(labels_by_node.get(node_id) != label for node_id, label in zip(route.node_ids, route.node_labels)):
                raise ValueError("Saved run path labels do not match its component roles")
            cache_positions = [index for index, role in enumerate(route_roles) if role == "cache"]
            if (
                (operation == "create-link" and cache_positions)
                or len(cache_positions) > 1
                or (
                    cache_positions
                    and (
                        cache_positions[0] != len(route_roles) - 2
                        or route_roles.index("compute") > cache_positions[0]
                    )
                )
            ):
                raise ValueError("Saved run contains an unsupported cache path")

            if operation_rates[operation] == 0:
                continue
            cache_seen = False
            for node_id, role in zip(route.node_ids, route_roles):
                if role == "client":
                    continue
                if operation == "redirect" and role == "cache":
                    cache_seen = True
                    redirect_cache_node_id = node_id
                demand = operation_rates[operation]
                if operation == "redirect" and role == "database" and cache_seen:
                    demand *= 1 - self.input.cache_hit_percent / 100
                node_demand = expected_demands.setdefault(
                    node_id, {"redirect": 0.0, "create-link": 0.0}
                )
                node_demand[operation] += demand

        metrics_by_node = {metric.node_id: metric for metric in self.result.node_metrics}
        if len(metrics_by_node) != len(self.result.node_metrics) or set(metrics_by_node) != set(expected_demands):
            raise ValueError("Saved run metrics do not match the prepared paths")

        offered_scale = self.input.request_rate / reference_rate
        expected_reference_utilization: dict[str, float] = {}
        for node_id, demands in expected_demands.items():
            metric = metrics_by_node[node_id]
            role = roles_by_node[node_id]
            expected_capacity = self.input.profile_capacities.get(role)
            if expected_capacity is None or metric.role != role or metric.label != labels_by_node[node_id]:
                raise ValueError("Saved run metrics do not match the component profile")
            expected_unit = "ops/s" if role in {"cache", "database"} else "requests/s"
            if metric.unit != expected_unit:
                raise ValueError("Saved run metric unit does not match the component role")
            if not isclose(metric.capacity_per_second, expected_capacity, rel_tol=1e-6, abs_tol=1e-6):
                raise ValueError("Saved run metric capacity does not match the selected profile")
            expected_redirect = demands["redirect"] * offered_scale
            expected_create = demands["create-link"] * offered_scale
            expected_total = expected_redirect + expected_create
            if (
                not isclose(metric.redirect_demand_per_second, expected_redirect, rel_tol=1e-6, abs_tol=1e-6)
                or not isclose(metric.create_link_demand_per_second, expected_create, rel_tol=1e-6, abs_tol=1e-6)
                or not isclose(metric.demand_per_second, expected_total, rel_tol=1e-6, abs_tol=1e-6)
                or not isclose(metric.utilization, expected_total / expected_capacity, rel_tol=1e-6, abs_tol=1e-6)
            ):
                raise ValueError("Saved run contains inconsistent node metrics")
            expected_reference_utilization[node_id] = (
                demands["redirect"] + demands["create-link"]
            ) / expected_capacity

        limiting_node_id = max(expected_reference_utilization, key=expected_reference_utilization.get)
        limiting_metric = metrics_by_node[limiting_node_id]
        expected_capacity_at_mix = reference_rate / expected_reference_utilization[limiting_node_id]
        expected_redirects = self.input.request_rate * self.input.redirect_share_percent / 100
        expected_creations = self.input.request_rate - expected_redirects
        expected_cache_hits = (
            expected_redirects * self.input.cache_hit_percent / 100
            if redirect_cache_node_id is not None
            else 0.0
        )
        expected_cache_misses = expected_redirects - expected_cache_hits
        database_metrics = [metric for metric in self.result.node_metrics if metric.role == "database"]
        expected_db_reads = sum(metric.redirect_demand_per_second for metric in database_metrics)
        expected_db_writes = sum(metric.create_link_demand_per_second for metric in database_metrics)
        expected_bottleneck = limiting_node_id if limiting_metric.utilization > 1 else None
        result_values_match = (
            isclose(self.result.request_rate, self.input.request_rate, rel_tol=1e-6, abs_tol=1e-6)
            and isclose(self.result.redirects_per_second, expected_redirects, rel_tol=1e-6, abs_tol=1e-6)
            and isclose(self.result.link_creations_per_second, expected_creations, rel_tol=1e-6, abs_tol=1e-6)
            and isclose(self.result.cache_hits_per_second, expected_cache_hits, rel_tol=1e-6, abs_tol=1e-6)
            and isclose(self.result.cache_misses_per_second, expected_cache_misses, rel_tol=1e-6, abs_tol=1e-6)
            and isclose(self.result.database_redirect_reads_per_second, expected_db_reads, rel_tol=1e-6, abs_tol=1e-6)
            and isclose(self.result.database_link_writes_per_second, expected_db_writes, rel_tol=1e-6, abs_tol=1e-6)
            and isclose(self.result.estimated_capacity_at_mix_requests_per_second, expected_capacity_at_mix, rel_tol=1e-6, abs_tol=1e-6)
            and self.result.limiting_node_id == limiting_node_id
            and self.result.bottleneck_node_id == expected_bottleneck
            and isclose(self.result.bottleneck_demand_per_second, limiting_metric.demand_per_second, rel_tol=1e-6, abs_tol=1e-6)
            and isclose(self.result.bottleneck_capacity_per_second, limiting_metric.capacity_per_second, rel_tol=1e-6, abs_tol=1e-6)
        )
        if not result_values_match:
            raise ValueError("Saved run result does not match its inputs and node metrics")
        return self


class SimulationRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    problem_id: str = Field(alias="problemId", min_length=1, max_length=160)
    requirement_revision: str | None = Field(alias="requirementRevision", max_length=200)
    snapshot: SavedSimulationSnapshot

    @model_validator(mode="after")
    def validate_snapshot_size_and_scope(self) -> "SimulationRunCreate":
        if self.snapshot.exercise_id != self.problem_id:
            raise ValueError("Saved run does not match the selected exercise")
        if self.snapshot.requirement_revision != self.requirement_revision:
            raise ValueError("Saved run does not match the selected requirement revision")
        if len(self.snapshot.model_dump_json(by_alias=True).encode("utf-8")) > 48 * 1024:
            raise ValueError("Saved run exceeds the 48 KiB storage limit")
        return self


class SimulationSavedRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    run_id: str = Field(alias="runId", min_length=1, max_length=64)
    created_at: str = Field(alias="createdAt", min_length=1, max_length=40)
    expires_at: int = Field(alias="expiresAt", gt=0)
    snapshot: SavedSimulationSnapshot
