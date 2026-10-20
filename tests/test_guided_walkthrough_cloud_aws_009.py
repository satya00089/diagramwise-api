"""Frozen-brief, schema, catalog, and graph checks for the AWS compliance draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_aws_009"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": "cloud_aws_009",
    "title": "Design a Compliance and Audit Monitoring Solution",
    "slug": "design-a-compliance-and-audit-monitoring-solution",
    "description": "Design a compliance monitoring system that tracks configuration changes, detects security threats, ensures regulatory compliance, and provides centralized audit logging.",
    "difficulty": "Hard",
    "category": "AWS - Security & Compliance",
    "domain": "infra",
    "estimated_time": "60-90 minutes",
    "requirements": [
        "Track all resource configuration changes",
        "Audit API calls and user activity",
        "Detect security threats",
        "Ensure compliance with standards",
        "Generate compliance reports",
        "Remediate non-compliant resources",
        "Alert on security findings",
        "Maintain audit logs for 7 years",
    ],
    "constraints": [
        "Comply with PCI-DSS, HIPAA, SOC 2",
        "Detect threats in real-time",
        "Immutable audit logs",
        "Automated compliance checks",
        "Centralized logging across accounts",
    ],
    "hints": [
        "AWS Config for resource tracking",
        "CloudTrail for API logging",
        "Security Hub for security posture",
        "GuardDuty for threat detection",
        "Config Rules for compliance",
        "Systems Manager for remediation",
    ],
    "tags": ["aws", "compliance", "security", "cloudtrail", "config", "guardduty"],
    "companies": ["Amazon", "Financial Services", "Healthcare"],
    "has_guided_walkthrough": False,
}

ACTION_TYPES = {"add_component", "add_connection", "decision_point", "scale_trigger"}
STEP_TYPES = ACTION_TYPES | {"explanation"}
CONNECTION_TYPES = {
    "http",
    "tcp",
    "websocket",
    "message-queue",
    "database-connection",
    "api-call",
    "data-flow",
    "event-stream",
}
EXPECTED_COMPONENT_TYPES = {
    "aws009_accounts": "custom-component",
    "aws009_config": "configuration-management",
    "aws009_cloudtrail": "log-processing",
    "aws009_audit_archive": "object-storage",
    "aws009_guardduty": "security-scanning",
    "aws009_security_hub": "security-scanning",
    "aws009_event_router": "custom-component",
    "aws009_notifications": "notification-service",
    "aws009_ssm_automation": "configuration-management",
    "aws009_report_worker": "serverless-function",
    "aws009_review_console": "admin-console",
    "aws009_monitoring": "monitoring",
}
EXPECTED_ANCHORS = {
    *(f"legacy-requirement:{index}" for index in range(1, 9)),
    *(f"legacy-constraint:{index}" for index in range(1, 6)),
}


def _load() -> tuple[dict, GuidedWalkthrough]:
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def _catalog_component_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'(?m)^    id:\s*"{re.escape(component_type)}"\s*,', catalog)
    assert match is not None, f"Unknown palette component type {component_type!r}"
    following = re.search(r"(?m)^  \},\s*$", catalog[match.end() :])
    assert following is not None, f"Could not delimit catalog entry {component_type!r}"
    return catalog[match.start() : match.end() + following.start()]


def test_draft_preserves_the_live_frozen_brief_and_unpublished_flag():
    raw, guide = _load()
    intro = guide.steps[0].content

    assert raw["problem_id"] == guide.problem_id == FROZEN_BRIEF["id"]
    assert raw["version"] == "1.0-review-draft"
    assert FROZEN_BRIEF["has_guided_walkthrough"] is False
    assert guide.requirementRevision is None
    for field in (
        "title",
        "slug",
        "description",
        "difficulty",
        "category",
        "domain",
        "estimated_time",
    ):
        assert FROZEN_BRIEF[field] in intro
    for field in ("requirements", "constraints", "hints", "tags", "companies"):
        assert all(value in intro for value in FROZEN_BRIEF[field]), field
    assert "has_guided_walkthrough=false" in intro
    assert "local review draft" in intro.casefold()
    assert "does not change that field or publish" in intro


def test_steps_phases_and_all_frozen_anchors_are_ordered_and_actionable():
    _, guide = _load()
    assert guide.totalSteps == len(guide.steps) == 39
    assert [step.stepNumber for step in guide.steps] == list(range(1, 40))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES for step in guide.steps)

    mapped = {anchor for step in guide.steps for anchor in step.requirementIds}
    actionable = {
        anchor
        for step in guide.steps
        if step.type in ACTION_TYPES
        for anchor in step.requirementIds
    }
    assert mapped == actionable == EXPECTED_ANCHORS

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    for step in guide.steps:
        if step.type == "add_component":
            assert step.component is not None
        elif step.type == "add_connection":
            assert step.connection is not None
        elif step.type == "decision_point":
            assert step.decision is not None and step.decision.chosen
        elif step.type == "scale_trigger":
            assert step.scaleTrigger is not None
            assert all(
                getattr(step.scaleTrigger, field)
                for field in ("metric", "action", "impact")
            )


def test_actions_replay_to_one_connected_graph_with_the_intended_paths():
    raw, _ = _load()
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {component["id"] for component in architecture["components"]}
    edges = architecture["connections"]
    assert nodes == set(EXPECTED_COMPONENT_TYPES)
    assert len(edges) == 16

    neighbors = {node_id: set() for node_id in nodes}
    directed = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] in CONNECTION_TYPES
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
        directed[edge["source"]].add(edge["target"])

    reached: set[str] = set()
    pending = deque([next(iter(nodes))])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    assert reached == nodes

    def reaches(source: str, target: str) -> bool:
        visited: set[str] = set()
        pending_nodes = [source]
        while pending_nodes:
            current = pending_nodes.pop()
            if current in visited:
                continue
            visited.add(current)
            pending_nodes.extend(directed[current] - visited)
        return target in visited

    assert reaches("aws009_accounts", "aws009_config")
    assert reaches("aws009_accounts", "aws009_cloudtrail")
    assert reaches("aws009_cloudtrail", "aws009_audit_archive")
    assert reaches("aws009_accounts", "aws009_guardduty")
    assert reaches("aws009_guardduty", "aws009_security_hub")
    assert reaches("aws009_security_hub", "aws009_notifications")
    assert reaches("aws009_config", "aws009_ssm_automation")
    assert reaches("aws009_config", "aws009_review_console")
    assert reaches("aws009_security_hub", "aws009_review_console")
    assert len(replay["appliedStepIds"]) + len(replay["explanationOnlyStepIds"]) == 39


def test_components_use_existing_catalog_types_and_supported_properties():
    raw, _ = _load()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step.get("type") == "add_component"
    }
    assert {node_id: item["componentType"] for node_id, item in additions.items()} == (
        EXPECTED_COMPONENT_TYPES
    )
    assert sum(item["componentType"] == "custom-component" for item in additions.values()) == 2

    for node_id, component in additions.items():
        block = _catalog_component_block(catalog, component["componentType"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        properties = set(component.get("properties", {}))
        assert {"componentName", "purpose"} <= properties, node_id
        assert properties <= supported, (
            f"{node_id} has unsupported properties: {sorted(properties - supported)}"
        )


def test_walkthrough_keeps_unknown_targets_open_and_avoids_invented_sizing():
    raw, _ = _load()
    text = json.dumps(raw, ensure_ascii=False).casefold()

    for phrase in (
        "pci-dss, hipaa, soc 2",
        "real-time",
        "immutable audit logs",
        "centralized logging across accounts",
        "7 years",
        "no account or resource counts",
        "numeric response target",
        "control mapping",
        "approval policy",
        "object lock",
        "aws config",
        "cloudtrail",
        "guardduty",
        "security hub",
        "systems manager automation",
    ):
        assert phrase in text, f"Missing supplied need or explicit design caveat: {phrase}"

    for invented_target in ("requests per second", "99.9%", "p99", "milliseconds"):
        assert invented_target not in text
