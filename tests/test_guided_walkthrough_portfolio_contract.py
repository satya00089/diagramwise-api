"""Portfolio-level identity and action-anchor contract for missing guides."""

import json
from pathlib import Path

from app.models.walkthrough_models import GuidedWalkthrough


ROOT = Path(__file__).resolve().parents[1]
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
GUIDES_PATH = ROOT / "data" / "guided-walkthroughs"
GRAPH_ACTION_TYPES = {"add_component", "add_connection", "update_component"}
STEP_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "decision_point",
    "scale_trigger",
    "update_component",
    "conclusion",
}


def test_every_unflagged_problem_has_a_versioned_guide_with_full_action_anchor_coverage():
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    candidates = [problem for problem in problems if problem.get("has_guided_walkthrough") is not True]
    assert candidates, "The frozen inventory unexpectedly contains no missing walkthroughs"
    assert len({problem["id"] for problem in candidates}) == len(candidates)

    for problem in candidates:
        path = GUIDES_PATH / f"{problem['id']}.json"
        assert path.is_file(), f"{problem['id']}: no local review candidate"
        raw = json.loads(path.read_text(encoding="utf-8"))
        guide = GuidedWalkthrough.model_validate(raw)
        assert guide.problem_id == problem["id"]
        assert guide.version
        assert guide.totalSteps == len(guide.steps)
        assert len({step.id for step in guide.steps}) == guide.totalSteps
        assert [step.stepNumber for step in guide.steps] == list(
            range(1, guide.totalSteps + 1)
        )
        for step in guide.steps:
            assert step.type in STEP_TYPES, f"{problem['id']}/{step.id}: unknown step type"
            assert step.content.strip(), f"{problem['id']}/{step.id}: blank step guidance"

        expected_next_step = 1
        for phase in guide.phases:
            start, end = phase.stepRange
            assert start == expected_next_step, f"{problem['id']}: phase ranges have a gap"
            assert start <= end <= guide.totalSteps
            assert all(
                guide.steps[index - 1].phase == phase.name
                for index in range(start, end + 1)
            )
            expected_next_step = end + 1
        assert expected_next_step == guide.totalSteps + 1

        expected = {
            *(f"legacy-requirement:{index}" for index in range(1, len(problem.get("requirements", [])) + 1)),
            *(f"legacy-constraint:{index}" for index in range(1, len(problem.get("constraints", [])) + 1)),
        }
        all_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
        action_anchors = {
            anchor
            for step in guide.steps
            if step.type in GRAPH_ACTION_TYPES or step.componentUpdate is not None
            for anchor in step.requirementIds
        }
        assert all_anchors == expected, f"{problem['id']}: brief anchor set differs"
        assert action_anchors == expected, f"{problem['id']}: anchors are missing from graph actions"
