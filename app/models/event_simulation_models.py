"""Bounded, versioned replay artifacts for the local event simulator.

These records are private user artifacts, not server-verified benchmark results
or challenge scores. The API never executes the submitted graph or commands.
"""

from math import isfinite
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


NodeKind = Literal[
    "client", "lb", "service", "cache", "db", "queue", "worker",
    "autoscaler", "region", "cdn", "ratelimiter", "breaker", "replica",
    "shard", "objectstore", "searchindex", "timeseriesdb", "graphdb",
    "coldstorage", "vectordb", "streambroker", "pubsub", "websocket",
    "apigateway", "sidecar", "lambda", "cron", "bulkhead", "retryqueue",
    "transcoder", "edgecompute", "writebehind", "loadshedder",
]
TrafficPattern = Literal["steady", "ramp", "spike", "diurnal"]
Identifier = Annotated[str, Field(min_length=1, max_length=200)]
FiniteNonNegative = Annotated[float, Field(ge=0, le=1e15, allow_inf_nan=False)]
SimulationTime = Annotated[float, Field(ge=0, le=86_400_000, allow_inf_nan=False)]


class EventModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, strict=True, allow_inf_nan=False
    )


# Flat numeric/enum data only. This intentionally cannot carry JavaScript,
# expressions, embedded graphs, callable plugins, or arbitrary nested objects.
NUMERIC_CONFIG_FIELDS = frozenset("""
capacity instances serviceMs serviceCv queueLimit hitRate errorRate timeoutMs
retries rps trafficPeriodS targetUtil minCapacity maxCapacity cooldownMs
scaleStepPct warmupMs regions activeRegion failoverMs rateLimitRps burst
errorThreshold windowMs openMs halfOpenProbes replicaCount replicationLagMs
readFraction shardCount shardCapacity hotKeyFraction indexMs indexLagMs
rangeQueryFraction rangeQueryMs traversalDepth indexSizeK recallTarget partitions
connectionMs authFailRate outlierAfter coldStartMs keepWarmMs maxConcurrency
intervalMs batchSize bulkheadMax acquireQueueMax acquireTimeoutMs flushDelayMs
edgeShare lowPriorityShare priorityReserve lockMs prefixRps renditions cpuMsCap
""".split())
FRACTION_FIELDS = frozenset("""
hitRate errorRate targetUtil scaleStepPct errorThreshold readFraction
hotKeyFraction rangeQueryFraction recallTarget authFailRate edgeShare
lowPriorityShare priorityReserve
""".split())
POSITIVE_INTEGER_FIELDS = frozenset("""
capacity instances replicaCount shardCount shardCapacity partitions regions
halfOpenProbes maxConcurrency bulkheadMax renditions batchSize traversalDepth
minCapacity maxCapacity outlierAfter
""".split())
ZERO_INTEGER_FIELDS = frozenset("queueLimit retries activeRegion acquireQueueMax".split())
REQUIRED_CONFIG_FIELDS = frozenset(
    "capacity serviceMs serviceCv queueLimit hitRate errorRate timeoutMs retries rps".split()
)

# event-v1: mirror defaultConfig(kind) plus the replay runtime's common fields.
# Keep this contract versioned with packages/simulation-core/src/runtime.ts.
COMMON_CONFIG_FIELDS = REQUIRED_CONFIG_FIELDS | frozenset("""
instances replicaCount replicationLagMs readFraction shardCount shardCapacity
hotKeyFraction traffic trafficPeriodS bulkheadMode
""".split())
KIND_CONFIG_FIELDS = {
    "db": "lockMs",
    "autoscaler": "targetUtil minCapacity maxCapacity cooldownMs scaleStepPct warmupMs",
    "region": "regions activeRegion failoverMs",
    "ratelimiter": "rateLimitRps burst",
    "breaker": "errorThreshold windowMs openMs halfOpenProbes",
    "objectstore": "prefixRps",
    "searchindex": "indexMs indexLagMs",
    "timeseriesdb": "rangeQueryFraction rangeQueryMs",
    "graphdb": "traversalDepth",
    "vectordb": "indexSizeK recallTarget",
    "streambroker": "partitions",
    "websocket": "connectionMs",
    "apigateway": "rateLimitRps burst authFailRate",
    "sidecar": "outlierAfter openMs",
    "lambda": "coldStartMs keepWarmMs maxConcurrency",
    "cron": "intervalMs batchSize",
    "bulkhead": "bulkheadMax acquireQueueMax acquireTimeoutMs",
    "transcoder": "renditions",
    "edgecompute": "edgeShare cpuMsCap",
    "writebehind": "flushDelayMs",
    "loadshedder": "rateLimitRps burst lowPriorityShare priorityReserve",
}


