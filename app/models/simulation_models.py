"""Contracts for preparing an architecture for the educational simulator."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
SimulationOperation = Literal["read", "write"]


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

    title: str = Field(default="System design", max_length=240)
    description: str = Field(default="", max_length=8000)
    requirements: str | None = Field(default=None, max_length=12000)
    constraints: str | None = Field(default=None, max_length=12000)


class SimulationPreparationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    components: list[SimulationComponent] = Field(min_length=1, max_length=100)
    connections: list[SimulationConnection] = Field(default_factory=list, max_length=200)
    problem: SimulationProblem | None = None

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
    status: Literal["ready", "blocked", "needs_review"]
    blockers: list[str] = Field(default_factory=list, max_length=30)


class SimulationProfile(BaseModel):
    """Defaults are educational assumptions and never provider benchmarks."""

    role: SimulationRole
    operations_per_second: float = Field(gt=0, le=1_000_000)
    provenance: Literal["educational-default", "user"] = "educational-default"
