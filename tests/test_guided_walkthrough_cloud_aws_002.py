"""Structural, frozen-brief, and component-catalog checks for the DR draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_aws_002"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": "cloud_aws_002",
    "title": "Design a Multi-Region Disaster Recovery Solution",
    "slug": "design-a-multi-region-disaster-recovery-solution",
    "description": (
        "Design a disaster recovery architecture that ensures business continuity "
        "across multiple geographic regions with automatic failover."
    ),
    "difficulty": "Hard",
    "category": "AWS - High Availability",
    "domain": "infra",
    "estimated_time": "60-90 minutes",
    "has_guided_walkthrough": False,
    "requirements": [
        "Ensure business continuity during outages",
        "Replicate data across multiple regions",
        "Automatic failover within minutes",
        "Maintain data consistency",
        "Regular backup and restore testing",
        "Monitor system health across regions",
        "Define RPO and RTO targets",
        "Automate infrastructure provisioning",
    ],
    "constraints": [
        "RPO (Recovery Point Objective) < 5 minutes",
        "RTO (Recovery Time Objective) < 15 minutes",
        "Handle regional failures gracefully",
        "Minimize data loss during failover",
        "Cost-effective replication strategy",
    ],
    "hints": [
        "Use Route 53 health checks for failover",
        "RDS Multi-AZ for database HA",
        "S3 Cross-Region Replication for objects",
        "CloudFormation for infrastructure as code",
        "Aurora Global Database for low-latency reads",
        "DynamoDB Global Tables for multi-region",
    ],
    "tags": [
        "aws",
        "disaster-recovery",
        "route53",
        "rds",
        "s3",
        "cloudformation",
        "multi-region",
    ],
    "companies": ["Amazon", "Capital One", "Netflix"],
}

STEP_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "decision_point",
    "update_component",
}
ACTION_TYPES = {"add_component", "add_connection", "update_component"}
CONNECTION_TYPES = {
    "http",
    "database-connection",
    "data-flow",
    "api-call",
}
EXPECTED_COMPONENT_TYPES = {
    "dr_route53": "authoritative-nameserver",
    "dr_primary_alb": "loadbalancer",
    "dr_primary_app": "backend-server",
    "dr_primary_db": "database",
    "dr_primary_s3": "object-storage",
    "dr_standby_alb": "loadbalancer",
    "dr_standby_app": "backend-server",
    "dr_standby_db": "database",
    "dr_standby_s3": "object-storage",
    "dr_monitoring": "monitoring",
    "dr_failover_runner": "serverless-function",
    "dr_cloudformation": "infrastructure-as-code",
    "dr_backup_vault": "cold-storage",
    "dr_restore_tests": "automated-testing",
}
EXPECTED_ANCHORS = {
    *(f"legacy-requirement:{index}" for index in range(1, 9)),
    *(f"legacy-constraint:{index}" for index in range(1, 6)),
}


def _load():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def _catalog_component_block(catalog: str, component_type: str) -> str:
    match = re.search(
        rf'(?m)^    id:\s*"{re.escape(component_type)}"\s*,', catalog
    )
    assert match is not None, f"Unknown palette component type {component_type!r}"
    following = re.search(r"(?m)^  \},\s*$", catalog[match.end() :])
    assert following is not None, f"Could not delimit catalog entry {component_type!r}"
    return catalog[match.start() : match.end() + following.start()]


def test_guide_matches_the_exact_frozen_problem_row_and_covers_its_brief():
    raw, guide = _load()
    rows = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in rows if row["id"] == PROBLEM_ID)
    actual_brief = {key: problem[key] for key in FROZEN_BRIEF}
    opening = guide.steps[0].content

    assert actual_brief == FROZEN_BRIEF
    assert raw["problem_id"] == guide.problem_id == PROBLEM_ID
    assert raw["version"] == "1.0-review"
    assert guide.requirementRevision is None
    assert "has_guided_walkthrough=false" in opening
    assert "local review draft" in opening
    assert "does not change that availability flag" in opening
    for field in (
        "title",
        "slug",
        "description",
        "difficulty",
        "category",
        "domain",
        "estimated_time",
    ):
        assert FROZEN_BRIEF[field] in opening
    for field in ("requirements", "constraints", "hints", "tags", "companies"):
        assert all(value in opening for value in FROZEN_BRIEF[field]), field

    mapped = {anchor for step in guide.steps for anchor in step.requirementIds}
    actionable = {
        anchor
        for step in guide.steps
        if step.type in ACTION_TYPES
        for anchor in step.requirementIds
    }
    assert mapped == actionable == EXPECTED_ANCHORS


def test_steps_follow_the_walkthrough_schema_and_cover_all_phase_ranges():
    raw, guide = _load()

    assert 35 <= guide.totalSteps <= 60
    assert guide.totalSteps == len(guide.steps) == 54
    assert [step.stepNumber for step in guide.steps] == list(range(1, 55))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES for step in guide.steps)

    for step in guide.steps:
        if step.type == "add_component":
            assert step.component is not None
        elif step.type == "add_connection":
            assert step.connection is not None
        elif step.type == "update_component":
            assert step.componentUpdate is not None
        elif step.type == "decision_point":
            assert step.decision is not None and step.decision.chosen
            assert step.decision.chosenReason

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step
        assert start <= end
        assert all(
            guide.steps[index - 1].phase == phase.name
            for index in range(start, end + 1)
        )
        next_step = end + 1
    assert next_step == guide.totalSteps + 1
    assert raw.get("has_guided_walkthrough") is None


def test_every_component_and_update_uses_existing_catalog_ids_and_properties():
    raw, guide = _load()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step.component.nodeId: step.component
        for step in guide.steps
        if step.type == "add_component" and step.component is not None
    }
    actual_component_types = {
        node_id: component.componentType for node_id, component in additions.items()
    }
    assert actual_component_types == EXPECTED_COMPONENT_TYPES
    assert "custom-component" not in actual_component_types.values()

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

        block = _catalog_component_block(catalog, component_type)
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert properties
        assert set(properties) <= supported, (
            f"{step['id']} uses unsupported {component_type} properties: "
            f"{sorted(set(properties) - supported)}"
        )


def test_replay_builds_one_connected_multi_region_replication_and_recovery_graph():
    raw, _ = _load()
    built = build_architecture(raw)
    architecture = built["architecture"]
    components = {component["id"] for component in architecture["components"]}
    connections = architecture["connections"]
    edge_ids = {edge["id"] for edge in connections}

    assert components == set(EXPECTED_COMPONENT_TYPES)
    assert len(connections) == 25
    assert len(built["appliedStepIds"]) == 40
    assert len(built["appliedStepIds"]) > len(built["explanationOnlyStepIds"])
    assert all(edge["type"] in CONNECTION_TYPES for edge in connections)
    assert {
        "primary_db_to_standby_db",
        "primary_s3_to_standby_s3",
        "monitoring_to_failover_runner",
        "failover_runner_promotes_standby_db",
        "failover_runner_readies_standby_app",
        "failover_runner_updates_route53",
        "primary_db_to_backup_vault",
        "primary_s3_to_backup_vault",
        "backup_vault_to_restore_tests",
        "restore_tests_to_monitoring",
        "cloudformation_to_primary_app",
        "cloudformation_to_standby_app",
    } <= edge_ids

    neighbors = {component_id: set() for component_id in components}
    for edge in connections:
        assert edge["source"] in components
        assert edge["target"] in components
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])

    visited = set()
    pending = deque(["dr_route53"])
    while pending:
        component_id = pending.popleft()
        if component_id in visited:
            continue
        visited.add(component_id)
        pending.extend(neighbors[component_id] - visited)
    assert visited == components


def test_design_explains_recovery_targets_consistency_and_unstated_assumptions():
    raw, _ = _load()
    text = json.dumps(raw, ensure_ascii=False).casefold()

    for signal in (
        "rpo (recovery point objective) < 5 minutes",
        "rto (recovery time objective) < 15 minutes",
        "warm standby",
        "asynchronous cross-region replication",
        "single-writer",
        "fence the old writer",
        "s3 cross-region replication",
        "replica lag",
        "resolver and client caching",
        "restore and failover",
        "cloudformation",
        "controlled failback",
        "problem supplies no numeric detector interval",
        "no named aws regions",
    ):
        assert signal in text, f"Walkthrough does not explain {signal!r}"