class EventSimulationNode(EventModel):
    id: Identifier
    kind: NodeKind
    label: str = Field(max_length=240)
    x: float = Field(ge=-1_000_000, le=1_000_000)
    y: float = Field(ge=-1_000_000, le=1_000_000)
    config: dict[str, float | str]

    @model_validator(mode="after")
    def validate_config(self) -> "EventSimulationNode":
        if not REQUIRED_CONFIG_FIELDS.issubset(self.config):
            raise ValueError("Replay node is missing required model settings")
        allowed = COMMON_CONFIG_FIELDS | frozenset(KIND_CONFIG_FIELDS.get(self.kind, "").split())
        if not self.config.keys() <= allowed:
            raise ValueError("Node setting is not supported by this component model")
        for key, value in self.config.items():
            if key == "traffic":
                if value not in {"steady", "ramp", "spike", "diurnal"}:
                    raise ValueError("Unknown traffic pattern")
            elif key == "bulkheadMode":
                if value not in {"reject", "wait"}:
                    raise ValueError("Unknown bulkhead mode")
            elif key not in NUMERIC_CONFIG_FIELDS:
                raise ValueError("Unknown node model setting")
            elif not isinstance(value, (int, float)) or not isfinite(value) or not 0 <= value <= 1e6:
                raise ValueError("Node settings must be finite nonnegative numbers")
            elif key in FRACTION_FIELDS and value > 1:
                raise ValueError("Fractional node settings must lie between zero and one")
            elif key in POSITIVE_INTEGER_FIELDS and (not float(value).is_integer() or not 1 <= value <= 512):
                raise ValueError("This node setting must be a bounded positive integer")
            elif key in ZERO_INTEGER_FIELDS and not float(value).is_integer():
                raise ValueError("This node setting must be a whole number")
            elif key == "retries" and value > 10:
                raise ValueError("Retry count exceeds the supported bound")
            elif key == "queueLimit" and value > 50_000:
                raise ValueError("Queue limit exceeds the supported bound")
            elif key == "serviceCv" and value > 10:
                raise ValueError("Service variability exceeds the supported bound")
            elif key == "trafficPeriodS" and value < 0.1:
                raise ValueError("Traffic period must be at least 0.1 seconds")
        minimum = self.config.get("minCapacity")
        maximum = self.config.get("maxCapacity")
        if isinstance(minimum, (int, float)) and isinstance(maximum, (int, float)) and minimum > maximum:
            raise ValueError("Minimum capacity cannot exceed maximum capacity")
        return self


class EventSimulationEdge(EventModel):
    id: Identifier
    from_id: Identifier = Field(alias="from")
    to: Identifier
    weight: float = Field(gt=0, le=1e6)
    control: bool = False
    latency_ms: float = Field(default=0, alias="latencyMs", ge=0, le=60_000)


