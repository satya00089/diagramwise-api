"""Frozen-brief, catalog, requirement-coverage, and graph checks for cloud_multi_002."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_multi_002"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": "cloud_multi_002",
    "slug": "build-a-multi-cloud-kubernetes-orchestration-platform",
    "title": "Build a Multi-Cloud Kubernetes Orchestration Platform",
    "description": "Design a unified Kubernetes management solution that orchestrates workloads across multiple cloud providers with centralized monitoring, consistent policies, and disaster recovery.",
    "requirements": [
        "Manage clusters across clouds",
        "Deploy applications uniformly",
        "Implement centralized monitoring",
        "Handle cross-cluster networking",
        "Enforce consistent policies",
        "Implement disaster recovery",
        "Optimize costs across clouds",
        "Provide unified access control",
    ],
    "constraints": [
        "Support 100+ Kubernetes clusters",
        "Unified management interface",
        "Network latency under 100ms",
        "Maintain security compliance",
        "Handle cloud-specific features",
    ],
    "hints": [
        "Use Rancher or Anthos for multi-cluster management",
        "Implement GitOps with Flux or ArgoCD",
        "Use service mesh (Istio) for networking",
        "Centralized logging (ELK, Loki)",
        "Prometheus for unified monitoring",
        "Terraform for infrastructure as code",
    ],
}

EXPECTED_COMPONENTS = {
    "mc2_console": "web-app",
    "mc2_api": "api-gateway",
    "mc2_identity": "auth-service",
    "mc2_control": "backend-server",
    "mc2_state": "database",
    "mc2_secrets": "secrets-manager",
    "mc2_gitops": "deployment-pipeline",
    "mc2_policy": "configuration-management",
    "mc2_fleet": "kubernetes",
    "mc2_eks": "kubernetes",
    "mc2_aks": "kubernetes",
    "mc2_gke": "kubernetes",
    "mc2_mesh": "service-mesh",
    "mc2_network": "vpn-gateway",
    "mc2_monitor": "monitoring",
    "mc2_logs": "log-processing",
    "mc2_compliance": "security-scanning",
    "mc2_backup": "object-storage",
    "mc2_cost": "analytics",
}

EXPECTED_ANCHORS = {
    *(f"legacy-requirement:{index}" for index in range(1, 9)),
    *(f"legacy-constraint:{index}" for index in range(1, 6)),
}
ACTION_TYPES = {"add_component", "add_connection", "decision_point", "scale_trigger"}
CONNECTION_TYPES = {
    "http",
    "tcp",
    "api-call",
    "data-flow",
    "database-connection",
}
EXPECTED_PHASES = [
    ("1. Establish the fleet control plane and trust boundaries", 1, 9),
    ("2. Roll out workloads and policy consistently", 10, 21),
    ("3. Connect clusters and observe fleet health", 22, 29),
    ("4. Prove scale, compliance, cost, and recovery", 30, 46),
]


def _load() -> tuple[dict, GuidedWalkthrough]:
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def _frozen_problem() -> dict:
    return next(
        problem
        for problem in json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
        if problem["id"] == PROBLEM_ID
    )


def _catalog_block(catalog: str, component_type: str) -> str:
    match = re.search(
        rf'(?m)^    id:\s*"{re.escape(component_type)}"\s*,', catalog
    )
    assert match, f"Unknown component catalog ID: {component_type}"
    end = re.search(r"(?m)^  \},\s*$", catalog[match.end() :])
    assert end, f"Could not delimit catalog component {component_type}"
    return catalog[match.start() : match.end() + end.start()]


def test_draft_preserves_the_frozen_brief_and_all_actionable_anchors():
    raw, guide = _load()
    frozen = _frozen_problem()
    intro = guide.steps[0].content

    assert all(FROZEN_BRIEF[key] == frozen[key] for key in FROZEN_BRIEF)
    assert raw["problem_id"] == guide.problem_id == FROZEN_BRIEF["id"]
    assert raw["version"] == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 46
    assert [step.stepNumber for step in guide.steps] == list(range(1, 47))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(value in intro for value in (FROZEN_BRIEF["title"], FROZEN_BRIEF["slug"], FROZEN_BRIEF["description"]))
    assert all(value in intro for value in FROZEN_BRIEF["requirements"])
    assert all(value in intro for value in FROZEN_BRIEF["constraints"])
    assert all(value in intro for value in FROZEN_BRIEF["hints"])

    assert [
        (phase.name, phase.stepRange[0], phase.stepRange[1]) for phase in guide.phases
    ] == EXPECTED_PHASES
    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(
            guide.steps[index - 1].phase == phase.name
            for index in range(start, end + 1)
        )
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    actionable = {
        anchor
        for step in guide.steps
        if step.type in ACTION_TYPES
        for anchor in step.requirementIds
    }
    assert anchors == actionable == EXPECTED_ANCHORS


def test_all_components_use_supported_catalog_types_and_properties():
    raw, _ = _load()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step["type"] == "add_component"
    }
    assert {node_id: row["componentType"] for node_id, row in components.items()} == EXPECTED_COMPONENTS
    assert all(row["componentType"] != "custom-component" for row in components.values())

    for node_id, component in components.items():
        block = _catalog_block(catalog, component["componentType"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        properties = component["properties"]
        assert {"componentName", "purpose"} <= properties.keys(), node_id
        assert properties.keys() <= supported, (
            f"{node_id} has unsupported properties: {sorted(properties.keys() - supported)}"
        )
        assert component["label"] == properties["componentName"]
        assert len(properties["purpose"]) >= 60
        assert component["highlightReason"]


def test_replay_builds_one_connected_fleet_architecture_with_required_paths():
    raw, _ = _load()
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {row["id"] for row in architecture["components"]}
    edges = architecture["connections"]
    assert nodes == set(EXPECTED_COMPONENTS)
    assert len(edges) == 23

    neighbors = {node_id: set() for node_id in nodes}
    directed = {node_id: set() for node_id in nodes}
    edge_ids = set()
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] in CONNECTION_TYPES
        assert edge["label"] and edge["description"]
        assert edge["id"] not in edge_ids
        edge_ids.add(edge["id"])
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
        directed[edge["source"]].add(edge["target"])

    reached = set()
    pending = deque(["mc2_console"])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    assert reached == nodes

    def reaches(source: str, target: str) -> bool:
        visited = set()
        pending_nodes = [source]
        while pending_nodes:
            current = pending_nodes.pop()
            if current == target:
                return True
            if current not in visited:
                visited.add(current)
                pending_nodes.extend(directed[current] - visited)
        return False

    assert reaches("mc2_console", "mc2_control")
    assert all(reaches("mc2_fleet", cluster) for cluster in ("mc2_eks", "mc2_aks", "mc2_gke"))
    assert all(reaches(cluster, "mc2_monitor") for cluster in ("mc2_eks", "mc2_aks", "mc2_gke"))
    assert reaches("mc2_eks", "mc2_mesh") and reaches("mc2_mesh", "mc2_network")
    assert reaches("mc2_compliance", "mc2_gitops")
    assert reaches("mc2_state", "mc2_backup")
    assert reaches("mc2_eks", "mc2_backup")
    assert reaches("mc2_backup", "mc2_fleet")
    assert reaches("mc2_control", "mc2_cost")


def test_explicit_targets_and_hints_are_addressed_without_claiming_slo_proof():
    raw, _ = _load()
    text = json.dumps(raw, ensure_ascii=False).casefold()
    for phrase in (
        "100+ kubernetes clusters",
        "network latency under 100ms",
        "sub-100ms",
        "unified management interface",
        "security compliance",
        "cloud-specific features",
        "rancher or anthos",
        "flux or argocd",
        "istio",
        "centralized logging (elk, loki)",
        "prometheus for unified monitoring",
        "terraform for infrastructure as code",
        "or establish browser, ai-assessment, or production verification",
    ):
        assert phrase in text, f"Missing explicit constraint, hint, or verification caveat: {phrase}"

    assert "custom-component" not in {
        step["component"]["componentType"]
        for step in raw["steps"]
        if step["type"] == "add_component"
    }


def test_portability_identity_placement_network_and_recovery_contract_are_explicit():
    raw, _ = _load()
    steps = {step["id"]: step for step in raw["steps"]}

    assert "not a replacement for those provider control planes" in steps["mc2_05_control"]["content"]
    for provider_identity in ("AWS IAM", "Microsoft Entra ID", "Google Cloud IAM"):
        assert provider_identity in steps["mc2_04_identity"]["content"]
    assert "not a single cross-cloud Kubernetes scheduler" in steps["mc2_30_scale"]["content"]
    assert "service mesh supplies service identity" in steps["mc2_23_network"]["content"]
    recovery = steps["mc2_46_restore"]["content"]
    assert "operator-approved recovery contract" in recovery
    assert "not transparent active-active cross-cloud failover" in recovery
    assert "RTO, or RPO" in recovery


def test_audited_actions_have_precise_requirement_and_constraint_anchors():
    raw, _ = _load()
    steps = {step["id"]: set(step["requirementIds"]) for step in raw["steps"]}
    expected = {
        "mc2_04_identity": {"legacy-requirement:8", "legacy-constraint:4"},
        "mc2_13_fleet_manager": {
            "legacy-requirement:1", "legacy-constraint:1", "legacy-constraint:5"
        },
        "mc2_14_eks": {"legacy-requirement:1", "legacy-constraint:5"},
        "mc2_15_aks": {"legacy-requirement:1", "legacy-constraint:5"},
        "mc2_16_gke": {"legacy-requirement:1", "legacy-constraint:5"},
        "mc2_23_network": {
            "legacy-requirement:4", "legacy-constraint:3",
            "legacy-constraint:4", "legacy-constraint:5"
        },
        "mc2_30_scale": {"legacy-requirement:1", "legacy-constraint:1"},
        "mc2_31_latency": {"legacy-requirement:4", "legacy-constraint:3"},
        "mc2_34_cost": {"legacy-requirement:7"},
        "mc2_46_restore": {
            "legacy-requirement:6", "legacy-requirement:1", "legacy-requirement:5",
            "legacy-constraint:4", "legacy-constraint:5"
        },
    }
    assert {step_id: steps[step_id] for step_id in expected} == expected
