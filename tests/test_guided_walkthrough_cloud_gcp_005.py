"""Focused structural contract for the cloud_gcp_005 local review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_gcp_005"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

REQUIREMENTS = [
    "Manage Kubernetes across clouds",
    "Implement consistent policies",
    "Deploy applications anywhere",
    "Monitor multi-cloud resources",
    "Implement service mesh",
    "Ensure security compliance",
    "Synchronize configurations",
    "Handle hybrid connectivity",
]
CONSTRAINTS = [
    "Unified management interface",
    "Support AWS, Azure, and on-prem",
    "Network latency under 100ms",
    "Implement zero-trust networking",
    "Maintain policy consistency",
]
HINTS = [
    "Anthos for multi-cloud management",
    "GKE for Google Cloud clusters",
    "Anthos Service Mesh for networking",
    "Config Sync for GitOps",
    "Anthos Config Management for policies",
    "Cloud Monitoring for observability",
]
FROZEN_BRIEF = (
    "Title: Design a Secure Multi-Cloud Kubernetes Architecture\n"
    "Description: Design a multi-cloud Kubernetes platform that manages workloads across multiple cloud providers "
    "with consistent policies, service mesh, and centralized configuration.\n"
    "Requirements:\n"
    "1. Manage Kubernetes across clouds\n"
    "2. Implement consistent policies\n"
    "3. Deploy applications anywhere\n"
    "4. Monitor multi-cloud resources\n"
    "5. Implement service mesh\n"
    "6. Ensure security compliance\n"
    "7. Synchronize configurations\n"
    "8. Handle hybrid connectivity\n"
    "Constraints:\n"
    "1. Unified management interface\n"
    "2. Support AWS, Azure, and on-prem\n"
    "3. Network latency under 100ms\n"
    "4. Implement zero-trust networking\n"
    "5. Maintain policy consistency\n"
    "Hints:\n"
    "1. Anthos for multi-cloud management\n"
    "2. GKE for Google Cloud clusters\n"
    "3. Anthos Service Mesh for networking\n"
    "4. Config Sync for GitOps\n"
    "5. Anthos Config Management for policies\n"
    "6. Cloud Monitoring for observability"
)


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"{step_id}: unknown catalog component {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), f"{step_id}: incomplete catalog entry for {component_type}"
    return catalog[match.start() : block_end]


def catalog_options(block: str, key: str) -> set[str] | None:
    marker = re.search(rf'\bkey:\s*"{re.escape(key)}"', block)
    if not marker:
        return None
    remainder = block[marker.end() :]
    next_property = re.search(r'\bkey:\s*"', remainder)
    section = remainder[: next_property.start()] if next_property else remainder
    options = re.search(r"options:\s*\[([\s\S]*?)\]", section)
    return set(re.findall(r'"([^"]+)"', options.group(1))) if options else None


def test_schema_step_order_phase_ranges_and_action_payloads():
    raw, guide = load_guide()
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 48
    assert [step.stepNumber for step in guide.steps] == list(range(1, 49))
    assert len({step.id for step in guide.steps}) == guide.totalSteps

    expected_start = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == expected_start
        assert start <= end <= guide.totalSteps
        assert all(step.phase == phase.name for step in guide.steps[start - 1 : end])
        expected_start = end + 1
    assert expected_start == guide.totalSteps + 1

    allowed_types = {"explanation", "add_component", "add_connection", "decision_point"}
    assert {step.type for step in guide.steps} == allowed_types
    for step in guide.steps:
        assert step.title and step.content and step.requirementIds
        if step.type == "add_component":
            assert step.component is not None
            assert set(step.component.position) == {"x", "y"}
            assert step.component.highlightReason
        elif step.type == "add_connection":
            assert step.connection is not None
            assert step.connection.label and step.connection.description
        elif step.type == "decision_point":
            assert step.decision is not None and step.componentUpdate is not None
            assert step.decision.question and step.decision.chosen and step.decision.chosenReason
            assert len(step.decision.alternatives) >= 2
            assert all(option.option and option.tradeoff for option in step.decision.alternatives)

    assert raw["totalSteps"] == len(raw["steps"])


def test_exact_frozen_live_brief_and_requirement_traceability():
    raw, guide = load_guide()
    assert raw["steps"][0]["content"] == FROZEN_BRIEF

    expected_ids = {
        *(f"legacy-requirement:{index}" for index in range(1, len(REQUIREMENTS) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(CONSTRAINTS) + 1)),
    }
    mapped_ids = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert mapped_ids == expected_ids

    anchors = {
        "legacy-requirement:1": "gcp005_fleet_to_gke",
        "legacy-requirement:2": "gcp005_config_policy_decision",
        "legacy-requirement:3": "gcp005_sync_to_gke",
        "legacy-requirement:4": "gcp005_monitoring",
        "legacy-requirement:5": "gcp005_anthos_mesh",
        "legacy-requirement:6": "gcp005_policy_manager",
        "legacy-requirement:7": "gcp005_git_to_sync",
        "legacy-requirement:8": "gcp005_hybrid_connectivity",
        "legacy-constraint:1": "gcp005_admin_console",
        "legacy-constraint:2": "gcp005_aws_cluster",
        "legacy-constraint:3": "gcp005_latency_decision",
        "legacy-constraint:4": "gcp005_zero_trust_decision",
        "legacy-constraint:5": "gcp005_policy_manager",
    }
    steps = {step.id: step for step in guide.steps}
    for requirement_id, step_id in anchors.items():
        assert requirement_id in steps[step_id].requirementIds
        assert steps[step_id].type != "explanation"


def test_portability_security_and_network_anchors_are_qualified():
    raw, guide = load_guide()
    steps = {step.id: step for step in guide.steps}

    # Listing Kubernetes distributions/environments is not proof that apps run anywhere.
    for step_id in (
        "gcp005_gke",
        "gcp005_aws_cluster",
        "gcp005_azure_cluster",
        "gcp005_onprem_cluster",
    ):
        assert "legacy-requirement:3" not in steps[step_id].requirementIds

    # The GitOps application path is the closest matching action, but it must remain conditional.
    for step_id in (
        "gcp005_sync_to_gke",
        "gcp005_sync_to_aws",
        "gcp005_sync_to_azure",
        "gcp005_sync_to_onprem",
    ):
        step = steps[step_id]
        assert set(step.requirementIds) == {
            "legacy-requirement:7",
            "legacy-requirement:3",
        }
        assert "candidate" in step.content.lower()
        assert "not proof" in step.content.lower() or "does not prove" in step.content.lower()
        assert "portab" in step.content.lower()

    # Policy evaluation supports security review; mesh identity is not itself compliance evidence.
    assert "legacy-requirement:6" in steps["gcp005_policy_manager"].requirementIds
    for step_id in (
        "gcp005_anthos_mesh",
        "gcp005_mesh_to_gke",
        "gcp005_mesh_to_aws",
        "gcp005_mesh_to_azure",
        "gcp005_mesh_to_onprem",
        "gcp005_zero_trust_decision",
    ):
        assert "legacy-requirement:6" not in steps[step_id].requirementIds
    assert "legacy-constraint:4" not in steps["gcp005_identity"].requirementIds
    assert "legacy-constraint:4" not in steps["gcp005_identity_to_console"].requirementIds
    assert "legacy-constraint:4" not in steps["gcp005_identity_to_fleet"].requirementIds

    # Topology is not latency evidence; the explicit measurement decision owns that target.
    for step_id in (
        "gcp005_hybrid_connectivity",
        "gcp005_onprem_to_hybrid",
        "gcp005_hybrid_to_gke",
        "gcp005_hybrid_to_aws",
        "gcp005_hybrid_to_azure",
    ):
        assert "legacy-constraint:3" not in steps[step_id].requirementIds
    assert "legacy-constraint:3" in steps["gcp005_latency_decision"].requirementIds

    identity_text = " ".join(
        steps[step_id].content
        for step_id in ("gcp005_identity", "gcp005_identity_to_console", "gcp005_identity_to_fleet")
    ).lower()
    assert "provider-specific" in identity_text
    assert "federation" in identity_text
    assert "least-privilege" in identity_text

    mesh = steps["gcp005_anthos_mesh"]
    assert mesh.component.properties["mtls"] is True
    assert "not deployed enforcement" in mesh.content.lower()
    assert "trust-domain" in mesh.content.lower()
    network = steps["gcp005_hybrid_connectivity"]
    assert "firewall/egress" in network.content.lower()
    assert "does not create underlying network reachability" in network.content.lower()

    # The walkthrough makes no uptime or compliance-certification claim absent from the brief.
    all_text = json.dumps(raw).lower()
    assert not re.search(r"\b(?:99\.?9+%|100%|\d+% uptime)\b", all_text)
    assert "does not itself establish regulatory compliance" in all_text


def test_catalog_component_types_properties_and_explicit_generic_custom_usage():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step.get("component")
    }
    assert len(components) == 13
    assert {
        node_id for node_id, component in components.items()
        if component["componentType"] == "custom-component"
    } == {
        "gcp005_fleet_manager",
        "gcp005_git_source",
        "gcp005_hybrid_connectivity",
    }

    for step in raw["steps"]:
        component = step.get("component")
        update = step.get("componentUpdate")
        if component:
            component_type = component["componentType"]
            properties = component["properties"]
            node_id = component["nodeId"]
            assert properties["componentName"] == component["label"]
            assert len(properties["purpose"]) >= 45
        elif update:
            node_id = update["nodeId"]
            component_type = components[node_id]["componentType"]
            properties = update["properties"]
        else:
            continue

        block = catalog_block(catalog, component_type, step["id"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert set(properties) <= supported, f"{step['id']}: unsupported properties {set(properties) - supported}"
        for key, value in properties.items():
            options = catalog_options(block, key)
            if options is not None:
                assert value in options, f"{step['id']}: {key}={value!r} is not a catalog option"

    assert components["gcp005_gke"]["properties"]["distribution"] == "GKE"
    assert "distribution" not in components["gcp005_aws_cluster"]["properties"]
    assert "distribution" not in components["gcp005_azure_cluster"]["properties"]
    assert "distribution" not in components["gcp005_onprem_cluster"]["properties"]


def test_replay_builds_connected_architecture_and_applies_decisions():
    raw, _ = load_guide()
    built = build_architecture(raw)
    architecture = built["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    edges = architecture["connections"]

    assert len(nodes) == 13
    assert len(edges) == 29
    assert len(built["acceptedDecisions"]) == 4
    assert len(built["appliedStepIds"]) == 46
    assert len(built["explanationOnlyStepIds"]) == 2
    assert built["provenance"]["problemId"] == PROBLEM_ID
    assert built["provenance"]["walkthroughVersion"] == "1.0-review-draft"

    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] and edge["description"]
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])

    visited = set()
    pending = deque(["gcp005_admin_console"])
    while pending:
        node_id = pending.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        pending.extend(neighbors[node_id] - visited)
    assert visited == set(nodes)
