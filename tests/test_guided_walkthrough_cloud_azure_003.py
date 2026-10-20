"""Focused structural and frozen-brief checks for the hybrid Azure draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_azure_003"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

TITLE = "Design a Hybrid Cloud Infrastructure Solution"
DESCRIPTION = (
    "Design a hybrid infrastructure that manages on-premises and cloud resources, "
    "implements consistent governance, and provides unified monitoring."
)
REQUIREMENTS = [
    "Manage on-premises and cloud resources",
    "Deploy services across hybrid environment",
    "Implement consistent governance",
    "Monitor hybrid infrastructure",
    "Apply Azure policies everywhere",
    "Secure connectivity between environments",
    "Run Azure services on-premises",
    "Maintain compliance across environments",
]
CONSTRAINTS = [
    "Network latency under 50ms",
    "Unified management interface",
    "Support air-gapped environments",
    "Implement zero-trust security",
    "Handle network failures gracefully",
]
HINTS = [
    "Azure Arc for hybrid management",
    "Azure Stack for on-premises cloud",
    "ExpressRoute for private connectivity",
    "Azure Monitor for unified monitoring",
    "Azure Policy for governance",
    "Azure Sentinel for security",
]
EXPECTED_ANCHORS = {
    *(f"legacy-requirement:{number}" for number in range(1, 9)),
    *(f"legacy-constraint:{number}" for number in range(1, 6)),
}
GRAPH_ACTION_TYPES = {"add_component", "add_connection"}
EXPECTED_COMPONENT_TYPES = {
    "onprem_zone": "security-boundary",
    "onprem_network": "vpc-network",
    "azure_network": "vpc-network",
    "stack_hci": "container-orchestrator",
    "expressroute": "custom-component",
    "expressroute_gateway": "custom-component",
    "vpn_backup": "vpn-gateway",
    "azure_firewall": "firewall",
    "azure_aks": "container-orchestrator",
    "offline_ops": "custom-component",
    "local_log_buffer": "custom-component",
    "arc_agents": "custom-component",
    "arc_control_plane": "custom-component",
    "entra_identity": "custom-component",
    "azure_policy": "custom-component",
    "azure_monitor": "monitoring",
    "sentinel": "custom-component",
}
EXPECTED_CONNECTION_PAIRS = {
    ("onprem_zone", "onprem_network"),
    ("onprem_network", "expressroute"),
    ("expressroute", "expressroute_gateway"),
    ("expressroute_gateway", "azure_network"),
    ("onprem_network", "vpn_backup"),
    ("vpn_backup", "azure_network"),
    ("azure_network", "azure_firewall"),
    ("azure_network", "azure_aks"),
    ("azure_firewall", "azure_aks"),
    ("onprem_network", "stack_hci"),
    ("offline_ops", "stack_hci"),
    ("stack_hci", "local_log_buffer"),
    ("stack_hci", "arc_agents"),
    ("azure_aks", "arc_agents"),
    ("arc_agents", "arc_control_plane"),
    ("entra_identity", "arc_control_plane"),
    ("azure_policy", "arc_control_plane"),
    ("arc_control_plane", "arc_agents"),
    ("arc_agents", "azure_monitor"),
    ("local_log_buffer", "azure_monitor"),
    ("azure_aks", "azure_monitor"),
    ("azure_monitor", "sentinel"),
}
EXPECTED_GRAPH_ACTION_ANCHORS = {
    "hybrid_04": {"legacy-requirement:1", "legacy-constraint:4"},
    "hybrid_05": {"legacy-requirement:1", "legacy-requirement:6"},
    "hybrid_06": {
        "legacy-requirement:1",
        "legacy-requirement:2",
        "legacy-requirement:6",
    },
    "hybrid_07": {
        "legacy-requirement:2",
        "legacy-requirement:7",
        "legacy-constraint:3",
        "legacy-constraint:5",
    },
    "hybrid_08": {"legacy-requirement:6", "legacy-constraint:1"},
    "hybrid_09": {"legacy-requirement:6", "legacy-constraint:1"},
    "hybrid_10": {"legacy-requirement:6", "legacy-constraint:5"},
    "hybrid_12": {"legacy-requirement:6", "legacy-constraint:4"},
    "hybrid_13": {"legacy-requirement:1", "legacy-constraint:4"},
    "hybrid_14": {"legacy-requirement:6", "legacy-constraint:1"},
    "hybrid_15": {"legacy-requirement:6", "legacy-constraint:1"},
    "hybrid_16": {"legacy-requirement:6", "legacy-constraint:1"},
    "hybrid_17": {"legacy-requirement:6", "legacy-constraint:5"},
    "hybrid_18": {"legacy-requirement:6", "legacy-constraint:5"},
    "hybrid_19": {"legacy-requirement:6"},
    "hybrid_21": {"legacy-requirement:2"},
    "hybrid_22": {
        "legacy-requirement:3",
        "legacy-constraint:3",
        "legacy-constraint:5",
    },
    "hybrid_23": {
        "legacy-requirement:4",
        "legacy-constraint:3",
        "legacy-constraint:5",
    },
    "hybrid_24": {"legacy-requirement:1", "legacy-constraint:2"},
    "hybrid_25": {"legacy-requirement:1", "legacy-constraint:2"},
    "hybrid_26": {
        "legacy-requirement:1",
        "legacy-constraint:4",
        "legacy-constraint:3",
    },
    "hybrid_27": {
        "legacy-requirement:2",
        "legacy-requirement:7",
        "legacy-constraint:3",
        "legacy-constraint:5",
    },
    "hybrid_28": {
        "legacy-requirement:3",
        "legacy-requirement:7",
        "legacy-constraint:3",
    },
    "hybrid_29": {
        "legacy-requirement:4",
        "legacy-constraint:3",
        "legacy-constraint:5",
    },
    "hybrid_30": {"legacy-requirement:2"},
    "hybrid_31": {"legacy-requirement:6"},
    "hybrid_32": {"legacy-requirement:1", "legacy-constraint:2"},
    "hybrid_33": {"legacy-requirement:1", "legacy-constraint:2"},
    "hybrid_34": {"legacy-requirement:1", "legacy-constraint:2"},
    "hybrid_35": {
        "legacy-requirement:1",
        "legacy-constraint:4",
        "legacy-constraint:3",
    },
    "hybrid_36": {
        "legacy-requirement:3",
        "legacy-requirement:5",
        "legacy-requirement:8",
    },
    "hybrid_37": {
        "legacy-requirement:3",
        "legacy-requirement:5",
        "legacy-requirement:8",
    },
    "hybrid_38": {
        "legacy-requirement:1",
        "legacy-requirement:3",
        "legacy-requirement:5",
        "legacy-requirement:8",
        "legacy-constraint:2",
        "legacy-constraint:3",
    },
    "hybrid_39": {"legacy-requirement:4"},
    "hybrid_40": {
        "legacy-requirement:4",
        "legacy-requirement:8",
        "legacy-constraint:3",
    },
    "hybrid_41": {"legacy-requirement:4"},
    "hybrid_42": {
        "legacy-requirement:4",
        "legacy-requirement:8",
        "legacy-constraint:3",
        "legacy-constraint:5",
    },
    "hybrid_43": {"legacy-requirement:4"},
    "hybrid_44": {"legacy-requirement:4", "legacy-requirement:8"},
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


def test_frozen_brief_matches_exact_target_and_flag_is_false():
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


def test_pydantic_phase_integrity_and_action_based_anchor_coverage():
    raw, _, guide = _load()
    assert guide.totalSteps == len(guide.steps) == 53
    assert 35 <= guide.totalSteps <= 60
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert [
        (phase.name, phase.stepRange[0], phase.stepRange[1]) for phase in guide.phases
    ] == [
        ("Frame the hybrid boundary and unknowns", 1, 7),
        ("Build private connectivity with an explicit fallback", 8, 20),
        ("Place workloads and establish hybrid management", 21, 35),
        ("Apply governance and unify security telemetry", 36, 46),
        ("Define failure behavior, scale signals, and proof", 47, 53),
    ]

    covered_numbers = []
    for phase in guide.phases:
        start, end = phase.stepRange
        expected_start = covered_numbers[-1] + 1 if covered_numbers else 1
        assert start == expected_start
        covered_numbers.extend(range(start, end + 1))
        assert all(
            step.phase == phase.name
            for step in guide.steps
            if start <= step.stepNumber <= end
        )
    assert covered_numbers == list(range(1, guide.totalSteps + 1))

    anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert anchors == EXPECTED_ANCHORS
    graph_action_anchors = {
        step["id"]: set(step.get("requirementIds", []))
        for step in raw["steps"]
        if step["type"] in GRAPH_ACTION_TYPES
    }
    assert graph_action_anchors == EXPECTED_GRAPH_ACTION_ANCHORS
    assert set().union(*graph_action_anchors.values()) == EXPECTED_ANCHORS

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

    opening = raw["steps"][0]["content"].casefold()
    assert "supplied brief" in opening and "assumptions for this draft" in opening
    assert "p95" in raw["steps"][1]["decision"]["chosen"]
    assert "no permitted external path" in raw["steps"][2]["content"]
    assert "proposal—not evidence" in raw["steps"][-1]["content"]


def test_assumptions_and_azure_service_choices_are_not_presented_as_guarantees():
    raw, _, _ = _load()
    by_id = {step["id"]: step for step in raw["steps"]}

    opening = by_id["hybrid_01"]["content"].casefold()
    assert "assumptions for this draft" in opening
    assert "actual site mix" in opening
    assert "no availability slo is specified" in opening
    assert "rto" in opening and "rpo" in opening
    assert "candidate provider-specific choices" in opening
    assert "does not guarantee" in opening

    latency = by_id["hybrid_02"]
    assert "only stated latency target" in latency["content"]
    assert "under 50ms" in latency["content"]
    assert "acceptance assumptions" in latency["content"]
    assert "diagnostic distributions only" in latency["content"]
    assert "not separate pass targets" in latency["content"]
    assert "required percentile open" in latency["decision"]["chosen"]

    assert "candidate path" in by_id["hybrid_09"]["content"]
    assert "does not itself guarantee" in by_id["hybrid_09"]["content"]
    assert "does not guarantee" in by_id["hybrid_10"]["content"]
    assert "does not guarantee one complete interface" in by_id["hybrid_25"]["component"]["properties"]["purpose"]
    assert "azure policy name alone guarantees none" in by_id["hybrid_36"]["content"].casefold()
    assert "none are guaranteed by this diagram" in by_id["hybrid_39"]["content"]
    assert "not guaranteed by this connection" in by_id["hybrid_37"]["connection"]["description"]
    assert "remain unverified" in by_id["hybrid_38"]["connection"]["description"]
    assert "not specified in the brief" in by_id["hybrid_49"]["scaleTrigger"]["action"]
    assert "if owners define" in by_id["hybrid_48"]["scaleTrigger"]["action"].casefold()
    assert "operating assumption to confirm" in by_id["hybrid_51"]["content"].casefold()
    assert "no service-availability" in by_id["hybrid_51"]["content"]


def test_catalog_component_types_and_properties_are_supported():
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
    assert set(EXPECTED_COMPONENT_TYPES.values()) <= {
        "security-boundary",
        "vpc-network",
        "container-orchestrator",
        "custom-component",
        "vpn-gateway",
        "firewall",
        "monitoring",
    }

    for component in additions.values():
        assert set(component["position"]) == {"x", "y"}
        assert component["properties"]["componentName"] == component["label"]
        assert len(component["properties"]["purpose"]) >= 80
        _assert_supported_properties(component["componentType"], component["properties"], catalog)


def test_ordered_replay_has_expected_edges_and_one_connected_architecture():
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
    pending = deque(["onprem_zone"])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    assert reached == nodes.keys()
