"""Focused structural review gates for the aiops_003 RCA walkthrough draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / "aiops_003.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

ACTION_TYPES = {"add_component", "add_connection", "decision_point"}
STEP_TYPES = ACTION_TYPES | {"explanation", "scale_trigger"}
CONNECTION_TYPES = {
    "api-call",
    "database-connection",
    "data-flow",
    "event-stream",
    "message-queue",
}
DIRECT_ACTION_EVIDENCE = {
    "Correlate metrics, logs, and traces for root cause": {
        "rca_09", "rca_10", "rca_11", "rca_19"
    },
    "Build and maintain service dependency graphs": {"rca_23", "rca_24", "rca_25"},
    "Identify causal chains from symptom to root cause": {
        "rca_27", "rca_30", "rca_38", "rca_39"
    },
    "Analyze deployment changes as potential causes": {"rca_12", "rca_17", "rca_38"},
    "Score and rank probable root causes": {"rca_30", "rca_38", "rca_41"},
    "Provide evidence and reasoning for each hypothesis": {"rca_29", "rca_31", "rca_40"},
    "Learn from operator feedback on correctness": {
        "rca_29", "rca_31", "rca_43", "rca_45", "rca_48"
    },
    "Integrate with monitoring and deployment systems": {"rca_09", "rca_12", "rca_28"},
}
DIRECT_CONSTRAINT_EVIDENCE = {
    "Root cause identification within 5 minutes": {"rca_34"},
    "Accuracy above 80% for top-3 suggested causes": {"rca_46"},
    "Handle 100+ services with 1000+ metrics each": {"rca_19"},
    "Process 1TB+ of observability data daily": {"rca_13", "rca_21"},
    "Support both infrastructure and application issues": {"rca_09"},
}


def _load() -> tuple[dict, GuidedWalkthrough]:
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def _frozen_problem() -> dict:
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == "aiops_003")


def _render_frozen_brief(problem: dict) -> str:
    lines = [f"Title: {problem['title']}", f"Description: {problem['description']}"]
    for field in ("requirements", "constraints", "hints"):
        lines.append(f"{field.title()}:")
        lines.extend(f"- {item}" for item in problem[field])
    return "\n".join(lines)


def _brief_anchors(problem: dict) -> set[str]:
    return {
        *(f"legacy-requirement:{number}" for number in range(1, len(problem["requirements"]) + 1)),
        *(f"legacy-constraint:{number}" for number in range(1, len(problem["constraints"]) + 1)),
    }


def _catalog_entry(catalog: str, component_id: str) -> str:
    match = re.search(
        rf'(?ms)^ {{4}}id: "{re.escape(component_id)}",.*?^ {{2}}\}},?', catalog
    )
    assert match, f"Unknown component catalog ID: {component_id}"
    return match.group(0)


def _assert_catalog_properties(component: dict, properties: dict, catalog: str) -> None:
    entry = _catalog_entry(catalog, component["componentType"])
    supported = set(re.findall(r'\bkey:\s*"([^"]+)"', entry))
    assert properties and set(properties) <= supported, (
        f"{component['componentType']} has unsupported properties "
        f"{sorted(set(properties) - supported)}"
    )

    for key, value in properties.items():
        start = re.search(rf'\{{\s*key:\s*"{re.escape(key)}"', entry)
        assert start, f"Missing catalog definition for {component['componentType']}.{key}"
        remaining = entry[start.start():]
        following = re.search(r'\n\s*\{\s*key:', remaining[1:])
        property_block = remaining[:following.start() + 1] if following else remaining
        field_type = re.search(r'\btype:\s*"([^"]+)"', property_block)
        assert field_type, f"Missing catalog type for {component['componentType']}.{key}"
        if field_type[1] == "boolean":
            assert type(value) is bool
        elif field_type[1] == "number":
            assert type(value) in (int, float)
        elif field_type[1] == "select":
            options = re.search(r'\boptions:\s*\[([^\]]*)\]', property_block, re.DOTALL)
            assert options, f"Missing select options for {component['componentType']}.{key}"
            assert value in set(re.findall(r'"([^"]+)"', options[1]))


def test_live_brief_is_preserved_verbatim_and_schema_is_valid():
    raw, guide = _load()
    problem = _frozen_problem()

    assert _render_frozen_brief(problem) in guide.steps[0].content
    assert guide.problem_id == problem["id"] == "aiops_003"
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 51
    assert [step.stepNumber for step in guide.steps] == list(range(1, 52))
    assert len({step.id for step in guide.steps}) == len(guide.steps)
    assert all(step.type in STEP_TYPES for step in guide.steps)
    assert raw["totalSteps"] == len(raw["steps"])

    phases = raw["phases"]
    assert [
        (phase["name"], phase["stepRange"][0], phase["stepRange"][1])
        for phase in phases
    ] == [
        ("1. Define the diagnosis contract", 1, 8),
        ("2. Ingest evidence and maintain service context", 9, 26),
        ("3. Produce and explain ranked root-cause hypotheses", 27, 42),
        ("4. Learn from feedback and validate the stated targets", 43, 51),
    ]
    next_number = 1
    for phase in phases:
        start, end = phase["stepRange"]
        assert start == next_number and start <= end
        assert phase["description"].strip()
        assert all(raw["steps"][number - 1]["phase"] == phase["name"] for number in range(start, end + 1))
        next_number = end + 1
    assert next_number == 52

    for step in raw["steps"]:
        if step["type"] == "decision_point":
            assert step["decision"]["chosen"]
            assert step["decision"]["chosenReason"]
            assert len(step["decision"]["alternatives"]) >= 2
            assert step["componentUpdate"]["properties"]
        elif step["type"] == "scale_trigger":
            assert all(step["scaleTrigger"][key] for key in ("metric", "action", "impact"))


def test_every_brief_anchor_has_an_explicit_architecture_action():
    raw, _ = _load()
    problem = _frozen_problem()
    observed = {anchor for step in raw["steps"] for anchor in step.get("requirementIds", [])}
    actionable = {
        anchor
        for step in raw["steps"]
        if step["type"] in ACTION_TYPES
        for anchor in step.get("requirementIds", [])
    }
    assert observed == actionable == _brief_anchors(problem)


def test_each_frozen_brief_item_has_semantically_direct_action_evidence():
    raw, _ = _load()
    problem = _frozen_problem()
    steps = {step["id"]: step for step in raw["steps"]}

    for field, prefix, evidence_by_item in (
        ("requirements", "legacy-requirement", DIRECT_ACTION_EVIDENCE),
        ("constraints", "legacy-constraint", DIRECT_CONSTRAINT_EVIDENCE),
    ):
        assert set(evidence_by_item) == set(problem[field])
        for item, step_ids in evidence_by_item.items():
            anchor = f"{prefix}:{problem[field].index(item) + 1}"
            assert step_ids
            for step_id in step_ids:
                step = steps[step_id]
                assert step["type"] in ACTION_TYPES
                assert anchor in step.get("requirementIds", [])


def test_components_connections_and_updates_use_the_existing_catalog():
    raw, _ = _load()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}
    edge_ids = set()

    for step in raw["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            assert component["nodeId"] not in components
            assert set(component["position"]) == {"x", "y"}
            assert component["properties"]["componentName"] == component["label"]
            assert component["properties"]["purpose"].strip()
            assert component["description"].strip() and component["highlightReason"].strip()
            _assert_catalog_properties(component, component["properties"], catalog)
            components[component["nodeId"]] = component
        elif step["type"] == "add_connection":
            connection = step["connection"]
            assert connection["edgeId"] not in edge_ids
            edge_ids.add(connection["edgeId"])
            assert connection["sourceNodeId"] in components
            assert connection["targetNodeId"] in components
            assert connection["connectionType"] in CONNECTION_TYPES
            assert connection["label"] and connection["description"]
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            assert update["nodeId"] in components
            _assert_catalog_properties(
                components[update["nodeId"]], update["properties"], catalog
            )

    custom_components = [
        component for component in components.values()
        if component["componentType"] == "custom-component"
    ]
    assert len(custom_components) == 1
    assert custom_components[0]["nodeId"] == "rca_trace_adapter"
    assert len(components) == 15
    assert len(edge_ids) == 19


def test_replay_produces_one_connected_architecture_and_feedback_loop():
    raw, _ = _load()
    built = build_architecture(raw)
    architecture = built["architecture"]
    nodes = {component["id"] for component in architecture["components"]}
    edges = architecture["connections"]

    assert len(nodes) == 15
    assert len(edges) == 19
    assert len(built["acceptedDecisions"]) == 4
    assert all(edge["type"] in CONNECTION_TYPES for edge in edges)
    pairs = set()
    adjacency = {node: set() for node in nodes}
    for edge in edges:
        pair = (edge["source"], edge["target"])
        assert pair not in pairs
        pairs.add(pair)
        assert edge["source"] in nodes and edge["target"] in nodes
        adjacency[edge["source"]].add(edge["target"])
        adjacency[edge["target"]].add(edge["source"])

    reached = set()
    pending = deque(["rca_metrics_source"])
    while pending:
        node = pending.popleft()
        if node in reached:
            continue
        reached.add(node)
        pending.extend(adjacency[node] - reached)
    assert reached == nodes
    assert {
        ("rca_correlator", "rca_coordinator"),
        ("rca_coordinator", "rca_ranker"),
        ("rca_coordinator", "rca_case_store"),
        ("rca_case_store", "rca_model_training"),
        ("rca_model_training", "rca_model_registry"),
        ("rca_model_registry", "rca_ranker"),
    } <= pairs
