import json
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "68d7013f6f42e23bb16a222e"


def test_news_feed_graph_actions_cover_every_frozen_requirement_and_constraint():
    guide_path = (
        API_ROOT
        / "data"
        / "guided-walkthroughs"
        / f"{PROBLEM_ID}.json"
    )
    fixture_path = (
        API_ROOT
        / "tests"
        / "fixtures"
        / "walkthroughs"
        / "problems.json"
    )

    guide = json.loads(guide_path.read_text(encoding="utf-8"))
    problems = json.loads(fixture_path.read_text(encoding="utf-8"))
    problem = next(item for item in problems if item["id"] == PROBLEM_ID)

    expected = {
        *(f"legacy-requirement:{index}" for index, _ in enumerate(problem["requirements"], 1)),
        *(f"legacy-constraint:{index}" for index, _ in enumerate(problem["constraints"], 1)),
    }
    graph_actions = [
        step
        for step in guide["steps"]
        if any(
            isinstance(step.get(action_key), dict)
            for action_key in (
                "component",
                "connection",
                "componentUpdate",
                "connectionUpdate",
            )
        )
    ]
    actual = {
        anchor
        for step in graph_actions
        for anchor in step.get("requirementIds", [])
    }

    missing = expected - actual
    unexpected = actual - expected
    assert not missing and not unexpected, (
        f"Graph-action anchor coverage differs from the frozen brief; "
        f"missing={sorted(missing)}, unexpected={sorted(unexpected)}"
    )
