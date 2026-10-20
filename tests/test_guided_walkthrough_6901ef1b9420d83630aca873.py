"""Focused structural and frozen-brief checks for cluster-health walkthrough draft."""

import json
import re
from pathlib import Path

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca873"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
COMPONENT_CATALOG = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"


def load_fixture() -> dict:
    rows = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return next(row for row in rows if row["id"] == PROBLEM_ID)


def load_guide() -> dict:
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def test_guide_matches_exact_frozen_brief_fields():
    brief = load_fixture()
    assert brief["has_guided_walkthrough"] is False  # frozen snapshot only, not a fresh AWS check
    assert {
        key: brief[key]
        for key in (
            "id",
            "title",
            "description",
            "requirements",
            "constraints",
            "slug",
            "category",
            "domain",
            "difficulty",
            "estimatedTime",
            "hints",
            "tags",
            "createdAt",
            "updatedAt",
            "has_guided_walkthrough",
        )
    } == {
        "id": PROBLEM_ID,
        "title": "Design a System to Monitor the Health of a Cluster",
        "description": "Design a monitoring system to track health, performance, and availability of distributed clusters.",
        "requirements": [
            "Monitor node health and availability",
            "Collect performance metrics (CPU, memory, disk)",
            "Detect node failures and network partitions",
            "Alert on threshold violations",
            "Visualize cluster topology",
            "Historical metrics and trends",
            "Support thousands of nodes",
            "Auto-discovery of new nodes",
        ],
        "constraints": [
            "Real-time health status",
            "Low overhead on monitored systems",
            "Handle monitoring system failures",
            "Accurate failure detection",
            "Minimize false positives",
        ],
        "slug": "design-a-system-to-monitor-the-health-of-a-cluster",
        "category": "Monitoring",
        "domain": "application",
        "difficulty": "Medium",
        "estimatedTime": "45-60 minutes",
        "hints": [
            "Heartbeat mechanism for liveness",
            "Time-series database for metrics",
            "Gossip protocol for distributed health",
            "Alerting rules and thresholds",
            "Dashboard for visualization",
        ],
        "tags": ["monitoring", "health-check", "distributed-systems", "alerting", "metrics"],
        "createdAt": "2025-10-29T10:40:27.393000",
        "updatedAt": "2025-10-29T10:40:27.393000",
        "has_guided_walkthrough": False,
    }
    guide = load_guide()
    assert guide["problem_id"] == brief["id"]
    assert guide["requirementRevision"] is None


def test_guide_validates_against_public_walkthrough_schema():
    guide = load_guide()
    parsed = GuidedWalkthrough(**guide)
    assert parsed.problem_id == PROBLEM_ID
    assert parsed.totalSteps == len(parsed.steps) == 32


def test_all_frozen_requirements_and_constraints_are_anchored():
    brief = load_fixture()
    guide = load_guide()
    actual = {anchor for step in guide["steps"] for anchor in step.get("requirementIds", [])}
    expected = {
        *(f"legacy-requirement:{i}" for i in range(1, len(brief["requirements"]) + 1)),
        *(f"legacy-constraint:{i}" for i in range(1, len(brief["constraints"]) + 1)),
    }
    assert actual == expected


