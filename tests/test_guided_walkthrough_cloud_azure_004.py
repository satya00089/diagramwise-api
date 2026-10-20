"""Focused frozen-brief and structural checks for the Azure warehouse draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_azure_004"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

TITLE = "Design an Enterprise Data Warehouse Solution"
DESCRIPTION = (
    "Design a data warehouse solution that ingests data from multiple sources, "
    "transforms and cleanses data, runs complex analytical queries, and creates "
    "interactive dashboards."
)
REQUIREMENTS = [
    "Ingest data from multiple sources",
    "Transform and cleanse data",
    "Store structured and semi-structured data",
    "Run complex analytical queries",
    "Create interactive dashboards",
    "Implement data governance",
    "Schedule ETL pipelines",
    "Support business intelligence",
]
CONSTRAINTS = [
    "Query performance under 5 seconds",
    "Support concurrent users (500+)",
    "Handle petabyte-scale data",
    "Minimize ETL processing time",
    "Cost-effective storage and compute",
]
HINTS = [
    "Synapse Analytics for warehousing",
    "Data Lake Storage Gen2 for storage",
    "Data Factory for ETL orchestration",
    "Power BI for visualization",
    "PolyBase for data integration",
    "Dedicated SQL pools for performance",
]

EXPECTED_ANCHORS = {
    *(f"legacy-requirement:{number}" for number in range(1, 9)),
    *(f"legacy-constraint:{number}" for number in range(1, 6)),
}
GRAPH_ACTION_TYPES = {"add_component", "add_connection"}
EXPECTED_COMPONENT_TYPES = {
    "source_systems": "custom-component",
    "data_factory": "custom-component",
    "data_lake": "object-storage",
    "synapse_warehouse": "data-warehouse",
    "power_bi": "custom-component",
    "governance_controls": "custom-component",
}
EXPECTED_CONNECTION_PAIRS = {
    ("source_systems", "data_factory"),
    ("data_factory", "data_lake"),
    ("data_lake", "synapse_warehouse"),
    ("data_factory", "synapse_warehouse"),
    ("synapse_warehouse", "power_bi"),
    ("governance_controls", "data_lake"),
    ("governance_controls", "synapse_warehouse"),
    ("governance_controls", "power_bi"),
}


def _load() -> tuple[dict, dict, GuidedWalkthrough]:
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    return raw, problem, GuidedWalkthrough.model_validate(raw)


def _brief_prefix(problem: dict) -> str:
    lines = [
        "Problem brief copied verbatim from the frozen problem fixture:",
        f"Title: {problem['title']}",
        f"Description: {problem['description']}",
        "Requirements:",
        *(f"- {item}" for item in problem["requirements"]),
        "Constraints:",
        *(f"- {item}" for item in problem["constraints"]),
        "Hints:",
        *(f"- {item}" for item in problem["hints"]),
        "",
    ]
    return "\n".join(lines)


def _catalog_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'(?m)^    id:\s*"{re.escape(component_type)}"', catalog)
    assert match, f"Unknown component catalog ID: {component_type}"
    end = catalog.find("\n  },", match.start())
    assert end > match.start(), f"Could not bound catalog component: {component_type}"
    return catalog[match.start() : end]


def _assert_supported_properties(component_type: str, properties: dict, catalog: str) -> None:
    block = _catalog_block(catalog, component_type)
    keys = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
    assert set(properties) <= keys, (
        f"Unsupported {component_type} properties: {set(properties) - keys}"
    )

    for key, value in properties.items():
        marker = re.search(rf'\bkey:\s*"{re.escape(key)}"', block)
        assert marker, f"Missing catalog definition for {component_type}.{key}"
        remainder = block[marker.start() :]
        next_property = re.search(r"\n\s*\{\s*key:", remainder[1:])
        property_block = remainder[: next_property.start() + 1] if next_property else remainder
        field_type = re.search(r'\btype:\s*"([^"]+)"', property_block)
        assert field_type, f"Missing field type for {component_type}.{key}"
        if field_type[1] == "boolean":
            assert type(value) is bool
        elif field_type[1] == "number":
            assert type(value) in (int, float)
        elif field_type[1] == "select":
            options = re.search(r"\boptions:\s*\[([^\]]*)\]", property_block, re.DOTALL)
            assert options, f"Missing select options for {component_type}.{key}"
            assert value in set(re.findall(r'"([^"]+)"', options[1]))


def _step_text(step: dict) -> list[str]:
    texts = [step["title"], step["content"]]
    component = step.get("component")
    if component:
        texts.extend(
            [component["label"], component["description"], component["highlightReason"]]
        )
        texts.extend(str(value) for value in component.get("properties", {}).values())
    connection = step.get("connection")
    if connection:
        texts.extend([connection["label"], connection["description"]])
    decision = step.get("decision")
    if decision:
        texts.extend(
            [decision["question"], decision["chosen"], decision["chosenReason"]]
        )
        texts.extend(
            text
            for alternative in decision.get("alternatives", [])
            for text in (alternative["option"], alternative["tradeoff"])
        )
    trigger = step.get("scaleTrigger")
    if trigger:
        texts.extend([trigger["metric"], trigger["action"], trigger["impact"]])
    return texts


def _combined_step_text(steps_by_number: dict[int, dict], numbers: tuple[int, ...]) -> str:
    return " ".join(
        text
        for number in numbers
        for text in _step_text(steps_by_number[number])
    ).lower()


def _has_unbrief_numeric_value(text: str, brief_numbers: set[str]) -> bool:
    # Gen2 is part of the exact supplied service name, not a workload value.
    numeric_text = re.sub(r"\bGen2\b", "", text)
    return any(
        value not in brief_numbers
        for value in re.findall(r"(?<!\w)\d+(?:\.\d+)?(?!\w)", numeric_text)
    )


def test_frozen_brief_fixture_matches_walkthrough_and_remains_unpublished():
    raw, problem, guide = _load()

    assert problem["id"] == PROBLEM_ID
    assert problem["title"] == TITLE
    assert problem["description"] == DESCRIPTION
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert problem["hints"] == HINTS
    assert problem["has_guided_walkthrough"] is False
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert raw["steps"][0]["content"].startswith(_brief_prefix(problem))


def test_schema_phases_and_requirement_anchor_coverage():
    raw, problem, guide = _load()
    assert guide.totalSteps == len(guide.steps) == 42
    assert 35 <= guide.totalSteps <= 60
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps

    covered_numbers = []
    for phase in guide.phases:
        start, end = phase.stepRange
        expected_start = covered_numbers[-1] + 1 if covered_numbers else 1
        assert start == expected_start
        covered_numbers.extend(range(start, end + 1))
        assert all(
            step.phase == phase.name
            for step in guide.steps
            if start <= step.stepNumber <= end
        )
    assert covered_numbers == list(range(1, guide.totalSteps + 1))

    anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert anchors == EXPECTED_ANCHORS
    graph_action_anchors = {
        anchor
        for step in raw["steps"]
        if step["type"] in GRAPH_ACTION_TYPES
        for anchor in step.get("requirementIds", [])
    }
    assert graph_action_anchors == EXPECTED_ANCHORS

    brief_numbers = set(
        re.findall(r"(?<!\w)\d+(?:\.\d+)?(?!\w)", _brief_prefix(problem))
    )
    for step in raw["steps"][1:]:
        assert not any(
            _has_unbrief_numeric_value(text, brief_numbers) for text in _step_text(step)
        ), (
            f"{step['id']} introduces a numeric value beyond the copied brief"
        )


def test_supplied_scale_constraints_are_measured_in_the_walkthrough():
    raw, problem, _ = _load()
    steps_by_number = {step["stepNumber"]: step for step in raw["steps"]}
    query_text = _combined_step_text(steps_by_number, (23,))
    concurrency_text = _combined_step_text(steps_by_number, (24,))
    scale_text = _combined_step_text(steps_by_number, (40,))
    acceptance_text = _combined_step_text(steps_by_number, (41,))

    assert problem["constraints"][0] == "Query performance under 5 seconds"
    assert "under 5 seconds" in query_text
    assert "measure" in query_text and "repeatable" in acceptance_text

    assert problem["constraints"][1] == "Support concurrent users (500+)"
    assert "500+" in concurrency_text
    assert "concurrent users" in concurrency_text
    assert "session" in concurrency_text
    assert "derive the resulting query and session load from that profile" in concurrency_text

    assert problem["constraints"][2] == "Handle petabyte-scale data"
    assert "petabyte-scale" in scale_text
    assert "before claiming" in scale_text

    assert problem["constraints"][3].lower() == "minimize etl processing time"
    etl_text = _combined_step_text(steps_by_number, (15, 25, 41))
    assert "reduces etl processing time" in etl_text
    assert "cost-effective storage and compute" in acceptance_text


def test_component_catalog_and_properties_are_supported():
    raw, _, _ = _load()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step["type"] == "add_component"
    }
    assert {
        node_id: component["componentType"] for node_id, component in additions.items()
    } == EXPECTED_COMPONENT_TYPES

    for component in additions.values():
        assert set(component["position"]) == {"x", "y"}
        assert component["properties"]["componentName"] == component["label"]
        assert len(component["properties"]["purpose"]) >= 40
        _assert_supported_properties(component["componentType"], component["properties"], catalog)


def test_ordered_replay_produces_the_expected_connected_architecture():
    raw, _, _ = _load()
    added_nodes = set()
    edge_ids = set()
    action_ids = []
    for step in raw["steps"]:
        if step["type"] == "add_component":
            node_id = step["component"]["nodeId"]
            assert node_id not in added_nodes
            added_nodes.add(node_id)
            action_ids.append(step["id"])
        elif step["type"] == "add_connection":
            edge = step["connection"]
            assert edge["sourceNodeId"] in added_nodes
            assert edge["targetNodeId"] in added_nodes
            assert edge["edgeId"] not in edge_ids
            edge_ids.add(edge["edgeId"])
            action_ids.append(step["id"])

    built = build_architecture(raw)
    architecture = built["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    edges = architecture["connections"]
    assert set(nodes) == set(EXPECTED_COMPONENT_TYPES)
    assert built["appliedStepIds"] == action_ids
    assert built["provenance"]["problemId"] == PROBLEM_ID
    assert built["provenance"]["walkthroughVersion"] == "1.0.0-review-draft"

    actual_pairs = set()
    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] and edge["label"] and edge["description"]
        actual_pairs.add((edge["source"], edge["target"]))
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    assert actual_pairs == EXPECTED_CONNECTION_PAIRS

    reached = set()
    pending = deque(["source_systems"])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    assert reached == nodes.keys()
