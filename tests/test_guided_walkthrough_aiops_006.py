"""Local structural review gates for the self-healing infrastructure draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / "aiops_006.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

REQUIREMENTS = [
    "Detect infrastructure anomalies automatically",
    "Match detected issues to known remediation playbooks",
    "Execute automated remediation actions safely",
    "Implement safety gates before destructive actions",
    "Learn new remediation patterns from operator actions",
    "Handle cascading failures with coordinated responses",
    "Track remediation success rates and outcomes",
    "Support rollback of failed remediations",
]
CONSTRAINTS = [
    "Auto-remediation within 5 minutes of detection",
    "Remediation success rate above 90%",
    "Zero unintended side effects from automation",
    "Handle 100+ different failure scenarios",
    "Audit trail for all automated actions",
]
STEP_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "decision_point",
    "scale_trigger",
}
CONNECTION_TYPES = {
    "api-call",
    "data-flow",
    "database-connection",
    "event-stream",
    "message-queue",
}


def load_problem():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == "aiops_006")


def load_guide():
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def test_frozen_brief_and_schema_are_preserved():
    problem = load_problem()
    guide = GuidedWalkthrough.model_validate(load_guide())

    assert problem["title"] == "Design a Self-Healing Infrastructure Platform"
    assert problem["description"] == (
        "Design a platform that automatically detects, diagnoses, and remediates "
        "infrastructure issues without human intervention, using playbook automation "
        "and ML-driven decision making."
    )
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert guide.problem_id == problem["id"]
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None  # The frozen brief has no versioned spec.
    assert guide.totalSteps == len(guide.steps) == 60


def test_steps_phases_actions_and_exact_brief_anchors():
    guide = load_guide()
    steps = guide["steps"]
    assert [step["stepNumber"] for step in steps] == list(range(1, 61))
    assert len({step["id"] for step in steps}) == len(steps)
    assert all(step["type"] in STEP_TYPES for step in steps)

    next_step = 1
    for phase in guide["phases"]:
        start, end = phase["stepRange"]
        assert start == next_step
        assert start <= end
        assert phase["description"]
        assert all(
            steps[number - 1]["phase"] == phase["name"]
            for number in range(start, end + 1)
        )
        next_step = end + 1
    assert next_step == 61
    assert len({phase["name"] for phase in guide["phases"]}) == 5

    counts = {kind: sum(step["type"] == kind for step in steps) for kind in STEP_TYPES}
    assert counts == {
        "explanation": 2,
        "add_component": 19,
        "add_connection": 31,
        "decision_point": 6,
        "scale_trigger": 2,
    }
    for step in steps:
        if step["type"] == "add_component":
            assert "component" in step
        elif step["type"] == "add_connection":
            assert "connection" in step
        elif step["type"] == "decision_point":
            assert "decision" in step and "componentUpdate" in step
            assert step["decision"]["alternatives"]
        elif step["type"] == "scale_trigger":
            assert "scaleTrigger" in step

    expected_anchors = {
        *(f"legacy-requirement:{number}" for number in range(1, len(REQUIREMENTS) + 1)),
        *(f"legacy-constraint:{number}" for number in range(1, len(CONSTRAINTS) + 1)),
    }
    anchors = {anchor for step in steps for anchor in step["requirementIds"]}
    assert anchors == expected_anchors
    # Each brief item is traced to a concrete design action, not just the introduction.
    action_steps = [
        step for step in steps
        if step["type"] in {"add_component", "add_connection", "decision_point"}
    ]
    assert {anchor for step in action_steps for anchor in step["requirementIds"]} == expected_anchors
    for anchor, number, kind in (
        ("legacy-requirement:1", 3, "add_component"),
        ("legacy-requirement:2", 18, "add_component"),
        ("legacy-requirement:3", 31, "add_component"),
        ("legacy-requirement:4", 20, "add_component"),
        ("legacy-requirement:5", 49, "add_component"),
        ("legacy-requirement:6", 13, "add_component"),
        ("legacy-requirement:7", 47, "add_component"),
        ("legacy-requirement:8", 40, "decision_point"),
        ("legacy-constraint:1", 31, "add_component"),
        ("legacy-constraint:2", 47, "add_component"),
        ("legacy-constraint:3", 20, "add_component"),
        ("legacy-constraint:4", 18, "add_component"),
        ("legacy-constraint:5", 43, "add_component"),
    ):
        step = steps[number - 1]
        assert step["type"] == kind
        assert anchor in step["requirementIds"]


def test_every_component_and_update_uses_supported_catalog_properties():
    guide = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}

    for step in guide["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            assert component["nodeId"] not in components
            assert component["componentType"] != "custom-component"
            assert component["properties"]["componentName"] == component["label"]
            assert component["properties"]["purpose"] == component["description"]
            components[component["nodeId"]] = component
            properties = component["properties"]
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            assert update["nodeId"] in components
            component = components[update["nodeId"]]
            properties = update["properties"]
            assert properties
        else:
            continue

        component_type = component["componentType"]
        match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
        assert match, f"{step['id']} uses unknown catalog ID {component_type}"
        block_end = catalog.find("\n  },", match.start())
        assert block_end > match.start()
        component_block = catalog[match.start():block_end]
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', component_block))
        assert set(properties) <= supported, (
            f"{step['id']} has unsupported {component_type} properties "
            f"{sorted(set(properties) - supported)}"
        )
        for key, value in properties.items():
            property_start = re.search(
                rf'\{{\s*key:\s*"{re.escape(key)}"', component_block
            )
            assert property_start is not None
            remainder = component_block[property_start.start():]
            next_property = re.search(r'\n\s*\{\s*key:', remainder[1:])
            property_block = (
                remainder[:next_property.start() + 1]
                if next_property else remainder
            )
            field_type = re.search(r'\btype:\s*"([^"]+)"', property_block)
            assert field_type is not None
            if field_type[1] == "boolean":
                assert type(value) is bool
            elif field_type[1] == "number":
                assert type(value) in (int, float)
            elif field_type[1] == "select":
                options = re.search(
                    r'\boptions:\s*\[([^\]]*)\]', property_block, re.DOTALL
                )
                assert options is not None
                allowed = set(re.findall(r'"([^"]+)"', options[1]))
                assert value in allowed, (
                    f"{step['id']} has invalid {component_type}.{key}={value!r}"
                )

    assert len(components) == 19
    assert components["heal_playbooks"]["componentType"] == "configuration-management"
    assert components["heal_safety"]["componentType"] == "backend-server"
    assert components["heal_lock"]["componentType"] == "distributed-lock"
    assert components["heal_tests"]["componentType"] == "automated-testing"


def test_replay_produces_one_connected_graph_and_frozen_request():
    guide = load_guide()
    built = build_architecture(guide)
    architecture = built["architecture"]
    nodes = {component["id"] for component in architecture["components"]}
    edges = architecture["connections"]

    assert len(nodes) == 19
    assert len(edges) == 31
    assert len(built["acceptedDecisions"]) == 6
    assert len(built["appliedStepIds"]) == 56
    assert len(built["explanationOnlyStepIds"]) == 4
    assert all(edge["type"] in CONNECTION_TYPES for edge in edges)
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in edges)

    neighbors = {node: set() for node in nodes}
    pairs = set()
    for edge in edges:
        pair = (edge["source"], edge["target"])
        assert pair not in pairs
        pairs.add(pair)
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    reached = set()
    pending = deque([next(iter(nodes))])
    while pending:
        node = pending.popleft()
        if node in reached:
            continue
        reached.add(node)
        pending.extend(neighbors[node] - reached)
    assert reached == nodes

    assert {
        ("heal_orchestrator", "heal_safety"),
        ("heal_safety", "heal_lock"),
        ("heal_safety", "heal_queue"),
        ("heal_queue", "heal_executor"),
        ("heal_executor", "heal_targets"),
        ("heal_executor", "heal_monitor"),
        ("heal_executor", "heal_audit"),
        ("heal_analytics", "heal_trainer"),
        ("heal_console", "heal_trainer"),
    } <= pairs
    assert ("heal_orchestrator", "heal_executor") not in pairs
    assert ("heal_orchestrator", "heal_queue") not in pairs

    request = make_request(load_problem(), guide, built)
    assert request["problem"]["requirements"] == "\n".join(REQUIREMENTS)
    assert request["problem"]["constraints"] == "\n".join(CONSTRAINTS)
    assert request["problem"]["requirementRevision"].startswith("legacy-")
    assert len(request["components"]) == 19


def test_safety_tradeoffs_are_explicit_and_applied():
    guide = load_guide()
    steps = {step["stepNumber"]: step for step in guide["steps"]}
    for number, node_id, terms in (
        (
            27,
            "heal_safety",
            (
                "known",
                "reversible",
                "preapproved",
                "destructive",
                "high-blast-radius",
                "low-confidence",
                "novel",
                "operator approval",
            ),
        ),
        (39, "heal_executor", ("one instance", "canary", "verify")),
        (40, "heal_executor", ("rollback", "compensation", "verify")),
        (41, "heal_orchestrator", ("root incident", "failure domain", "sequence")),
        (58, "heal_trainer", ("shadow mode", "signed playbook", "policy")),
    ):
        step = steps[number]
        assert step["type"] == "decision_point"
        assert step["componentUpdate"]["nodeId"] == node_id
        text = " ".join(
            (step["content"], step["decision"]["chosen"],
             step["decision"]["chosenReason"])
        ).casefold()
        assert all(term in text for term in terms)

    release = steps[59]["content"].casefold()
    for target in (
        "five-minute", "above-90%", "zero observed", "100+", "audit trail"
    ):
        assert target in release
    assert "none is established by this draft alone" in release
    assert "missed timing target" in steps[27]["content"].casefold()
    assert "without human intervention" in steps[60]["content"].casefold()

    policy = steps[27]
    policy_text = " ".join(
        (
            policy["decision"]["chosen"],
            policy["componentUpdate"]["properties"]["purpose"],
        )
    ).casefold()
    assert not re.search(
        r"(?:low-confidence|blast[- ]radius).{0,40}\b\d+", policy_text
    )

    feedback_text = " ".join(
        (
            steps[49]["content"],
            steps[58]["decision"]["chosen"],
            steps[58]["decision"]["chosenReason"],
            steps[58]["componentUpdate"]["properties"]["purpose"],
        )
    ).casefold()
    assert "operator feedback" in feedback_text
    assert "feedback alone" in feedback_text
    assert "shadow" in feedback_text
    assert "policy approval" in feedback_text
