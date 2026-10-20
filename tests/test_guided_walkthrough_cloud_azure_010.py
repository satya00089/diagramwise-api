"""Focused contract tests for the Cognitive AI Application review draft."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_azure_010"
GUIDE_PATH = ROOT / "data/guided-walkthroughs/cloud_azure_010.json"
PROBLEMS_PATH = ROOT / "tests/fixtures/walkthroughs/problems.json"
COMPONENTS_PATH = ROOT.parent / "diagrammatic/src/config/components.ts"

FROZEN_BRIEF = {
    "id": PROBLEM_ID,
    "title": "Build a Cognitive AI Application",
    "description": (
        "Design an AI application that processes text, images, and speech, provides "
        "conversational AI, understands user intent, and answers questions from knowledge bases."
    ),
    "requirements": [
        "Implement conversational AI bot",
        "Understand natural language",
        "Extract intents and entities",
        "Answer frequently asked questions",
        "Perform sentiment analysis",
        "Integrate with multiple channels",
        "Customize bot responses",
        "Monitor bot conversations",
    ],
    "constraints": [
        "Response latency under 2 seconds",
        "Support 10k+ concurrent conversations",
        "Accuracy rate above 85%",
        "Handle multi-turn conversations",
        "Support multiple languages",
    ],
    "hints": [
        "Bot Service for bot framework",
        "LUIS for language understanding",
        "QnA Maker for knowledge base",
        "Text Analytics for sentiment",
        "Cognitive Search for enhanced answers",
        "Application Insights for analytics",
    ],
}

EXPECTED_STEP_ANCHORS = {
    "cai_07": {"legacy-requirement:6"},
    "cai_08": {"legacy-requirement:6"},
    "cai_09": {"legacy-requirement:6"},
    "cai_10": {"legacy-constraint:2"},
    "cai_11": {"legacy-requirement:6", "legacy-constraint:1"},
    "cai_12": {"legacy-requirement:6"},
    "cai_13": {"legacy-requirement:1", "legacy-requirement:7"},
    "cai_14": {"legacy-requirement:1"},
    "cai_15": {"legacy-requirement:6"},
    "cai_17": set(),
    "cai_18": {"legacy-requirement:1", "legacy-requirement:7"},
    "cai_19": {"legacy-requirement:1", "legacy-requirement:7"},
    "cai_20": set(),
    "cai_21": set(),
    "cai_22": {"legacy-requirement:2", "legacy-requirement:3", "legacy-constraint:5"},
    "cai_23": {"legacy-requirement:2", "legacy-requirement:3", "legacy-constraint:5"},
    "cai_24": {"legacy-requirement:2", "legacy-requirement:3", "legacy-constraint:5"},
    "cai_25": {"legacy-requirement:5"},
    "cai_26": {"legacy-requirement:5"},
    "cai_27": {"legacy-requirement:5"},
    "cai_29": {"legacy-requirement:4"},
    "cai_30": {"legacy-requirement:4"},
    "cai_31": {"legacy-requirement:4"},
    "cai_32": {"legacy-requirement:4"},
    "cai_33": {"legacy-requirement:4"},
    "cai_35": {"legacy-constraint:2", "legacy-constraint:4"},
    "cai_36": {"legacy-constraint:2", "legacy-constraint:4"},
    "cai_38": {"legacy-requirement:8"},
    "cai_39": {"legacy-requirement:8", "legacy-constraint:1"},
    "cai_40": {"legacy-constraint:3"},
    "cai_41": {"legacy-constraint:3"},
    "cai_42": {"legacy-requirement:7", "legacy-constraint:3"},
    "cai_43": {"legacy-constraint:5"},
    "cai_44": {"legacy-constraint:2"},
    "cai_45": {"legacy-constraint:2", "legacy-constraint:4"},
    "cai_46": {
        "legacy-requirement:2",
        "legacy-requirement:4",
        "legacy-constraint:2",
        "legacy-constraint:5",
    },
    "cai_47": {"legacy-requirement:4", "legacy-constraint:1"},
}

NON_REQUIREMENT_KEYS = {
    "edgeId",
    "id",
    "nodeId",
    "position",
    "problem_id",
    "requirementIds",
    "stepNumber",
    "stepRange",
    "version",
}


def _load_guide() -> dict:
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return GuidedWalkthrough.model_validate(raw).model_dump(exclude_none=True)


def _problem_from_frozen_fixture() -> dict:
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    matches = [problem for problem in problems if problem["id"] == PROBLEM_ID]
    assert len(matches) == 1
    return matches[0]


def _catalog_blocks() -> dict[str, str]:
    source = COMPONENTS_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        r'^  \{\n    id: "(?P<id>[^"]+)",(?P<body>.*?)^  \},?$',
        re.MULTILINE | re.DOTALL,
    )
    return {match.group("id"): match.group(0) for match in pattern.finditer(source)}


def _catalog_properties(block: str) -> set[str]:
    return set(re.findall(r'^\s*key: "([^"]+)"', block, re.MULTILINE))


def _narrative_strings(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            if key not in NON_REQUIREMENT_KEYS:
                yield from _narrative_strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _narrative_strings(nested)
    elif isinstance(value, str):
        yield value


def test_frozen_problem_brief_matches_the_independent_contract():
    problem = _problem_from_frozen_fixture()

    assert {key: problem[key] for key in FROZEN_BRIEF} == FROZEN_BRIEF
    assert problem["has_guided_walkthrough"] is False


def test_review_draft_is_pydantic_valid_and_has_contiguous_unique_steps_and_phases():
    guide = _load_guide()
    steps = guide["steps"]
    total = guide["totalSteps"]

    assert guide["problem_id"] == PROBLEM_ID
    assert guide["version"] == "1.0.0-review-draft"
    assert "supplied description" in steps[0]["content"]
    assert "Working assumptions, not supplied requirements" in steps[1]["content"]
    assert steps[0]["requirementIds"] == steps[1]["requirementIds"] == []
    assert 35 <= total <= 60
    assert total == len(steps)
    assert [step["stepNumber"] for step in steps] == list(range(1, total + 1))
    assert len({step["id"] for step in steps}) == total

    expected_start = 1
    for phase in guide["phases"]:
        start, end = phase["stepRange"]
        assert start == expected_start
        assert start <= end
        assert all(steps[number - 1]["phase"] == phase["name"] for number in range(start, end + 1))
        expected_start = end + 1
    assert expected_start == total + 1


def test_every_frozen_requirement_and_constraint_is_anchored_to_a_graph_action():
    guide = _load_guide()
    expected_anchors = {
        *(f"legacy-requirement:{index}" for index in range(1, len(FROZEN_BRIEF["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(FROZEN_BRIEF["constraints"]) + 1)),
    }
    all_anchors = {
        anchor for step in guide["steps"] for anchor in step["requirementIds"]
    }
    graph_actions = [
        step for step in guide["steps"] if step["type"] in {"add_component", "add_connection"}
    ]
    graph_action_anchors = {
        anchor for step in graph_actions for anchor in step["requirementIds"]
    }

    assert all_anchors == expected_anchors
    assert graph_action_anchors == expected_anchors

    actual_by_step = {
        step["id"]: set(step["requirementIds"])
        for step in guide["steps"]
        if step["type"] in {"add_component", "add_connection"} or step["requirementIds"]
    }
    assert actual_by_step == EXPECTED_STEP_ANCHORS


def test_latency_accuracy_and_concurrency_targets_stay_distinct_from_assumptions():
    guide = _load_guide()
    by_id = {step["id"]: step for step in guide["steps"]}

    assumptions = by_id["cai_02"]["content"]
    latency = by_id["cai_03"]["content"]
    accuracy = by_id["cai_04"]["content"]
    concurrency = by_id["cai_05"]["content"]
    quality_gate = by_id["cai_40"]["content"]

    assert "Working assumptions, not supplied requirements" in assumptions
    assert "response latency under two seconds" in latency
    assert "does not define the start/stop events, percentile" in latency
    assert "do not quietly substitute a time-to-first-token or an average" in latency
    assert "accuracy above 85%" in accuracy
    assert "does not define a labeled set" in accuracy
    assert "strictly greater than 85%" in accuracy
    assert "10k+ concurrent conversations, not a requests-per-second figure" in concurrency
    assert "strictly above 85%" in quality_gate


def test_numeric_performance_claims_are_limited_to_frozen_brief_targets():
    guide = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    narrative = " ".join(_narrative_strings(guide))
    numeric_claims = set(
        re.findall(
            r"(?<![A-Za-z0-9])\d+(?:,\d{3})*(?:\.\d+)?(?:[kKmMbB]\+?)?(?![A-Za-z0-9])",
            narrative,
        )
    )

    assert numeric_claims <= {"2", "85", "10k+"}
    assert {"85", "10k+"} <= numeric_claims


def test_components_use_catalog_types_and_only_catalog_supported_properties():
    guide = _load_guide()
    catalog = _catalog_blocks()
    component_steps = [step for step in guide["steps"] if step["type"] == "add_component"]

    assert component_steps
    for step in component_steps:
        component = step["component"]
        component_type = component["componentType"]
        assert component_type in catalog, f"{step['id']} uses unknown component type {component_type!r}"
        supported = _catalog_properties(catalog[component_type])
        unsupported = set(component["properties"]) - supported
        assert not unsupported, f"{step['id']} uses unsupported {component_type} properties: {sorted(unsupported)}"


def test_ordered_replay_has_prior_node_edges_and_a_connected_final_graph():
    guide = _load_guide()
    replay_input = deepcopy(guide)
    replay_input["steps"].reverse()
    built = build_architecture(replay_input)
    ordered_steps = sorted(guide["steps"], key=lambda step: step["stepNumber"])
    expected_applied = [
        step["id"] for step in ordered_steps if step["type"] in {"add_component", "add_connection"}
    ]

    assert built["appliedStepIds"] == expected_applied

    prior_nodes: set[str] = set()
    for step in ordered_steps:
        if step["type"] == "add_component":
            prior_nodes.add(step["component"]["nodeId"])
        elif step["type"] == "add_connection":
            connection = step["connection"]
            assert connection["sourceNodeId"] in prior_nodes
            assert connection["targetNodeId"] in prior_nodes

    architecture = built["architecture"]
    nodes = {node["id"] for node in architecture["components"]}
    assert nodes
    adjacency = {node_id: set() for node_id in nodes}
    for edge in architecture["connections"]:
        assert edge["source"] in nodes
        assert edge["target"] in nodes
        adjacency[edge["source"]].add(edge["target"])
        adjacency[edge["target"]].add(edge["source"])

    reached: set[str] = set()
    frontier = [next(iter(nodes))]
    while frontier:
        current = frontier.pop()
        if current in reached:
            continue
        reached.add(current)
        frontier.extend(adjacency[current] - reached)
    assert reached == nodes
