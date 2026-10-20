"""Frozen-brief, catalog, and replay checks for the local AWS security draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_aws_005"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "title": "Design a Secure Multi-Tier Web Application",
    "description": "Design a secure web application architecture with network isolation, protection against common web attacks, auto-scaling capabilities, and secure database access.",
    "requirements": [
        "Implement network isolation",
        "Protect against common web attacks",
        "Auto-scale based on traffic",
        "Secure database access",
        "Encrypt data in transit and at rest",
        "Implement least privilege access",
        "Log all security events",
        "Handle SSL/TLS termination",
    ],
    "constraints": [
        "No direct internet access to database",
        "All traffic must be encrypted",
        "Support 99.95% availability",
        "Comply with security best practices",
        "Block SQL injection and XSS attacks",
    ],
    "hints": [
        "VPC with public and private subnets",
        "Application Load Balancer for traffic",
        "Auto Scaling Group for web tier",
        "RDS in private subnet with security groups",
        "AWS WAF for web application firewall",
        "KMS for encryption key management",
    ],
}

STEP_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "decision_point",
    "scale_trigger",
    "update_component",
}
CONNECTION_TYPES = {"http", "database-connection", "api-call", "event-stream"}
EXPECTED_COMPONENT_TYPES = {
    "secure_vpc": "vpc-network",
    "secure_clients": "web-app",
    "secure_waf": "firewall",
    "secure_alb": "loadbalancer",
    "secure_web_tier": "webserver",
    "secure_rds": "database",
    "secure_kms": "custom-component",
    "secure_cloudwatch": "monitoring",
    "secure_cloudtrail": "custom-component",
}
EXPECTED_STEP_ANCHORS = {
    "secure_03": {"legacy-requirement:1", "legacy-requirement:4", "legacy-constraint:1"},
    "secure_05": {"legacy-requirement:1", "legacy-constraint:1"},
    "secure_06": {"legacy-requirement:4", "legacy-requirement:5", "legacy-constraint:2"},
    "secure_07": {"legacy-requirement:2", "legacy-requirement:7", "legacy-constraint:5"},
    "secure_08": {"legacy-requirement:8"},
    "secure_09": {"legacy-requirement:1", "legacy-requirement:3"},
    "secure_10": {
        "legacy-requirement:1",
        "legacy-requirement:4",
        "legacy-requirement:5",
        "legacy-constraint:1",
        "legacy-constraint:2",
        "legacy-constraint:3",
    },
    "secure_11": {"legacy-requirement:5", "legacy-constraint:4"},
    "secure_12": {"legacy-requirement:7", "legacy-constraint:4"},
    "secure_13": {"legacy-requirement:7", "legacy-constraint:4"},
    "secure_14": {
        "legacy-requirement:2",
        "legacy-requirement:5",
        "legacy-constraint:2",
        "legacy-constraint:5",
    },
    "secure_15": {"legacy-requirement:2", "legacy-constraint:5"},
    "secure_16": {
        "legacy-requirement:5",
        "legacy-constraint:2",
        "legacy-constraint:3",
    },
    "secure_17": {
        "legacy-requirement:1",
        "legacy-requirement:4",
        "legacy-requirement:5",
        "legacy-requirement:6",
        "legacy-constraint:1",
        "legacy-constraint:2",
    },
    "secure_18": {"legacy-requirement:5", "legacy-constraint:4"},
    "secure_19": {"legacy-requirement:7", "legacy-constraint:4"},
    "secure_20": {"legacy-requirement:7", "legacy-constraint:4"},
    "secure_21": {"legacy-requirement:7", "legacy-constraint:4"},
    "secure_22": {"legacy-requirement:7", "legacy-constraint:4"},
    "secure_23": {
        "legacy-requirement:1",
        "legacy-requirement:4",
        "legacy-requirement:5",
        "legacy-constraint:1",
        "legacy-constraint:2",
        "legacy-constraint:3",
    },
    "secure_24": {
        "legacy-requirement:5",
        "legacy-requirement:6",
        "legacy-constraint:2",
        "legacy-constraint:4",
    },
    "secure_25": {
        "legacy-requirement:2",
        "legacy-requirement:7",
        "legacy-constraint:4",
        "legacy-constraint:5",
    },
    "secure_26": {
        "legacy-requirement:5",
        "legacy-requirement:8",
        "legacy-constraint:2",
    },
    "secure_27": {
        "legacy-requirement:5",
        "legacy-requirement:6",
        "legacy-constraint:4",
    },
    "secure_28": {"legacy-requirement:6", "legacy-constraint:4"},
    "secure_29": {"legacy-requirement:7", "legacy-constraint:4"},
    "secure_30": {
        "legacy-requirement:6",
        "legacy-requirement:7",
        "legacy-constraint:4",
    },
    "secure_31": {"legacy-requirement:3"},
    "secure_32": {"legacy-constraint:3"},
    "secure_33": {
        "legacy-requirement:1",
        "legacy-requirement:4",
        "legacy-requirement:5",
        "legacy-requirement:6",
        "legacy-constraint:1",
        "legacy-constraint:2",
        "legacy-constraint:3",
    },
    "secure_34": {
        "legacy-requirement:2",
        "legacy-requirement:7",
        "legacy-constraint:4",
        "legacy-constraint:5",
    },
    "secure_35": {
        "legacy-requirement:5",
        "legacy-requirement:8",
        "legacy-constraint:2",
        "legacy-constraint:4",
    },
}


def load_guide() -> tuple[dict, GuidedWalkthrough]:
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def catalog_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'(?m)^    id:\s*"{re.escape(component_type)}"\s*,', catalog)
    assert match is not None, f"Unknown palette component type {component_type!r}"
    following = re.search(r"(?m)^  \},\s*$", catalog[match.end() :])
    assert following is not None, f"Could not delimit catalog entry {component_type!r}"
    return catalog[match.start() : match.end() + following.start()]


def expected_anchors() -> set[str]:
    return {
        *(f"legacy-requirement:{index}" for index in range(1, 9)),
        *(f"legacy-constraint:{index}" for index in range(1, 6)),
    }


def test_live_brief_and_unpublished_flag_are_preserved_verbatim():
    rows = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in rows if row["id"] == PROBLEM_ID)
    assert {field: problem[field] for field in FROZEN_BRIEF} == FROZEN_BRIEF
    assert problem["has_guided_walkthrough"] is False

    raw, guide = load_guide()
    assert raw["problem_id"] == PROBLEM_ID
    assert raw["version"] == "1.0-local-draft"
    assert guide.problem_id == PROBLEM_ID

    opening = guide.steps[0].content
    for field in ("title", "description"):
        assert FROZEN_BRIEF[field] in opening
    for field in ("requirements", "constraints", "hints"):
        assert all(item in opening for item in FROZEN_BRIEF[field])


def test_steps_phases_and_action_anchors_cover_the_frozen_brief():
    _, guide = load_guide()
    assert guide.totalSteps == len(guide.steps) == 36
    assert [step.stepNumber for step in guide.steps] == list(range(1, 37))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES for step in guide.steps)

    all_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    action_anchors = {
        anchor
        for step in guide.steps
        if step.type in {"add_component", "add_connection", "update_component"}
        for anchor in step.requirementIds
    }
    assert all_anchors == expected_anchors()
    assert action_anchors == expected_anchors()

    for step in guide.steps:
        if step.type == "add_component":
            assert step.component is not None
        elif step.type == "add_connection":
            assert step.connection is not None
        elif step.type == "update_component":
            assert step.componentUpdate is not None
        elif step.type == "decision_point":
            assert step.decision is not None
        elif step.type == "scale_trigger":
            assert step.scaleTrigger is not None

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1


def test_each_step_anchor_matches_its_specific_requirement_evidence():
    raw, _ = load_guide()
    steps = {step["id"]: step for step in raw["steps"]}
    actual_anchor_map = {
        step_id: set(step.get("requirementIds", []))
        for step_id, step in steps.items()
        if step.get("requirementIds")
    }

    assert actual_anchor_map == EXPECTED_STEP_ANCHORS


def test_web_api_data_and_identity_boundaries_are_explicit():
    raw, _ = load_guide()
    steps = {step["id"]: step for step in raw["steps"]}
    tier_boundary = " ".join(steps[step_id]["content"] for step_id in ("secure_03", "secure_09"))
    database_boundary = steps["secure_17"]["content"].casefold()
    identity_boundary = " ".join(
        steps[step_id]["content"].casefold() for step_id in ("secure_24", "secure_28")
    )

    assert "web and api runtime" in tier_boundary.casefold()
    assert "not a separately exposed api tier" in tier_boundary.casefold()
    assert "private data subnet" in tier_boundary.casefold()
    assert "network reachability" in database_boundary
    assert "database authentication" in database_boundary
    assert "end-user authorization" in database_boundary
    assert "database principal" in identity_boundary
    assert "aws actions" in identity_boundary


def test_availability_and_capacity_are_not_presented_as_verified_guarantees():
    raw, _ = load_guide()
    steps = {step["id"]: step for step in raw["steps"]}
    assumptions = steps["secure_02"]["content"].casefold()
    failover = steps["secure_10"]["content"].casefold()

    assert "99.95%" in assumptions
    assert "peak-to-average profile" in assumptions
    assert "rto" in assumptions and "rpo" in assumptions
    assert "not a failover-time or recovery-point guarantee" in failover


def test_components_use_only_catalog_types_and_supported_properties():
    raw, guide = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step.component.nodeId: step.component
        for step in guide.steps
        if step.type == "add_component" and step.component is not None
    }
    assert {node_id: component.componentType for node_id, component in additions.items()} == (
        EXPECTED_COMPONENT_TYPES
    )

    for step in raw["steps"]:
        if step.get("component"):
            component = step["component"]
            component_type = component["componentType"]
            properties = component.get("properties", {})
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            component_type = additions[update["nodeId"]].componentType
            properties = update.get("properties", {})
        else:
            continue

        block = catalog_block(catalog, component_type)
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert properties
        assert set(properties) <= supported, (
            f"{step['id']} uses unsupported {component_type} properties: "
            f"{sorted(set(properties) - supported)}"
        )

    for node_id in ("secure_kms", "secure_cloudtrail"):
        properties = additions[node_id].properties
        assert properties["componentName"]
        assert properties["technology"]
        assert properties["componentType"]


def test_ordered_replay_has_valid_connections_and_one_service_graph():
    raw, _ = load_guide()
    applied = build_architecture(raw)
    architecture = applied["architecture"]
    components = {component["id"] for component in architecture["components"]}
    connections = architecture["connections"]
    assert components == set(EXPECTED_COMPONENT_TYPES)
    assert len(connections) == 9
    assert len(applied["appliedStepIds"]) > len(applied["explanationOnlyStepIds"])

    service_components = components - {"secure_vpc"}
    neighbors = {component_id: set() for component_id in service_components}
    edge_ids = set()
    for connection in connections:
        assert connection["type"] in CONNECTION_TYPES
        assert connection["source"] in components
        assert connection["target"] in components
        if connection["source"] in service_components and connection["target"] in service_components:
            neighbors[connection["source"]].add(connection["target"])
            neighbors[connection["target"]].add(connection["source"])

    visited = set()
    pending = deque([next(iter(service_components))])
    while pending:
        component_id = pending.popleft()
        if component_id in visited:
            continue
        visited.add(component_id)
        pending.extend(neighbors[component_id] - visited)
    assert visited == service_components
    assert len({step["connection"]["edgeId"] for step in raw["steps"] if step.get("connection")}) == len(connections)


def test_security_walkthrough_does_not_add_unprovided_sizing_values():
    raw, _ = load_guide()
    narrative = " ".join(step.get("content", "") for step in raw["steps"])
    measurements = re.findall(
        r"\b\d+(?:\.\d+)?\s*(?:%|ms\b|seconds?\b|minutes?\b|hours?\b|"
        r"requests per second\b|rps\b|GB\b|TB\b|users\b|instances\b)",
        narrative,
        flags=re.IGNORECASE,
    )
    assert set(measurements) == {"99.95%"}

    serialized = json.dumps(raw, ensure_ascii=False).casefold()
    for required_phrase in ("99.95%", "sql injection", "xss", "least-privilege", "no direct internet"):
        assert required_phrase in serialized
