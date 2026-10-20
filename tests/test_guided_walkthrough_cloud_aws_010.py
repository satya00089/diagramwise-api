"""Structural, catalog, and frozen-brief checks for the AWS data-lake draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_aws_010"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": "cloud_aws_010",
    "title": "Build a Scalable Data Lake Architecture",
    "slug": "build-a-scalable-data-lake-architecture",
    "description": (
        "Design a data lake architecture that ingests data from multiple sources, "
        "catalogs and organizes data, enables SQL queries, and provides data visualization capabilities."
    ),
    "difficulty": "Hard",
    "category": "AWS - Data Lake",
    "domain": "infra",
    "estimated_time": "60-90 minutes",
    "has_guided_walkthrough": False,
    "requirements": [
        "Store structured and unstructured data",
        "Catalog and discover datasets",
        "Query data without moving it",
        "Transform and prepare data",
        "Implement data governance",
        "Control access to sensitive data",
        "Visualize data insights",
        "Support petabyte-scale data",
    ],
    "constraints": [
        "Query latency under 10 seconds",
        "Support concurrent queries (100+)",
        "Enforce fine-grained access control",
        "Minimize data movement costs",
        "Automate data cataloging",
    ],
    "hints": [
        "S3 for data lake storage",
        "AWS Glue for ETL and catalog",
        "Athena for SQL queries",
        "Lake Formation for governance",
        "QuickSight for visualization",
        "Partition data for performance",
    ],
    "tags": ["aws", "data-lake", "s3", "glue", "athena", "analytics"],
    "companies": ["Amazon", "Netflix", "Airbnb"],
}

STEP_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "decision_point",
    "scale_trigger",
}
ACTION_TYPES = {"add_component", "add_connection"}
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
    "lake_sources": "backend-server",
    "lake_stream": "message-broker",
    "lake_delivery": "stream-processor",
    "lake_raw": "object-storage",
    "lake_etl": "processing-worker",
    "lake_curated": "object-storage",
    "lake_catalog": "database",
    "lake_crawler": "processing-worker",
    "lake_governance": "auth-service",
    "lake_athena": "analytics",
    "lake_results": "object-storage",
    "lake_quicksight": "web-app",
    "lake_monitoring": "monitoring",
}
EXPECTED_ANCHORS = {
    *(f"legacy-requirement:{index}" for index in range(1, 9)),
    *(f"legacy-constraint:{index}" for index in range(1, 6)),
}
EXPECTED_ACTION_ANCHORS = {
    "lake_07": {"legacy-requirement:1"},
    "lake_08": {"legacy-requirement:1"},
    "lake_09": {"legacy-requirement:1"},
    "lake_10": {"legacy-requirement:1", "legacy-requirement:5", "legacy-requirement:6", "legacy-requirement:8"},
    "lake_11": {"legacy-requirement:1"},
    "lake_12": {"legacy-requirement:1"},
    "lake_13": {"legacy-requirement:1", "legacy-requirement:5", "legacy-requirement:6"},
    "lake_14": {"legacy-requirement:1", "legacy-requirement:5", "legacy-requirement:6"},
    "lake_15": {"legacy-requirement:4", "legacy-requirement:5", "legacy-requirement:6"},
    "lake_16": {"legacy-requirement:1", "legacy-requirement:4", "legacy-requirement:8"},
    "lake_17": {"legacy-requirement:1", "legacy-requirement:3", "legacy-requirement:4", "legacy-requirement:8", "legacy-constraint:1"},
    "lake_18": {"legacy-requirement:4", "legacy-requirement:8"},
    "lake_23": {"legacy-requirement:2"},
    "lake_24": {"legacy-requirement:2", "legacy-requirement:5", "legacy-constraint:5"},
    "lake_25": {"legacy-requirement:2", "legacy-requirement:5", "legacy-requirement:6", "legacy-constraint:3", "legacy-constraint:5"},
    "lake_26": {"legacy-requirement:2", "legacy-requirement:3", "legacy-constraint:5"},
    "lake_27": {"legacy-requirement:2", "legacy-requirement:3", "legacy-constraint:5"},
    "lake_28": {"legacy-requirement:2", "legacy-requirement:4", "legacy-constraint:5"},
    "lake_29": {"legacy-requirement:5", "legacy-requirement:6", "legacy-constraint:3"},
    "lake_30": {"legacy-requirement:2", "legacy-requirement:5", "legacy-requirement:6", "legacy-constraint:3"},
    "lake_31": {"legacy-requirement:4", "legacy-requirement:5", "legacy-requirement:6", "legacy-constraint:3"},
    "lake_33": {"legacy-requirement:2", "legacy-requirement:3"},
    "lake_34": {"legacy-requirement:3", "legacy-requirement:8", "legacy-constraint:1", "legacy-constraint:4"},
    "lake_35": {"legacy-requirement:2", "legacy-requirement:3"},
    "lake_36": {"legacy-requirement:5", "legacy-requirement:6", "legacy-constraint:3"},
    "lake_37": {"legacy-requirement:5", "legacy-requirement:6", "legacy-constraint:3"},
    "lake_38": {"legacy-requirement:6", "legacy-constraint:3"},
    "lake_39": {"legacy-requirement:7"},
    "lake_40": {"legacy-requirement:3", "legacy-requirement:5", "legacy-requirement:6", "legacy-requirement:7", "legacy-constraint:3", "legacy-constraint:4"},
    "lake_41": {"legacy-requirement:3", "legacy-requirement:7", "legacy-constraint:4"},
    "lake_45": {"legacy-requirement:2", "legacy-requirement:4", "legacy-requirement:5", "legacy-requirement:6", "legacy-requirement:7", "legacy-constraint:1", "legacy-constraint:2", "legacy-constraint:5"},
    "lake_46": {"legacy-requirement:3", "legacy-requirement:5", "legacy-requirement:6", "legacy-constraint:1", "legacy-constraint:2", "legacy-constraint:3"},
    "lake_47": {"legacy-requirement:2", "legacy-requirement:4", "legacy-requirement:7", "legacy-constraint:5"},
}
EXPECTED_DATA_MOVEMENT_COST_STEPS = {
    "lake_06",
    "lake_34",
    "lake_40",
    "lake_41",
    "lake_44",
    "lake_48",
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


def test_walkthrough_covers_the_exact_frozen_brief_as_a_local_review_draft():
    raw, guide = _load()
    intro = guide.steps[0].content

    assert raw["problem_id"] == FROZEN_BRIEF["id"]
    assert guide.problem_id == FROZEN_BRIEF["id"]
    assert guide.version == "1.0-review"
    assert guide.requirementRevision is None
    assert FROZEN_BRIEF["has_guided_walkthrough"] is False
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
    assert "has_guided_walkthrough is false" in intro
    assert "local review draft" in intro
    assert "does not change the frozen availability field" in intro
    mapped = {anchor for step in guide.steps for anchor in step.requirementIds}
    actionable = {
        anchor
        for step in guide.steps
        if step.type in ACTION_TYPES
        for anchor in step.requirementIds
    }
    assert mapped == actionable == EXPECTED_ANCHORS


def test_test_snapshot_matches_the_authoritative_frozen_problem_fixture():
    problems = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    matches = [problem for problem in problems if problem.get("id") == PROBLEM_ID]
    assert matches == [FROZEN_BRIEF]


def test_action_anchors_are_direct_and_data_movement_cost_is_not_scan_cost():
    _, guide = _load()
    assert guide.steps[0].requirementIds == []
    action_anchors = {
        step.id: set(step.requirementIds)
        for step in guide.steps
        if step.type in ACTION_TYPES
    }
    assert action_anchors == EXPECTED_ACTION_ANCHORS

    movement_cost_steps = {
        step.id
        for step in guide.steps
        if "legacy-constraint:4" in step.requirementIds
    }
    assert movement_cost_steps == EXPECTED_DATA_MOVEMENT_COST_STEPS


def test_lifecycle_tiering_and_performance_are_policy_choices_not_guarantees():
    _, guide = _load()
    steps = {step.id: step for step in guide.steps}
    tiering_text = " ".join(
        [
            steps["lake_22"].content,
            steps["lake_22"].scaleTrigger.metric,
            steps["lake_22"].scaleTrigger.action,
            steps["lake_22"].scaleTrigger.impact,
        ]
    ).casefold()
    assert "storage class" in tiering_text
    assert "access frequency" in tiering_text
    assert "retention" in tiering_text
    assert "supplies no storage-class choice" in tiering_text

    query_text = " ".join(
        steps[step_id].content
        for step_id in ("lake_20", "lake_34", "lake_42", "lake_43", "lake_44")
    ).casefold()
    assert "not latency or throughput guarantees" in query_text
    assert "bytes scanned" in query_text
    assert "data transferred or copied" in query_text


def test_no_numeric_cost_retention_availability_or_throughput_values_are_invented():
    raw, _ = _load()
    strings = []

    def collect_strings(value):
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, dict):
            for nested in value.values():
                collect_strings(nested)
        elif isinstance(value, list):
            for nested in value:
                collect_strings(nested)

    collect_strings(raw)
    forbidden_claims = {
        "numeric cost": re.compile(
            r"(?:\$\s*\d|\b\d[\d,.]*\s*(?:USD|dollars?)\b|\b\d[\d,.]*\s*(?:/|per\s+)\s*(?:KB|MB|GB|TB|PB)(?:[- ](?:hour|day|month|year))?\b)",
            re.IGNORECASE,
        ),
        "numeric retention": re.compile(
            r"(?:\b(?:retention|retain(?:ed)?|expire|expiry|lifecycle|transition|ttl)\b[^.;\n]{0,80}\b\d+\s*(?:days?|weeks?|months?|years?)|\b\d+\s*(?:days?|weeks?|months?|years?)\b[^.;\n]{0,40}\b(?:retention|lifecycle|policy|ttl)\b)",
            re.IGNORECASE,
        ),
        "numeric availability": re.compile(r"\b\d+(?:\.\d+)?\s*(?:%|percent)\b", re.IGNORECASE),
        "numeric throughput": re.compile(
            r"\b\d[\d,.]*\s*(?:k|m|b|thousand|million|billion)?\s*(?:requests?|queries?|records?|events?|objects?|bytes?)\s*(?:/\s*(?:s|sec|second|min|minute|h|hour|d|day)|per\s+(?:s|sec|second|min|minute|h|hour|d|day))\b|\b\d[\d,.]*\s*(?:KB|MB|GB|TB|PB)\s*/\s*(?:s|sec|second|min|minute|h|hour|d|day)\b",
            re.IGNORECASE,
        ),
    }
    for claim, pattern in forbidden_claims.items():
        assert not any(pattern.search(value) for value in strings), claim


def test_steps_phases_and_action_payloads_follow_the_walkthrough_schema():
    _, guide = _load()
    assert 35 <= guide.totalSteps <= 60
    assert guide.totalSteps == len(guide.steps) == 48
    assert [step.stepNumber for step in guide.steps] == list(range(1, 49))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES for step in guide.steps)

    for step in guide.steps:
        if step.type == "add_component":
            assert step.component is not None
        elif step.type == "add_connection":
            assert step.connection is not None
        elif step.type == "decision_point":
            assert step.decision is not None
            assert step.decision.chosen
        elif step.type == "scale_trigger":
            assert step.scaleTrigger is not None
            assert step.scaleTrigger.metric
            assert step.scaleTrigger.action
            assert step.scaleTrigger.impact

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step
        assert start <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1


def test_components_use_catalog_ids_and_only_supported_editable_properties():
    raw, guide = _load()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step.component.nodeId: step.component
        for step in guide.steps
        if step.type == "add_component" and step.component is not None
    }
    assert {node_id: item.componentType for node_id, item in additions.items()} == (
        EXPECTED_COMPONENT_TYPES
    )

    for step in raw["steps"]:
        component = step.get("component")
        if component is None:
            continue
        block = _catalog_component_block(catalog, component["componentType"])
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        properties = set(component.get("properties", {}))
        assert {"componentName", "purpose"} <= properties, step["id"]
        assert properties <= supported, (
            f"{step['id']} has unsupported {component['componentType']} properties: "
            f"{sorted(properties - supported)}"
        )


def test_ordered_actions_replay_to_a_connected_lake_architecture():
    raw, guide = _load()
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {component["id"] for component in architecture["components"]}
    edges = architecture["connections"]
    assert nodes == set(EXPECTED_COMPONENT_TYPES)
    assert len(edges) >= 18
    assert len(replay["appliedStepIds"]) > len(replay["explanationOnlyStepIds"])

    known_nodes = set()
    known_edges = set()
    directed = {node_id: set() for node_id in nodes}
    neighbors = {node_id: set() for node_id in nodes}
    for step in guide.steps:
        if step.type == "add_component":
            assert step.component.nodeId not in known_nodes
            known_nodes.add(step.component.nodeId)
        elif step.type == "add_connection":
            edge = step.connection
            assert edge.edgeId not in known_edges
            assert edge.sourceNodeId in known_nodes
            assert edge.targetNodeId in known_nodes
            assert edge.connectionType in CONNECTION_TYPES
            known_edges.add(edge.edgeId)

    for edge in edges:
        assert edge["type"] in CONNECTION_TYPES
        directed[edge["source"]].add(edge["target"])
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])

    visited = set()
    pending = deque([next(iter(nodes))])
    while pending:
        current = pending.popleft()
        if current in visited:
            continue
        visited.add(current)
        pending.extend(neighbors[current] - visited)
    assert visited == nodes

    def reaches(source, target):
        reachable = set()
        pending = [source]
        while pending:
            current = pending.pop()
            if current in reachable:
                continue
            reachable.add(current)
            pending.extend(directed[current] - reachable)
        return target in reachable

    assert reaches("lake_sources", "lake_raw")
    assert reaches("lake_sources", "lake_curated")
    assert reaches("lake_sources", "lake_athena")
    assert reaches("lake_sources", "lake_quicksight")
    assert len(replay["appliedStepIds"]) + len(replay["explanationOnlyStepIds"]) == guide.totalSteps


def test_lake_tradeoffs_cover_partitioning_governance_scale_and_data_movement():
    _, guide = _load()
    text = "\n".join(
        [step.title + " " + step.content for step in guide.steps]
        + [
            alternative.option + " " + alternative.tradeoff
            for step in guide.steps
            if step.decision
            for alternative in step.decision.alternatives
        ]
    ).casefold()

    for term in (
        "partition projection",
        "small files",
        "parquet",
        "orc",
        "bytes scanned",
        "glue data catalog",
        "glue crawlers",
        "lake formation",
        "lf-tags",
        "direct s3",
        "amazon athena",
        "100+ concurrent-query goal",
        "under 10 seconds",
        "petabyte-scale",
        "amazon quicksight",
        "spice",
        "cross-region",
        "data-movement costs",
    ):
        assert term in text, f"Missing lake design topic: {term}"

    decisions = {step.id: step.decision for step in guide.steps if step.decision}
    assert "partition projection" in decisions["lake_20"].chosen.casefold()
    assert "direct query" in decisions["lake_44"].chosen.casefold()
    assert "spice" in " ".join(
        alternative.option + alternative.tradeoff
        for alternative in decisions["lake_44"].alternatives
    ).casefold()
    assert "do not guarantee concurrency capacity" in guide.steps[42].content.casefold()