class EventSimulationTopology(EventModel):
    nodes: list[EventSimulationNode] = Field(min_length=1, max_length=101)
    edges: list[EventSimulationEdge] = Field(max_length=201)

    @model_validator(mode="after")
    def validate_references(self) -> "EventSimulationTopology":
        node_ids = {node.id for node in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("Replay graph contains duplicate node identifiers")
        if len({edge.id for edge in self.edges}) != len(self.edges):
            raise ValueError("Replay graph contains duplicate edge identifiers")
        if any(edge.from_id not in node_ids or edge.to not in node_ids for edge in self.edges):
            raise ValueError("Replay connection references a missing node")
        if not any(node.kind == "client" for node in self.nodes):
            raise ValueError("Replay graph requires a traffic source")
        return self


class EventSimulationScope(EventModel):
    design_id: Identifier = Field(alias="designId")
    canvas_id: Identifier = Field(alias="canvasId")
    exercise_id: Identifier | None = Field(default=None, alias="exerciseId")


class EventSimulationWorkload(EventModel):
    rps: float = Field(ge=0, le=100_000)
    pattern: TrafficPattern = "steady"
    seed: int = Field(ge=0, le=4_294_967_295)


class WorkloadCommand(EventModel):
    type: Literal["workload"]
    rps: float = Field(ge=0, le=100_000)
    pattern: TrafficPattern | None = None


class ReplicaCommand(EventModel):
    type: Literal["replicas"]
    node_id: Identifier = Field(alias="nodeId")
    instances: int = Field(ge=1, le=512)


class FaultOptions(EventModel):
    factor: float | None = Field(default=None, ge=1, le=1000)
    rate: float | None = Field(default=None, ge=0, le=1)
    edge_ids: list[Identifier] | None = Field(default=None, alias="edgeIds", max_length=201)


class FaultCommand(EventModel):
    type: Literal["fault"]
    node_id: Identifier = Field(alias="nodeId")
    kind: Literal["crash", "slow", "errors", "partition"]
    opts: FaultOptions | None = None


class ClearFaultCommand(EventModel):
    type: Literal["clearFault"]
    node_id: Identifier = Field(alias="nodeId")


Command = Annotated[
    WorkloadCommand | ReplicaCommand | FaultCommand | ClearFaultCommand,
    Field(discriminator="type"),
]


class RecordedEventCommand(EventModel):
    at_ms: SimulationTime = Field(alias="atMs")
    command: Command


class EventSimulationSummary(EventModel):
    time_ms: SimulationTime = Field(alias="timeMs")
    offered_rps: FiniteNonNegative = Field(alias="offeredRps")
    goodput_rps: FiniteNonNegative = Field(alias="goodputRps")
    error_rate: float = Field(alias="errorRate", ge=0, le=1)
    p50: FiniteNonNegative
    p95: FiniteNonNegative
    p99: FiniteNonNegative
    total_requests: int = Field(alias="totalRequests", ge=0, le=10**15)
    total_failed: int = Field(alias="totalFailed", ge=0, le=10**15)
    status: Literal["complete", "incomplete"]

    @model_validator(mode="after")
    def validate_summary(self) -> "EventSimulationSummary":
        if not self.p50 <= self.p95 <= self.p99:
            raise ValueError("Latency percentiles must be ordered")
        if self.total_failed > self.total_requests:
            raise ValueError("Root failures exceed offered root requests")
        return self


class EventSimulationSnapshot(EventModel):
    contract_version: Literal["2"] = Field(alias="contractVersion")
    engine_version: Literal["event-v1"] = Field(alias="engineVersion")
    profile_version: Literal["profiles-v1"] = Field(alias="profileVersion")
    scope: EventSimulationScope
    graph_fingerprint: str = Field(alias="graphFingerprint", min_length=1, max_length=128)
    topology: EventSimulationTopology
    workload: EventSimulationWorkload
    commands: list[RecordedEventCommand] = Field(default_factory=list, max_length=1000)
    result: EventSimulationSummary | None = None

    @model_validator(mode="after")
    def validate_artifact(self) -> "EventSimulationSnapshot":
        nodes = {node.id for node in self.topology.nodes}
        edges = {edge.id for edge in self.topology.edges}
        previous = 0.0
        for entry in self.commands:
            if entry.at_ms < previous:
                raise ValueError("Replay commands must be in simulated-time order")
            previous = entry.at_ms
            command = entry.command
            if not isinstance(command, WorkloadCommand) and command.node_id not in nodes:
                raise ValueError("Replay command references a missing node")
            if isinstance(command, FaultCommand) and command.opts and command.opts.edge_ids:
                if not set(command.opts.edge_ids).issubset(edges):
                    raise ValueError("Replay fault references a missing connection")
        if self.result is not None and previous > self.result.time_ms:
            raise ValueError("Replay contains commands after its result time")
        if len(self.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8")) > 240 * 1024:
            raise ValueError("Replay artifact exceeds the 240 KiB storage limit")
        return self


class EventSimulationRunCreate(EventModel):
    snapshot: EventSimulationSnapshot


class EventSimulationRunResponse(EventModel):
    run_id: str = Field(alias="runId", min_length=1, max_length=64)
    created_at: str = Field(alias="createdAt", min_length=1, max_length=40)
    expires_at: int = Field(alias="expiresAt", gt=0)
    snapshot: EventSimulationSnapshot
