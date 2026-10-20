import json
import sys

import pytest

from scripts import run_walkthrough_ai_gate as gate


PROBLEM_ID = "typed-problem"
FUNCTIONAL_CORE_ID = "documents.create"
QUALITY_CORE_ID = "documents.collaboration-latency"
EXTENSION_ID = "documents.optional-export"
LEGACY_REQUIREMENT_ID = "legacy-requirement:1"
LEGACY_CONSTRAINT_ID = "legacy-constraint:1"


def problem_with_spec():
    return {
        "id": PROBLEM_ID,
        "requirements": ["Legacy functional text"],
        "constraints": ["Legacy constraint text"],
        "requirementSpec": {
            "schemaVersion": 1,
            "revision": "test-r1",
            "functional": [
                {"id": FUNCTIONAL_CORE_ID, "text": "Create documents", "scope": "core"},
                {"id": EXTENSION_ID, "text": "Optional export", "scope": "extension"},
            ],
            "nonFunctional": [
                {"id": QUALITY_CORE_ID, "text": "Low collaboration latency", "scope": "core"}
            ],
        },
    }


def run_gate(tmp_path, monkeypatch, problem, coverage):
    fixture_path = tmp_path / "tests/fixtures/walkthroughs/problems.json"
    fixture_path.parent.mkdir(parents=True)
    fixture_path.write_text(json.dumps([problem]), encoding="utf-8")

    guide_path = tmp_path / "data/guided-walkthroughs" / f"{PROBLEM_ID}.json"
    guide_path.parent.mkdir(parents=True)
    guide_path.write_text(json.dumps({"problem_id": PROBLEM_ID}), encoding="utf-8")

    output_path = tmp_path / "gate-result.json"
    response = {
        "source": "ai",
        "score_available": True,
        "is_valid": True,
        "overall_score": 98,
        "verdict": "strong_alignment",
        "requirement_coverage": coverage,
    }
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "prepare_request", lambda _problem, _guide: {})
    monkeypatch.setattr(gate, "submit", lambda *_args: (200, response))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_walkthrough_ai_gate",
            "--ids",
            PROBLEM_ID,
            "--rounds",
            "1",
            "--parallelism",
            "1",
            "--output",
            str(output_path),
        ],
    )

    exit_code = gate.main()
    candidate = json.loads(output_path.read_text(encoding="utf-8"))["candidates"][PROBLEM_ID]
    return exit_code, candidate


def test_gate_rejects_missing_core_requirement_spec_anchors(tmp_path, monkeypatch):
    legacy_coverage = [
        {"requirement_id": LEGACY_REQUIREMENT_ID, "status": "supported"},
        {"requirement_id": LEGACY_CONSTRAINT_ID, "status": "supported"},
    ]

    exit_code, candidate = run_gate(tmp_path, monkeypatch, problem_with_spec(), legacy_coverage)

    assert exit_code == 2
    assert candidate["passed"] is False
    assert candidate["requiredAnchors"] == sorted([FUNCTIONAL_CORE_ID, QUALITY_CORE_ID])
    assert candidate["results"][0]["unsupportedAnchors"] == sorted(
        [FUNCTIONAL_CORE_ID, QUALITY_CORE_ID]
    )


def test_gate_accepts_supported_core_and_does_not_require_extension_anchors(tmp_path, monkeypatch):
    structured_coverage = [
        {"requirement_id": FUNCTIONAL_CORE_ID, "status": "supported"},
        {"requirement_id": QUALITY_CORE_ID, "status": "supported"},
        {"requirement_id": EXTENSION_ID, "status": "missing"},
    ]

    exit_code, candidate = run_gate(tmp_path, monkeypatch, problem_with_spec(), structured_coverage)

    assert exit_code == 0
    assert candidate["passed"] is True
    assert candidate["requiredAnchors"] == sorted([FUNCTIONAL_CORE_ID, QUALITY_CORE_ID])
    assert candidate["results"][0]["unsupportedAnchors"] == []


def test_gate_keeps_legacy_anchor_checks_when_no_requirement_spec_exists(tmp_path, monkeypatch):
    legacy_problem = {
        "id": PROBLEM_ID,
        "requirements": ["Create documents"],
        "constraints": ["Low collaboration latency"],
    }
    legacy_coverage = [
        {"requirement_id": LEGACY_REQUIREMENT_ID, "status": "supported"},
        {"requirement_id": LEGACY_CONSTRAINT_ID, "status": "supported"},
    ]

    exit_code, candidate = run_gate(tmp_path, monkeypatch, legacy_problem, legacy_coverage)

    assert exit_code == 0
    assert candidate["passed"] is True
    assert candidate["requiredAnchors"] == sorted(
        [LEGACY_REQUIREMENT_ID, LEGACY_CONSTRAINT_ID]
    )


def test_typed_spec_without_core_anchors_fails_closed():
    extension_only_problem = {
        "requirementSpec": {
            "functional": [
                {"id": EXTENSION_ID, "text": "Optional export", "scope": "extension"}
            ],
            "nonFunctional": [],
        }
    }

    with pytest.raises(ValueError, match="at least one core requirement anchor"):
        gate.required_anchor_ids(extension_only_problem)
