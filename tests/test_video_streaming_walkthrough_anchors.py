"""Requirement and constraint anchor coverage for the video streaming walkthrough."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "68d7013f6f42e23bb16a222f"
GRAPH_ACTION_TYPES = {"add_component", "add_connection"}
FROZEN_BRIEF = {
    "id": PROBLEM_ID,
    "title": "Video Streaming Platform",
    "description": (
        "Design a video streaming service like YouTube or Netflix that can serve "
        "millions of concurrent viewers."
    ),
    "requirements": [
        "Upload and store video content",
        "Stream videos to millions of users",
        "Support different video qualities (480p, 720p, 1080p, 4K)",
        "Adaptive bitrate streaming",
        "Search and recommendation system",
        "User profiles and watch history",
        "Global content delivery",
    ],
    "constraints": [
        "Minimize video startup time (<2 seconds)",
        "Handle peak traffic during popular releases",
        "Support multiple devices and browsers",
        "Efficient storage for large video files",
        "Copyright protection and DRM",
    ],
    "hints": [
        "Video transcoding pipeline",
        "CDN for global content delivery",
        "Metadata database for search",
        "Machine learning for recommendations",
        "Chunked video storage for adaptive streaming",
    ],
}


def _is_graph_action(step):
    return step["type"] in GRAPH_ACTION_TYPES or (
        step["type"] == "decision_point" and "componentUpdate" in step
    )


def test_frozen_requirements_and_constraints_are_anchored_on_graph_actions():
    problems = json.loads(
        (ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json").read_text(
            encoding="utf-8"
        )
    )
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    assert {key: problem[key] for key in FROZEN_BRIEF} == FROZEN_BRIEF

    guide = json.loads(
        (ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json").read_text(
            encoding="utf-8"
        )
    )

    expected_anchors = {
        *(f"legacy-requirement:{index}" for index in range(1, len(problem["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(problem["constraints"]) + 1)),
    }
    graph_actions = [step for step in guide["steps"] if _is_graph_action(step)]
    action_ids = {step["id"] for step in graph_actions}
    actual_anchors = {
        anchor
        for step in graph_actions
        for anchor in step.get("requirementIds", [])
    }

    assert guide["problem_id"] == PROBLEM_ID
    assert actual_anchors == expected_anchors
    for step in guide["steps"]:
        anchors = step.get("requirementIds", [])
        assert len(anchors) == len(set(anchors)), f"{step['id']}: duplicate anchor"
        assert set(anchors) <= expected_anchors
        if anchors:
            assert step["id"] in action_ids, f"{step['id']}: anchor is not on a graph action"

    def anchor(field, statement):
        kind = "requirement" if field == "requirements" else "constraint"
        index = problem[field].index(statement) + 1
        return f"legacy-{kind}:{index}"

    anchors_by_step = {
        step["id"]: set(step.get("requirementIds", [])) for step in graph_actions
    }
    search_anchor = anchor("requirements", FROZEN_BRIEF["requirements"][4])
    rights_anchor = anchor("constraints", FROZEN_BRIEF["constraints"][4])
    assert search_anchor in anchors_by_step["video_33"]
    assert search_anchor in anchors_by_step["video_39"]
    assert rights_anchor in anchors_by_step["video_23"]
    assert rights_anchor in anchors_by_step["video_24"]
