from copy import deepcopy
from pathlib import Path

import pytest

from scripts.assessment_evaluation import evaluate_results, evaluation_plan, run_evaluation
from scripts.requirements_migration import digest, read_json, write_json
from scripts.walkthrough_fixtures import FixtureError, build_architecture, make_request, prepare_bundle


@pytest.fixture
def guide():
    return {"problem_id": "p1", "version": "2.0-candidate", "requirementRevision": "requirements-v2-preserved",
            "totalSteps": 6, "steps": [
                {"id": "lesson", "stepNumber": 1, "type": "explanation", "content": "Encryption is important"},
                {"id": "add1", "stepNumber": 2, "type": "add_component", "component": {
                    "nodeId": "gateway", "componentType": "api-gateway", "label": "Gateway",
                    "position": {"x": 10, "y": 20}, "properties": {"purpose": "Validates writes", "width": 300}}},
                {"id": "add2", "stepNumber": 3, "type": "add_component", "component": {
                    "nodeId": "store", "componentType": "object-storage", "label": "Object storage",
                    "properties": {"provider": "S3", "versioning": True}}},
                {"id": "edge", "stepNumber": 4, "type": "add_connection", "connection": {
                    "edgeId": "writes", "sourceNodeId": "gateway", "targetNodeId": "store",
                    "connectionType": "database-connection", "label": "durable writes", "description": "Commit then acknowledge"}},
                {"id": "update", "stepNumber": 5, "type": "update_component", "componentUpdate": {
                    "nodeId": "store", "properties": {"encryption": True}}},
                {"id": "decision", "stepNumber": 6, "type": "decision_point", "decision": {
                    "question": "When to acknowledge?", "chosen": "After durable commit", "chosenReason": "Avoid data loss"},
                 "componentUpdate": {"nodeId": "gateway", "properties": {"ackBoundary": "durable commit"}}},
            ]}


@pytest.fixture
def bundle(tmp_path, guide):
    problem = {"id": "p1", "title": "Store documents", "description": "Public exercise",
               "requirements": ["Persist documents"], "constraints": ["Low latency"]}
    write_json(tmp_path / "problems.json", [problem])
    write_json(tmp_path / "p1.json", guide)
    spec = {"schemaVersion": 1, "revision": "requirements-v2-preserved",
            "functional": [{"id": "F1", "text": "Persist documents", "scope": "core"}],
            "nonFunctional": [], "assumptions": []}
    return prepare_bundle(tmp_path, manifest={"changes": [{"id": "p1", "proposedSpec": spec}]})


def recorded(bundle, *, camel=False):
    experiment = {"model": "fake-model", "modelConfigHash": "frozen-config", "promptVersion": "v2", "rubricVersion": "v2"}
    planned = evaluation_plan(bundle)
    output = {"bundleHash": planned["bundleHash"], "experiment": experiment, "runs": []}
    cases = {case["id"]: case for case in bundle["cases"]}
    for row in planned["runs"]:
        negative = cases[row["caseId"]]["kind"] == "negative"
        node_id = row["request"]["components"][-1]["id"]
        finding = {"title": "Gateway missing", "explanation": "Required write validation is absent", "severity": "important"}
        finding["evidenceIds" if camel else "evidence_ids"] = [node_id]
        finding["requirementIds" if camel else "requirement_ids"] = ["F1"]
        coverage = {"requirementId" if camel else "requirement_id": "F1", "status": "supported",
                    "explanation": "Versioned durable store", "evidenceIds" if camel else "evidence_ids": [node_id]}
        result = {"source": "ai", "scoreAvailable": True, "overall_score": 90 if negative else 97,
                  "findings": [finding] if negative else [],
                  "requirementCoverage" if camel else "requirement_coverage": [coverage]}
        output["runs"].append({"caseId": row["caseId"], "repeat": row["repeat"], "inputHash": row["inputHash"],
                               "provenance": {**row["provenance"], **experiment}, "result": result, "latencyMs": 10})
    return output