def test_brief_anchors_preserve_failure_uncertainty_and_separate_assumptions():
    brief = load_fixture()
    guide = load_guide()

    def anchored_text(section: str, item: str) -> str:
        index = brief[section].index(item) + 1
        anchor_type = "requirement" if section == "requirements" else "constraint"
        anchor = f"legacy-{anchor_type}:{index}"
        matching_steps = [
            step for step in guide["steps"] if anchor in step.get("requirementIds", [])
        ]
        assert matching_steps, f"Frozen brief item is not anchored: {item}"
        return json.dumps(matching_steps, ensure_ascii=False).casefold()

    failure_design = anchored_text(
        "requirements", "Detect node failures and network partitions"
    )
    assert "partition" in failure_design
    assert "suspect" in failure_design
    assert "corroborat" in failure_design
    assert "unknown" in failure_design

    alert_design = anchored_text("requirements", "Alert on threshold violations")
    assert "threshold" in alert_design
    assert "sustained" in alert_design
    assert "deduplicat" in alert_design

    historical_design = anchored_text("requirements", "Historical metrics and trends")
    assert "time-series" in historical_design
    assert "trend" in historical_design

    discovery_design = anchored_text("requirements", "Auto-discovery of new nodes")
    assert "discovery" in discovery_design
    assert "membership" in discovery_design

    overhead_design = anchored_text("constraints", "Low overhead on monitored systems")
    assert "overhead" in overhead_design
    assert "measure" in overhead_design
    assert "backpressure" in overhead_design or "resource-bounded" in overhead_design

    failure_tolerance_design = anchored_text(
        "constraints", "Handle monitoring system failures"
    )
    assert "monitoring-system failures" in failure_tolerance_design
    assert "outage" in failure_tolerance_design
    assert "recover" in failure_tolerance_design

    accuracy_design = anchored_text("constraints", "Accurate failure detection")
    assert "suspect" in accuracy_design
    assert "corroborat" in accuracy_design
    assert "detection delay" in accuracy_design

    false_positive_design = anchored_text("constraints", "Minimize false positives")
    assert "false-positive" in false_positive_design
    assert "anti-flap" in false_positive_design

    brief_step = guide["steps"][0]["content"].casefold()
    assert "draft assumptions, not prompt facts" in brief_step
    assert "3,000" in brief_step and "5-second" in brief_step and "30 days" in brief_step
    assert "none of these choices is a measured slo" in brief_step


def test_step_order_phase_ranges_and_replayed_architecture_are_connected():
    guide = load_guide()
    steps = guide["steps"]
    assert [step["stepNumber"] for step in steps] == list(range(1, len(steps) + 1))
    assert [phase["stepRange"] for phase in guide["phases"]] == [[1, 5], [6, 13], [14, 27], [28, 32]]
    for phase in guide["phases"]:
        start, end = phase["stepRange"]
        assert all(step["phase"] == phase["name"] for step in steps[start - 1 : end])

    replay = build_architecture(guide)
    architecture = replay["architecture"]
    nodes = {component["id"] for component in architecture["components"]}
    assert len(nodes) == 13
    assert len(architecture["connections"]) == 14
    adjacency = {node_id: set() for node_id in nodes}
    for edge in architecture["connections"]:
        adjacency[edge["source"]].add(edge["target"])
        adjacency[edge["target"]].add(edge["source"])
    reached = set()
    pending = [next(iter(nodes))]
    while pending:
        node_id = pending.pop()
        if node_id in reached:
            continue
        reached.add(node_id)
        pending.extend(adjacency[node_id] - reached)
    assert reached == nodes


def test_components_and_properties_exist_in_the_editable_frontend_catalog():
    catalog = COMPONENT_CATALOG.read_text(encoding="utf-8")
    guide = load_guide()
    components = {
        step["component"]["nodeId"]: step["component"]
        for step in guide["steps"]
        if step.get("type") == "add_component"
    }
    assert len(components) == 13
    assert all(component["componentType"] != "custom" for component in components.values())

    for step in guide["steps"]:
        component = step.get("component")
        if step.get("componentUpdate"):
            update = step["componentUpdate"]
            component = components[update["nodeId"]]
            properties = update.get("properties", {})
        elif component:
            properties = component.get("properties", {})
        else:
            continue
        component_type = component["componentType"]
        match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
        assert match, f"{step['id']} uses non-catalog component {component_type}"
        block_end = catalog.find("\n  },", match.start())
        component_block = catalog[match.start() : block_end]
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', component_block))
        assert set(properties) <= supported, f"{step['id']} has unsupported properties: {set(properties) - supported}"
        assert {"componentName", "purpose"} <= set(properties)

