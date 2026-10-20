"""Structural and frozen-brief regression checks for the Azure IoT walkthrough draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_azure_001"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

TITLE = "Design a Scalable IoT Platform"
DESCRIPTION = (
    "Design an IoT platform that connects millions of devices, ingests sensor data at scale, "
    "processes streams in real-time, and detects anomalies."
)
REQUIREMENTS = [
    "Connect millions of IoT devices",
    "Ingest sensor data at scale",
    "Process data streams in real-time",
    "Store time-series data efficiently",
    "Detect anomalies and patterns",
    "Send commands to devices",
    "Visualize device telemetry",
    "Manage device lifecycle",
]
CONSTRAINTS = [
    "Support 10M+ connected devices",
    "Ingest 1M+ messages per second",
    "Processing latency under 5 seconds",
    "Store 5 years of time-series data",
    "Ensure device security and authentication",
]
HINTS = [
    "IoT Hub for device connectivity",
    "Stream Analytics for real-time processing",
    "Cosmos DB for device metadata",
    "Time Series Insights for telemetry",
    "Event Grid for event routing",
    "Device Provisioning Service for onboarding",
]
EXPECTED_ANCHORS = {
    *(f"legacy-requirement:{number}" for number in range(1, 9)),
    *(f"legacy-constraint:{number}" for number in range(1, 6)),
}
ACTION_TYPES = {"add_component", "add_connection"}
EXPECTED_COMPONENT_TYPES = {
    "device_fleet": "web-app",
    "device_provisioning": "auth-service",
    "iot_hub": "message-broker",
    "lifecycle_event_router": "message-broker",
    "device_registry": "database",
    "telemetry_processor": "stream-processor",
    "anomaly_analytics": "analytics",
    "timeseries_store": "database",
    "telemetry_archive": "object-storage",
    "operations_gateway": "api-gateway",
    "operations_service": "backend-server",
    "command_queue": "queue",
    "operator_console": "web-app",
    "platform_monitoring": "monitoring",
}
EXPECTED_CONNECTION_PAIRS = {
    ("device_fleet", "device_provisioning"),
    ("device_provisioning", "iot_hub"),
    ("iot_hub", "operations_service"),
    ("iot_hub", "lifecycle_event_router"),
    ("lifecycle_event_router", "device_registry"),
    ("iot_hub", "telemetry_processor"),
    ("telemetry_processor", "anomaly_analytics"),
    ("anomaly_analytics", "lifecycle_event_router"),
    ("telemetry_processor", "timeseries_store"),
    ("iot_hub", "telemetry_archive"),
    ("operator_console", "operations_gateway"),
    ("operations_gateway", "operations_service"),
    ("operations_service", "device_registry"),
    ("operations_service", "timeseries_store"),
    ("operations_service", "command_queue"),
    ("command_queue", "iot_hub"),
    ("iot_hub", "device_fleet"),
    ("device_fleet", "iot_hub"),
    ("iot_hub", "platform_monitoring"),
    ("telemetry_processor", "platform_monitoring"),
    ("timeseries_store", "platform_monitoring"),
    ("telemetry_archive", "platform_monitoring"),
    ("command_queue", "platform_monitoring"),
}


def _load() -> tuple[dict, dict, GuidedWalkthrough]:
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    return raw, problem, GuidedWalkthrough.model_validate(raw)


def _catalog_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'(?m)^    id:\s*"{re.escape(component_type)}"', catalog)
    assert match, f"Unknown component catalog ID: {component_type}"
    end = catalog.find("\n  },", match.start())
    assert end > match.start(), f"Could not bound catalog component: {component_type}"
    return catalog[match.start() : end]


def _assert_supported_properties(component_type: str, properties: dict, catalog: str) -> None:
    block = _catalog_block(catalog, component_type)
    keys = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
    assert set(properties) <= keys, (
        f"Unsupported {component_type} properties: {set(properties) - keys}"
    )

    for key, value in properties.items():
        marker = re.search(rf'\bkey:\s*"{re.escape(key)}"', block)
        assert marker, f"Missing catalog definition for {component_type}.{key}"
        remainder = block[marker.start() :]
        next_property = re.search(r"\n\s*\{\s*key:", remainder[1:])
        property_block = remainder[: next_property.start() + 1] if next_property else remainder
        field_type = re.search(r'\btype:\s*"([^"]+)"', property_block)
        assert field_type, f"Missing field type for {component_type}.{key}"
        if field_type[1] == "boolean":
            assert type(value) is bool
        elif field_type[1] == "number":
            assert type(value) in (int, float)
        elif field_type[1] == "select":
            options = re.search(r"\boptions:\s*\[([^\]]*)\]", property_block, re.DOTALL)
            assert options, f"Missing select options for {component_type}.{key}"
            assert value in set(re.findall(r'"([^"]+)"', options[1]))


def test_frozen_problem_row_matches_the_walkthrough_target():
    _, problem, guide = _load()

    assert problem["id"] == PROBLEM_ID
    assert problem["title"] == TITLE
    assert problem["description"] == DESCRIPTION
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert problem["hints"] == HINTS
    assert problem["has_guided_walkthrough"] is False
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None


def test_schema_phases_and_action_anchors_cover_every_frozen_requirement():
    raw, _, guide = _load()

    assert guide.totalSteps == len(guide.steps) == 48
    assert [step.stepNumber for step in guide.steps] == list(range(1, 49))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    expected_phases = [
        ("Frame fleet scale and target semantics", 1, 7),
        ("Enroll devices and secure the IoT ingress", 8, 17),
        ("Process, detect, query, and retain telemetry", 18, 27),
        ("Expose operations and deliver bounded commands", 28, 40),
        ("Instrument capacity and prove acceptance", 41, 48),
    ]
    assert [
        (phase.name, phase.stepRange[0], phase.stepRange[1]) for phase in guide.phases
    ] == expected_phases
    covered_steps = [
        number
        for phase in guide.phases
        for number in range(phase.stepRange[0], phase.stepRange[1] + 1)
    ]
    assert covered_steps == list(range(1, guide.totalSteps + 1))
    phase_by_step = {
        number: phase.name
        for phase in guide.phases
        for number in range(phase.stepRange[0], phase.stepRange[1] + 1)
    }
    assert all(phase_by_step[step.stepNumber] == step.phase for step in guide.steps)

    all_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert all_anchors == EXPECTED_ANCHORS
    action_anchors = {
        anchor
        for step in raw["steps"]
        if step["type"] in ACTION_TYPES
        for anchor in step.get("requirementIds", [])
    }
    assert action_anchors == EXPECTED_ANCHORS

    for step in guide.steps:
        if step.type == "add_component":
            assert step.component and step.component.nodeId and step.component.highlightReason
        elif step.type == "add_connection":
            assert step.connection and step.connection.label and step.connection.description
        elif step.type == "decision_point":
            assert step.decision and step.decision.question and step.decision.chosenReason
            assert len(step.decision.alternatives) >= 2
        elif step.type == "scale_trigger":
            assert step.scaleTrigger
            assert all(
                (step.scaleTrigger.metric, step.scaleTrigger.action, step.scaleTrigger.impact)
            )


def test_all_nodes_use_existing_catalog_components_and_supported_properties():
    raw, _, _ = _load()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step["type"] == "add_component"
    }

    assert {
        node_id: component["componentType"] for node_id, component in additions.items()
    } == EXPECTED_COMPONENT_TYPES
    assert "custom-component" not in EXPECTED_COMPONENT_TYPES.values()

    for component in additions.values():
        assert set(component["position"]) == {"x", "y"}
        assert component["properties"]["componentName"] == component["label"]
        assert len(component["properties"]["purpose"]) >= 80
        _assert_supported_properties(component["componentType"], component["properties"], catalog)


def test_ordered_actions_build_the_expected_connected_non_custom_architecture():
    raw, _, _ = _load()
    added_nodes = set()
    edge_ids = set()
    action_ids = []

    for step in sorted(raw["steps"], key=lambda item: item["stepNumber"]):
        if step["type"] == "add_component":
            node_id = step["component"]["nodeId"]
            assert node_id not in added_nodes
            added_nodes.add(node_id)
            action_ids.append(step["id"])
        elif step["type"] == "add_connection":
            edge = step["connection"]
            assert edge["sourceNodeId"] in added_nodes
            assert edge["targetNodeId"] in added_nodes
            assert edge["edgeId"] not in edge_ids
            edge_ids.add(edge["edgeId"])
            action_ids.append(step["id"])

    built = build_architecture(raw)
    architecture = built["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    edges = architecture["connections"]
    assert set(nodes) == set(EXPECTED_COMPONENT_TYPES)
    assert len(edges) == len(EXPECTED_CONNECTION_PAIRS)
    assert built["appliedStepIds"] == action_ids
    assert built["provenance"]["problemId"] == PROBLEM_ID
    assert built["provenance"]["walkthroughVersion"] == "1.0.0-review-draft"
    assert all(component["type"] != "custom" for component in nodes.values())

    neighbors = {node_id: set() for node_id in nodes}
    actual_pairs = set()
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] and edge["label"] and edge["description"]
        actual_pairs.add((edge["source"], edge["target"]))
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    assert actual_pairs == EXPECTED_CONNECTION_PAIRS

    reached = set()
    pending = deque(["device_fleet"])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    assert reached == nodes.keys()


def test_iot_targets_and_event_planes_remain_explicit_in_guidance():
    raw, _, _ = _load()
    content = "\n".join(step["content"] for step in raw["steps"]).casefold()
    for phrase in (
        "10m+",
        "1m+ messages per second",
        "under five seconds",
        "five years",
        "x.509",
        "tls",
        "event time",
        "idempotent",
        "dead-letter",
        "event grid",
        "not the 1m+ messages/second telemetry stream",
        "not evidence that any quota",
    ):
        assert phrase in content, f"Missing IoT-specific design guidance: {phrase}"