def test_replay_keeps_protocol_updates_semantics_and_only_explicit_decisions(guide):
    built = build_architecture(guide)
    nodes = {node["id"]: node for node in built["architecture"]["components"]}
    assert nodes["store"]["type"] == "storage"
    assert nodes["store"]["properties"]["originalComponentId"] == "object-storage"
    assert nodes["store"]["properties"]["encryption"] is True
    assert "width" not in nodes["gateway"]["properties"]
    assert built["architecture"]["connections"][0]["type"] == "database-connection"
    assert built["acceptedDecisions"][0]["chosen"] == "After durable commit"
    assert built["explanationOnlyStepIds"] == ["lesson"]
    assert "Encryption is important" not in str(built["architecture"])
    partial = build_architecture(guide, applied_step_ids=["lesson", "add1", "add2", "edge"])
    assert not partial["acceptedDecisions"]
    assert "encryption" not in partial["architecture"]["components"][1]["properties"]


def test_reading_choice_without_apply_payload_is_not_evidence(guide):
    del guide["steps"][-1]["componentUpdate"]
    built = build_architecture(guide)
    assert not built["acceptedDecisions"]


@pytest.mark.parametrize("defect", ["edge", "protocol", "update", "duplicate_step", "duplicate_node"])
def test_broken_payloads_are_rejected_before_model_calls(guide, defect):
    if defect == "edge":
        guide["steps"][3]["connection"]["targetNodeId"] = "missing"
    elif defect == "protocol":
        del guide["steps"][3]["connection"]["connectionType"]
    elif defect == "update":
        guide["steps"][4]["componentUpdate"]["nodeId"] = "missing"
    elif defect == "duplicate_step":
        guide["steps"][2]["id"] = guide["steps"][1]["id"]
    else:
        guide["steps"][2]["component"]["nodeId"] = "gateway"
    with pytest.raises(FixtureError):
        build_architecture(guide)


def test_unsupported_new_apply_action_is_not_silently_ignored(guide):
    guide["steps"][0]["type"] = "invented_action"
    with pytest.raises(FixtureError, match="unsupported action"):
        build_architecture(guide)


def test_missing_or_changed_active_requirement_revision_rejected(guide):
    spec = {"schemaVersion": 1, "revision": "stale", "functional": [], "nonFunctional": [], "assumptions": []}
    problem = {"id": "p1", "title": "Public", "description": "Brief"}
    architecture = build_architecture(guide)
    with pytest.raises(FixtureError, match="revision"):
        make_request(problem, guide, architecture, spec)


def test_bundle_has_negative_and_equivalent_alternative_drafts_separate_from_requests(bundle):
    assert {case["kind"] for case in bundle["cases"]} == {"complete", "negative", "alternative"}
    assert all(case["expected"]["origin"] == "generated-not-human-truth" for case in bundle["cases"])
    complete, negative, alternative = bundle["cases"]
    assert len(negative["request"]["components"]) < len(complete["request"]["components"])
    assert complete["request"]["components"][0]["id"] != alternative["request"]["components"][0]["id"]
    planned = evaluation_plan(bundle)
    assert len(planned["runs"]) == 15
    assert all("expected" not in row["request"] and "minScore" not in row["request"] for row in planned["runs"])


@pytest.mark.parametrize("camel", [False, True])
def test_snake_and_frontend_coverage_and_evidence_fields_pass(bundle, camel):
    report = evaluate_results(bundle, recorded(bundle, camel=camel))
    assert report["acceptancePassed"] is True
    assert report["releaseEligible"] is False
    assert "Generated expectations are drafts, not human truth" in report["publicationBlockers"]
    assert len(report["runs"]) == 15


def test_api_snake_score_available_is_supported(bundle):
    output = recorded(bundle)
    for row in output["runs"]:
        row["result"]["score_available"] = row["result"].pop("scoreAvailable")
    assert evaluate_results(bundle, output)["acceptancePassed"]


@pytest.mark.parametrize("source,available", [("rule_based", True), ("ai", False), ("ai", None)])
def test_fallback_or_missing_available_score_never_passes(bundle, source, available):
    output = recorded(bundle)
    output["runs"][0]["result"].update(source=source, scoreAvailable=available, overall_score=100)
    report = evaluate_results(bundle, output)
    assert not report["acceptancePassed"]
    assert report["runs"][0]["score"] is None
    assert report["fallbackCount"] == 1


@pytest.mark.parametrize("defect", ["low_score", "critical", "unknown_evidence", "unknown_requirement", "missing_core",
                                  "unsupported", "invalid_score", "frozen_model", "frozen_revision"])
