"""Focused contract tests for the confidential-computing review draft."""

from __future__ import annotations

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_azure_011"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": PROBLEM_ID,
    "slug": "design-a-confidential-computing-solution",
    "title": "Design a Confidential Computing Solution",
    "description": (
        "Design a secure compute environment that protects data in use with "
        "hardware-based encryption, verifies compute integrity, and manages "
        "encryption keys securely."
    ),
    "category": "Azure - Security",
    "difficulty": "Very Hard",
    "domain": "infra",
    "estimated_time": "90+ minutes",
    "companies": ["Microsoft", "Intel", "Financial Services"],
    "requirements": [
        "Protect data during processing",
        "Use hardware-based trusted execution",
        "Verify enclave integrity",
        "Manage encryption keys securely",
        "Process sensitive workloads",
        "Implement remote attestation",
        "Ensure data confidentiality",
        "Comply with regulatory requirements",
    ],
    "constraints": [
        "Zero data exposure during computation",
        "Support multi-party computation",
        "Minimal performance overhead",
        "Protect against insider threats",
        "Maintain compliance with GDPR, HIPAA",
    ],
    "hints": [
        "Confidential VMs with SGX/SEV",
        "Azure Attestation for verification",
        "Key Vault with HSM",
        "Confidential Containers on AKS",
        "Always Encrypted for databases",
        "Security Center for monitoring",
    ],
    "tags": ["azure", "confidential-computing", "security", "tee", "encryption"],
}

EXPECTED_COMPONENT_TYPES = {
    "azure011_data_owners": "custom-component",
    "azure011_api_gateway": "api-gateway",
    "azure011_identity": "auth-service",
    "azure011_job_control": "backend-server",
    "azure011_job_queue": "queue",
    "azure011_share_store": "object-storage",
    "azure011_confidential_mpc_peers": "custom-component",
    "azure011_maa": "custom-component",
    "azure011_key_vault": "secrets-manager",
    "azure011_result_store": "database",
    "azure011_monitoring": "monitoring",
}

EXPECTED_CONNECTION_PAIRS = {
    ("azure011_data_owners", "azure011_api_gateway"),
    ("azure011_api_gateway", "azure011_identity"),
    ("azure011_identity", "azure011_api_gateway"),
    ("azure011_api_gateway", "azure011_job_control"),
    ("azure011_job_control", "azure011_job_queue"),
    ("azure011_job_queue", "azure011_confidential_mpc_peers"),
    ("azure011_data_owners", "azure011_share_store"),
    ("azure011_job_control", "azure011_share_store"),
    ("azure011_job_queue", "azure011_confidential_mpc_peers"),
    ("azure011_confidential_mpc_peers", "azure011_maa"),
    ("azure011_maa", "azure011_confidential_mpc_peers"),
    ("azure011_confidential_mpc_peers", "azure011_key_vault"),
    ("azure011_key_vault", "azure011_confidential_mpc_peers"),
    ("azure011_share_store", "azure011_confidential_mpc_peers"),
    ("azure011_job_control", "azure011_result_store"),
    ("azure011_confidential_mpc_peers", "azure011_result_store"),
    ("azure011_job_control", "azure011_monitoring"),
    ("azure011_confidential_mpc_peers", "azure011_monitoring"),
    ("azure011_maa", "azure011_monitoring"),
    ("azure011_key_vault", "azure011_monitoring"),
}


def _load() -> tuple[dict, dict, GuidedWalkthrough]:
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    matches = [problem for problem in problems if problem["id"] == PROBLEM_ID]
    assert len(matches) == 1
    return raw, matches[0], GuidedWalkthrough.model_validate(raw)


def _catalog_blocks() -> dict[str, str]:
    source = CATALOG_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        r'^  \{\n    id: "(?P<id>[^"]+)",(?P<body>.*?)^  \},?',
        re.MULTILINE | re.DOTALL,
    )
    return {match.group("id"): match.group(0) for match in pattern.finditer(source)}


def test_frozen_brief_matches_the_live_item_snapshot_and_is_still_unpublished():
    _, problem, _ = _load()

    assert {key: problem[key] for key in FROZEN_BRIEF} == FROZEN_BRIEF
    assert problem["has_guided_walkthrough"] is False


