"""Problem-specific structure and coverage checks for the Azure CI/CD guide."""

import json
from pathlib import Path

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_azure_007"
GUIDE_PATH = ROOT / "data/guided-walkthroughs/cloud_azure_007.json"
PROBLEMS_PATH = ROOT / "tests/fixtures/walkthroughs/problems.json"


def _load_guide() -> dict:
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    validated = GuidedWalkthrough.model_validate(raw)
    return validated.model_dump(exclude_none=True)


def test_azure_cicd_walkthrough_is_sequenced_connected_and_problem_specific():
    guide = _load_guide()
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    built = build_architecture(guide)

    assert guide["problem_id"] == PROBLEM_ID
    assert guide["totalSteps"] == len(guide["steps"]) == 44
    assert [step["stepNumber"] for step in guide["steps"]] == list(range(1, 45))
    assert len({step["id"] for step in guide["steps"]}) == 44
    phase_numbers = [number for phase in guide["phases"] for number in range(phase["stepRange"][0], phase["stepRange"][1] + 1)]
    assert phase_numbers == list(range(1, 45))

    all_requirement_ids = {f"legacy-requirement:{i}" for i in range(1, 9)}
    all_constraint_ids = {f"legacy-constraint:{i}" for i in range(1, 6)}
    assigned_ids = {requirement_id for step in guide["steps"] for requirement_id in step["requirementIds"]}
    assert all_requirement_ids | all_constraint_ids <= assigned_ids
    assert len(problem["requirements"]) == 8
    assert len(problem["constraints"]) == 5

    architecture = built["architecture"]
    nodes = {node["id"]: node for node in architecture["components"]}
    assert {
        "cicd_source", "cicd_pipeline", "cicd_build", "cicd_tests", "cicd_quality",
        "cicd_security", "cicd_registry", "cicd_iac", "cicd_deployment",
        "cicd_aks_dev", "cicd_aks_staging", "cicd_aks_prod", "cicd_ingress", "cicd_monitor",
    } == nodes.keys()
    assert nodes["cicd_tests"]["properties"]["coverageThreshold"] == 81
    assert nodes["cicd_pipeline"]["properties"]["platform"] == "Azure DevOps"
    assert nodes["cicd_registry"]["properties"]["registry"] == "ACR"
    assert nodes["cicd_deployment"]["properties"]["strategy"] == "Blue-Green"
    assert nodes["cicd_deployment"]["properties"]["rollbackEnabled"] is True
    assert nodes["cicd_aks_prod"]["properties"]["distribution"] == "AKS"
    assert nodes["cicd_monitor"]["properties"]["stack"] == "Azure Monitor"

    edges = architecture["connections"]
    assert len(edges) == 21
    adjacency = {node_id: set() for node_id in nodes}
    for edge in edges:
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


def test_azure_cicd_guide_calls_out_approval_timing_history_and_rollback():
    guide = _load_guide()
    text = " ".join(step["content"].lower() for step in guide["steps"])

    assert "approval wait" in text
    assert "under ten minutes" in text
    assert "staging" in text and "production" in text
    assert "deployment history" in text
    assert "approver" in text and "image digest" in text
    assert "back to blue" in text
    assert "azure monitor" in text
    assert "strictly greater than 80%" in text


def test_azure_cicd_anchors_match_the_action_and_evidence_in_each_step():
    guide = _load_guide()
    by_id = {step["id"]: step for step in guide["steps"]}

    expected_anchors = {
        "cicd_05": {"legacy-requirement:1", "legacy-constraint:5"},
        "cicd_10": {"legacy-requirement:1", "legacy-requirement:4", "legacy-constraint:3"},
        "cicd_13": {"legacy-requirement:1"},
        "cicd_14": {"legacy-requirement:1"},
        "cicd_16": {"legacy-requirement:1"},
        "cicd_22": {"legacy-requirement:1", "legacy-requirement:2"},
        "cicd_30": {"legacy-requirement:2", "legacy-requirement:4"},
        "cicd_31": {"legacy-requirement:2", "legacy-constraint:4"},
        "cicd_36": {"legacy-requirement:3", "legacy-constraint:2"},
        "cicd_37": {"legacy-requirement:6", "legacy-constraint:2"},
        "cicd_39": {"legacy-requirement:6"},
    }
    for step_id, expected in expected_anchors.items():
        assert set(by_id[step_id]["requirementIds"]) == expected


def test_azure_cicd_preserves_stated_targets_without_claiming_compliance():
    guide = _load_guide()
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    by_id = {step["id"]: step for step in guide["steps"]}
    brief_constraints = " ".join(problem["constraints"])

    assert "Deployment time under 10 minutes" in brief_constraints
    assert "Automated testing coverage > 80%" in brief_constraints
    assert "deployment-time target under ten minutes" in by_id["cicd_02"]["content"]
    assert "do not claim end-to-end compliance" in by_id["cicd_02"]["content"]
    assert "approval waits" in by_id["cicd_20"]["content"]
    assert "strictly greater than 80%" in by_id["cicd_09"]["content"]
    assert "zero downtime still depends" in by_id["cicd_34"]["content"]
    assert "atomically switch" not in by_id["cicd_34"]["decision"]["chosen"].lower()
    assert "immediate reversal" not in by_id["cicd_34"]["decision"]["chosen"].lower()
    assert "immediately" not in by_id["cicd_43"]["content"].lower()
    assert "measure the recovery duration" in by_id["cicd_43"]["content"].lower()
    assert "immutable run/deployment metadata" not in by_id["cicd_42"]["decision"]["chosen"].lower()