def test_acceptance_failures_are_captured_without_overrides(bundle, defect):
    output = recorded(bundle)
    row = output["runs"][0]
    if defect == "low_score":
        row["result"]["overall_score"] = 95
    elif defect == "critical":
        row["result"]["findings"] = [{"severity": "critical", "title": "Loss", "explanation": "Missing core"}]
    elif defect == "unknown_evidence":
        row["result"]["requirement_coverage"][0]["evidence_ids"] = ["does-not-exist"]
    elif defect == "unknown_requirement":
        row["result"]["findings"] = [{"title": "Unknown", "requirement_ids": ["bad"]}]
    elif defect == "missing_core":
        row["result"]["requirement_coverage"][0]["status"] = "missing"
    elif defect == "unsupported":
        row["result"]["findings"] = [{"unsupported": True}]
    elif defect == "invalid_score":
        row["result"]["overall_score"] = True
    elif defect == "frozen_model":
        row["provenance"]["model"] = "new-model"
    else:
        row["provenance"]["requirementRevision"] = "changed"
    report = evaluate_results(bundle, output)
    assert not report["acceptancePassed"]
    assert report["runs"][0]["failures"]


def test_constant_high_scores_fail_negative_gate(bundle):
    output = recorded(bundle)
    for row in output["runs"]:
        row["result"]["overall_score"] = 98
    report = evaluate_results(bundle, output)
    assert not report["acceptancePassed"]
    assert any("below" in failure.get("message", "") for failure in report["failures"])


def test_negative_must_detect_the_intended_defect(bundle):
    output = recorded(bundle)
    for row in output["runs"]:
        if row["caseId"].endswith(":negative"):
            row["result"]["findings"] = []
    assert not evaluate_results(bundle, output)["acceptancePassed"]


def test_duplicate_missing_extra_runs_and_failed_run_cannot_be_cherry_picked(bundle):
    output = recorded(bundle)
    output["runs"][0]["error"] = "malformed model output"
    output["runs"].append(deepcopy(output["runs"][0]))
    output["runs"].append({"caseId": "p1:complete", "repeat": 6})
    output["runs"].pop(4)
    report = evaluate_results(bundle, output)
    assert not report["acceptancePassed"]
    kinds = {failure["kind"] for failure in report["failures"]}
    assert {"duplicate_run", "missing_run", "unexpected_run", "run_failure"} <= kinds


def test_local_runner_calls_each_planned_input_once_and_keeps_error(bundle):
    calls = []
    async def reviewer(request):
        assert "expected" not in request
        assert "minScore" not in request
        calls.append(request)
        if len(calls) == 1:
            raise RuntimeError("record this failure")
        return {"source": "ai", "scoreAvailable": True, "overall_score": 97, "findings": []}
    experiment = recorded(bundle)["experiment"]
    # This fake reviewer has no I/O, so drive the coroutine without creating
    # Windows named pipes or selector sockets in a pure local test.
    evaluation = run_evaluation(bundle, reviewer, experiment)
    with pytest.raises(StopIteration) as completed:
        evaluation.send(None)
    output = completed.value.value
    assert len(calls) == len(output["runs"]) == 15
    assert output["runs"][0]["error"] == "RuntimeError: record this failure"
    assert not evaluate_results(bundle, output)["acceptancePassed"]


def test_mutated_bundle_or_recorded_results_hash_rejected(bundle):
    output = recorded(bundle)
    output["bundleHash"] = "stale"
    with pytest.raises(FixtureError, match="bundle hash"):
        evaluate_results(bundle, output)
    bundle["cases"][0]["request"]["components"][0]["label"] = "Changed"
    with pytest.raises(FixtureError, match="input hash"):
        evaluation_plan(bundle)


def test_all_current_public_candidates_have_valid_replay_graphs():
    candidate_dir = Path(__file__).resolve().parents[1] / "data/assessment-reference-candidates/walkthroughs"
    paths = sorted(candidate_dir.glob("*.json"))
    if not paths:
        pytest.skip("Main-owned public candidate fixtures have not been generated")
    assert len(paths) == 5
    for path in paths:
        guide = read_json(path)
        built = build_architecture(guide)
        assert built["architecture"]["components"]
        if guide["problem_id"] == "6901ef1b9420d83630aca871":
            nodes = {node["id"]: node for node in built["architecture"]["components"]}
            assert nodes["guided_file_storage"]["properties"]["originalComponentId"] == "object-storage"
            assert "disasterRecovery" in nodes["guided_database"]["properties"]
            assert "tracing" in nodes["guided_monitoring"]["properties"]
