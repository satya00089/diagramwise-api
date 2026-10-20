"""Exact frozen-brief anchor placement for the Web Search Engine walkthrough."""

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "68d7013f6f42e23bb16a2231"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
GRAPH_ACTION_TYPES = {"add_component", "add_connection", "update_component"}

EXPECTED_ACTION_REFERENCES = {
    "ws_03": {"legacy-requirement:5"},
    "ws_04": {"legacy-requirement:3", "legacy-constraint:1"},
    "ws_05": {
        "legacy-requirement:2",
        "legacy-requirement:3",
        "legacy-constraint:1",
    },
    "ws_08": {
        "legacy-requirement:2",
        "legacy-requirement:3",
        "legacy-constraint:1",
    },
    "ws_15": {
        "legacy-requirement:7",
        "legacy-constraint:3",
        "legacy-constraint:5",
    },
    "ws_17": {"legacy-requirement:5", "legacy-constraint:5"},
    "ws_18": {"legacy-requirement:5"},
    "ws_19": {"legacy-requirement:5"},
    "ws_21": {
        "legacy-requirement:1",
        "legacy-requirement:3",
        "legacy-requirement:4",
        "legacy-constraint:3",
        "legacy-constraint:4",
        "legacy-constraint:5",
    },
    "ws_22": {"legacy-requirement:7", "legacy-constraint:3"},
    "ws_23": {
        "legacy-requirement:2",
        "legacy-requirement:3",
        "legacy-requirement:6",
        "legacy-constraint:1",
    },
    "ws_26": {"legacy-requirement:2", "legacy-constraint:1"},
    "ws_27": {"legacy-requirement:2", "legacy-constraint:1"},
    "ws_32": {
        "legacy-requirement:1",
        "legacy-constraint:2",
        "legacy-constraint:4",
    },
    "ws_33": {"legacy-constraint:2", "legacy-constraint:4"},
    "ws_35": {"legacy-requirement:1", "legacy-constraint:4"},
    "ws_48": {"legacy-requirement:4", "legacy-constraint:5"},
    "ws_50": {"legacy-requirement:4", "legacy-constraint:5"},
    "ws_53": {
        "legacy-requirement:1",
        "legacy-constraint:2",
        "legacy-constraint:4",
    },
    "ws_55": {"legacy-requirement:6"},
    "ws_57": {"legacy-requirement:6"},
    "ws_58": {"legacy-constraint:2"},
    "ws_66": {"legacy-constraint:2"},
}


def test_web_search_engine_graph_actions_have_exact_frozen_brief_anchors():
    guide = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)

    assert guide["problem_id"] == PROBLEM_ID
    expected_anchors = {
        *(f"legacy-requirement:{index}" for index in range(1, len(problem["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(problem["constraints"]) + 1)),
    }

    actions = {
        step["id"]: set(step.get("requirementIds", []))
        for step in guide["steps"]
        if step["type"] in GRAPH_ACTION_TYPES and step.get("requirementIds")
    }
    assert actions == EXPECTED_ACTION_REFERENCES

    action_anchors = set().union(*actions.values())
    all_anchors = {
        anchor for step in guide["steps"] for anchor in step.get("requirementIds", [])
    }
    assert action_anchors == expected_anchors
    assert all_anchors == action_anchors


def test_search_index_sizing_is_measured_not_fixed_by_the_brief():
    guide = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    steps = {step["id"]: step for step in guide["steps"]}

    for step_id in ("ws_17", "ws_21"):
        properties = steps[step_id]["component"]["properties"]
        assert not {"shards", "partitions", "replicas"}.intersection(properties)
        purpose = properties["purpose"].lower().replace("-", " ")
        assert "measured" in purpose
        assert "load test" in purpose
        assert "brief does not prescribe counts" in purpose
        assert re.search(
            r"\b\d+\s+(?:shards?|partitions?)\b",
            json.dumps(properties),
            re.IGNORECASE,
        ) is None