def test_draft_schema_steps_and_phase_ranges_are_complete_and_ordered():
    raw, _, guide = _load()

    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert raw["totalSteps"] == len(guide.steps) == 43
    assert [step.stepNumber for step in guide.steps] == list(range(1, 44))
    assert len({step.id for step in guide.steps}) == len(guide.steps)
    assert [
        (phase.name, phase.stepRange[0], phase.stepRange[1]) for phase in guide.phases
    ] == [
        ("Define participants, trust boundaries, and workload targets", 1, 10),
        ("Separate job metadata from encrypted participant inputs", 11, 20),
        ("Attest execution and gate scoped key release", 21, 32),
        ("Release minimized results and prove security and compliance objectives", 33, 43),
    ]

    expected_start = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == expected_start
        assert start <= end
        assert all(
            step.phase == phase.name
            for step in guide.steps
            if start <= step.stepNumber <= end
        )
        expected_start = end + 1
    assert expected_start == guide.totalSteps + 1


def test_every_live_requirement_and_constraint_is_anchored_to_a_replayable_graph_action():
    raw, _, _ = _load()
    expected = {
        *(f"legacy-requirement:{number}" for number in range(1, 9)),
        *(f"legacy-constraint:{number}" for number in range(1, 6)),
    }
    all_anchors = {
        anchor for step in raw["steps"] for anchor in step.get("requirementIds", [])
    }
    graph_action_anchors = {
        anchor
        for step in raw["steps"]
        if step["type"] in {"add_component", "add_connection"}
        for anchor in step.get("requirementIds", [])
    }

    assert all_anchors == expected
    assert graph_action_anchors == expected
    assert all(
        step["type"] in {"explanation", "decision_point", "scale_trigger", "add_component", "add_connection"}
        for step in raw["steps"]
    )


def test_catalog_types_and_properties_are_valid_and_custom_nodes_are_justified():
    raw, _, _ = _load()
    catalog = _catalog_blocks()
    component_steps = [step for step in raw["steps"] if step["type"] == "add_component"]
    actual_types = {
        step["component"]["nodeId"]: step["component"]["componentType"]
        for step in component_steps
    }

    assert actual_types == EXPECTED_COMPONENT_TYPES
    for step in component_steps:
        component = step["component"]
        component_type = component["componentType"]
        assert component_type in catalog, f"Unknown catalog type {component_type!r}"
        properties = component["properties"]
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', catalog[component_type]))
        assert set(properties) <= supported, (
            f"Unsupported {component_type} properties: {set(properties) - supported}"
        )
        assert properties["componentName"] == component["label"]
        assert properties["purpose"]

    custom_components = {
        step["component"]["nodeId"]: step["component"]
        for step in component_steps
        if step["component"]["componentType"] == "custom-component"
    }
    assert set(custom_components) == {
        "azure011_data_owners",
        "azure011_confidential_mpc_peers",
        "azure011_maa",
    }
    custom_explanations = " ".join(
        component["properties"]["purpose"] + " " + component["properties"].get("notes", "")
        for component in custom_components.values()
    ).casefold()
    assert "catalog has no" in custom_explanations


def test_ordered_replay_builds_the_expected_connected_end_to_end_architecture():
    raw, _, _ = _load()
    replay = json.loads(json.dumps(raw))
    replay["steps"].reverse()
    built = build_architecture(replay)
    ordered_steps = sorted(raw["steps"], key=lambda item: item["stepNumber"])
    expected_actions = [
        step["id"]
        for step in ordered_steps
        if step["type"] in {"add_component", "add_connection"}
    ]

    assert built["appliedStepIds"] == expected_actions
    architecture = built["architecture"]
    nodes = {node["id"] for node in architecture["components"]}
    edges = architecture["connections"]
    assert nodes == set(EXPECTED_COMPONENT_TYPES)
    assert len(edges) == len(EXPECTED_CONNECTION_PAIRS)
    assert built["provenance"]["problemId"] == PROBLEM_ID
    assert built["provenance"]["walkthroughVersion"] == "1.0.0-review-draft"

    pairs = set()
    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] and edge["label"] and edge["description"]
        pairs.add((edge["source"], edge["target"]))
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    assert pairs == EXPECTED_CONNECTION_PAIRS

    reached = set()
    pending = deque(["azure011_data_owners"])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    assert reached == nodes


def test_walkthrough_explains_mpc_tee_limits_native_key_release_and_compliance_gates():
    raw, _, _ = _load()
    content = json.dumps(raw).casefold()
    for phrase in (
        "cryptographic mpc",
        "confidential vm",
        "remote attestation",
        "secure key release",
        "fail closed",
        "gdpr",
        "hipaa",
        "side-channel",
        "owner-approved",
        "targets tbd",
    ):
        assert phrase in content, f"Missing security or scope caveat: {phrase}"

