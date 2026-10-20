"""Problem-specific structural and coverage checks for AI translation walkthrough."""

import json
from pathlib import Path

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "data/guided-walkthroughs/ai_012.json"
PROBLEMS_PATH = ROOT / "tests/fixtures/walkthroughs/problems.json"


def _load_guide() -> dict:
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return GuidedWalkthrough.model_validate(raw).model_dump(exclude_none=True)


def test_translation_walkthrough_is_sequenced_connected_and_covers_the_brief():
    guide = _load_guide()
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == "ai_012")
    built = build_architecture(guide)

    assert guide["problem_id"] == "ai_012"
    assert guide["totalSteps"] == len(guide["steps"]) == 45
    assert [step["stepNumber"] for step in guide["steps"]] == list(range(1, 46))
    phase_numbers = [
        number
        for phase in guide["phases"]
        for number in range(phase["stepRange"][0], phase["stepRange"][1] + 1)
    ]
    assert phase_numbers == list(range(1, 46))

    required_ids = {
        *(f"legacy-requirement:{index}" for index in range(1, 9)),
        *(f"legacy-constraint:{index}" for index in range(1, 6)),
    }
    assigned_ids = {
        requirement_id
        for step in guide["steps"]
        for requirement_id in step.get("requirementIds", [])
    }
    assert required_ids <= assigned_ids
    assert len(problem["requirements"]) == 8
    assert len(problem["constraints"]) == 5

    action_steps = [
        step
        for step in guide["steps"]
        if step["type"] in {"add_component", "add_connection", "update_component"}
        or step.get("componentUpdate")
    ]
    action_ids = {
        anchor
        for step in action_steps
        for anchor in step.get("requirementIds", [])
    }
    assert action_ids == required_ids
    concrete_actions = {
        "legacy-requirement:2": "tr_21",
        "legacy-requirement:7": "tr_02",
        "legacy-constraint:2": "tr_03",
        "legacy-constraint:3": "tr_09",
    }
    by_id = {step["id"]: step for step in action_steps}
    for anchor, step_id in concrete_actions.items():
        assert anchor in by_id[step_id]["requirementIds"]

    direct_action_anchors = {
        "tr_07": {"legacy-requirement:1", "legacy-requirement:2", "legacy-requirement:3"},
        "tr_10": {"legacy-requirement:1", "legacy-constraint:3"},
        "tr_16": {"legacy-requirement:1", "legacy-constraint:1"},
        "tr_18": {"legacy-requirement:4", "legacy-requirement:6", "legacy-requirement:8"},
        "tr_28": {"legacy-requirement:3", "legacy-constraint:5"},
        "tr_33": {"legacy-requirement:3", "legacy-constraint:4"},
        "tr_37": {"legacy-requirement:2", "legacy-requirement:5", "legacy-constraint:2"},
        "tr_38": {"legacy-requirement:5", "legacy-requirement:7"},
        "tr_43": {"legacy-requirement:1", "legacy-constraint:1", "legacy-constraint:3"},
        "tr_44": {"legacy-requirement:3", "legacy-constraint:5"},
    }
    for step_id, anchors in direct_action_anchors.items():
        assert anchors <= set(by_id[step_id]["requirementIds"])

    architecture = built["architecture"]
    nodes = {node["id"]: node for node in architecture["components"]}
    expected_nodes = {
        "tr_clients", "tr_gateway", "tr_auth", "tr_orchestrator",
        "tr_pair_registry", "tr_ai_gateway", "tr_nmt", "tr_cache",
        "tr_memory", "tr_speech_session", "tr_document_storage",
        "tr_document_queue", "tr_document_worker", "tr_quality_model",
        "tr_monitoring",
    }
    assert set(nodes) == expected_nodes

    adjacency = {node_id: set() for node_id in nodes}
    for edge in architecture["connections"]:
        adjacency[edge["source"]].add(edge["target"])
        adjacency[edge["target"]].add(edge["source"])
    reached = set()
    frontier = [next(iter(nodes))]
    while frontier:
        current = frontier.pop()
        if current in reached:
            continue
        reached.add(current)
        frontier.extend(adjacency[current] - reached)
    assert reached == nodes.keys()


def test_translation_walkthrough_distinguishes_quality_targets_and_editing_safeguards():
    guide = _load_guide()
    text = json.dumps(guide, ensure_ascii=False).lower()

    assert "end-to-end p95" in text
    assert "first useful translated audio" in text
    assert "corpus-level offline quality gate" in text
    assert "bleu above 40" in text
    assert "100mb" in text
    assert "formatting" in text or "format" in text
    assert "unreviewed" in text
    assert "tenant" in text
    assert "10k concurrent" in text


def test_translation_walkthrough_uses_reusable_catalog_components_only():
    guide = _load_guide()
    component_types = {
        step["component"]["componentType"]
        for step in guide["steps"]
        if step.get("type") == "add_component"
    }
    assert component_types <= {
        "web-app", "api-gateway", "auth-service", "ai-orchestrator",
        "database", "ai-gateway", "model-serving", "cache",
        "backend-server", "object-storage", "queue", "processing-worker",
        "ml-model", "monitoring",
    }
    for step in guide["steps"]:
        component = step.get("component")
        if component:
            assert {"componentName", "purpose"} <= set(component["properties"])

