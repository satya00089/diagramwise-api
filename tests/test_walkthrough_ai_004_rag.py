"""Contract and architecture checks for the enterprise RAG walkthrough draft."""

import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "ai_004"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
COMPONENT_CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
STEP_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "decision_point",
    "scale_trigger",
    "update_component",
}
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


def load_problem():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    return next(problem for problem in problems if problem["id"] == PROBLEM_ID)


def load_guide():
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))


def test_rag_walkthrough_matches_runner_schema_and_covers_entire_brief():
    guide = GuidedWalkthrough.model_validate_json(GUIDE_PATH.read_text(encoding="utf-8"))
    problem = load_problem()

    assert guide.problem_id == PROBLEM_ID
    assert guide.totalSteps == len(guide.steps)
    assert [step.stepNumber for step in guide.steps] == list(
        range(1, guide.totalSteps + 1)
    )
    assert all(step.type in STEP_TYPES for step in guide.steps)

    expected_ids = {
        *(f"legacy-requirement:{index}" for index in range(1, len(problem["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(problem["constraints"]) + 1)),
    }
    mapped_ids = {
        requirement_id
        for step in guide.steps
        for requirement_id in step.requirementIds
    }
    assert mapped_ids == expected_ids

    phase_numbers = [
        number
        for phase in guide.phases
        for number in range(phase.stepRange[0], phase.stepRange[1] + 1)
    ]
    assert phase_numbers == list(range(1, guide.totalSteps + 1))


def test_rag_walkthrough_actions_use_catalog_properties_and_form_connected_graph():
    guide = load_guide()
    catalog = COMPONENT_CATALOG_PATH.read_text(encoding="utf-8")
    components = {}
    edge_pairs = []
    edge_ids = []

    for step in guide["steps"]:
        assert step["type"] in STEP_TYPES
        if step["type"] == "add_component":
            component = step["component"]
            assert component["nodeId"] not in components
            match = re.search(
                rf'\bid:\s*"{re.escape(component["componentType"])}"', catalog
            )
            assert match, f"unknown palette component {component['componentType']}"
            block_end = catalog.find("\n  },", match.start())
            component_block = catalog[match.start() : block_end]
            supported_properties = set(
                re.findall(r'\bkey:\s*"([^"]+)"', component_block)
            )
            assert {"componentName", "purpose"} <= set(component["properties"])
            assert set(component["properties"]) <= supported_properties
            for key, value in component["properties"].items():
                property_schema = re.search(
                    rf'\{{\s*key:\s*"{re.escape(key)}"(?P<body>.*?)(?=\n\s*\{{|\n\s*\],)',
                    component_block,
                    re.DOTALL,
                )
                if property_schema and re.search(
                    r'\btype:\s*"select"', property_schema["body"]
                ):
                    options = re.search(
                        r'options:\s*\[([^\]]*)\]', property_schema["body"], re.DOTALL
                    )
                    if options:
                        allowed_values = set(re.findall(r'"([^"]+)"', options[1]))
                        assert value in allowed_values, (
                            f"{component['componentType']}.{key} has invalid select value {value!r}"
                        )
            components[component["nodeId"]] = component

        if step["type"] == "add_connection":
            connection = step["connection"]
            assert connection["connectionType"] in CONNECTION_TYPES
            assert connection["sourceNodeId"] in components
            assert connection["targetNodeId"] in components
            edge_pairs.append(
                (connection["sourceNodeId"], connection["targetNodeId"])
            )
            edge_ids.append(connection["edgeId"])

        if step.get("componentUpdate"):
            assert step["componentUpdate"]["nodeId"] in components
            assert step["componentUpdate"]["properties"]

    assert len(edge_ids) == len(set(edge_ids))
    neighbors = {node_id: set() for node_id in components}
    for source, target in edge_pairs:
        neighbors[source].add(target)
        neighbors[target].add(source)

    reached = set()
    pending = [next(iter(components))]
    while pending:
        node_id = pending.pop()
        if node_id in reached:
            continue
        reached.add(node_id)
        pending.extend(neighbors[node_id] - reached)
    assert reached == set(components)

    # There is no first-party source-connector palette item, so this is the sole
    # justified generic custom component in the draft.
    assert [
        component["label"]
        for component in components.values()
        if component["componentType"] == "custom-component"
    ] == ["Enterprise Source Connectors"]


def test_rag_walkthrough_replays_as_a_save_reload_safe_architecture():
    guide = load_guide()
    architecture = build_architecture(guide)["architecture"]
    node_ids = {component["id"] for component in architecture["components"]}

    assert len(architecture["components"]) == 18
    assert len(architecture["connections"]) == 25
    assert all(
        edge["source"] in node_ids and edge["target"] in node_ids
        for edge in architecture["connections"]
    )


def test_rag_walkthrough_teaches_evaluation_not_guaranteed_scores():
    text = json.dumps(load_guide(), ensure_ascii=False).casefold()
    for required_concept in (
        "recall@10",
        "hallucination",
        "under 3 seconds",
        "100k documents",
        "1k concurrent",
        "dense",
        "sparse",
        "rerank",
        "follow-up",
        "abstention",
        "citation",
        "feedback",
        "acl",
        "chunk",
    ):
        assert required_concept in text
    assert "not something this architecture can guarantee" in text
