"""Attempt trust rules exercised with in-memory tables, never AWS clients."""

from copy import deepcopy
from decimal import Decimal
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError

from app.models.attempt_models import AssessmentHistoryEntry, AttemptCreate

# The module creates a service singleton at import time. Prevent even client
# construction here; each test below uses a service with fake tables instead.
with patch("boto3.resource"):
    from app.services.dynamodb_service import DynamoDBService


NOW = "2026-10-10T00:00:00+00:00"


def stored_attempt(**overrides):
    item = {
        "userId": "learner", "problemId": "problem", "title": "Example",
        "createdAt": NOW, "updatedAt": NOW, "lastAttemptedAt": NOW,
        "nodes": [], "edges": [], "assessmentCount": 0,
    }
    item.update(overrides)
    return item


def ai_review(**overrides):
    review = {
        "score": 88, "source": "ai", "assessmentId": "review-1",
        "findings": [{"title": "Clarify failover", "severity": "important"}],
        "rubricVersion": "2.0", "requirementRevision": "r1",
        "modelVersion": "model-1", "inputFingerprint": "canvas-1",
    }
    review.update(overrides)
    return review


def requirement_spec(revision="r1", text="Redirect visitors"):
    return {
        "schemaVersion": 1, "revision": revision,
        "functional": [{"id": "redirect", "text": text, "scope": "core"}],
        "nonFunctional": [], "assumptions": [],
    }


class AttemptTable:
    def __init__(self, item=None):
        self.item = deepcopy(item)
        self.writes = []

    def get_item(self, **_):
        return {"Item": deepcopy(self.item)} if self.item else {}

    def query(self, **_):
        return {"Items": [deepcopy(self.item)]} if self.item else {"Items": []}

    def update_item(self, **kwargs):
        self.writes.append(deepcopy(kwargs))
        if self.item is None:
            self.item = deepcopy(kwargs["Key"])
        names = kwargs.get("ExpressionAttributeNames", {})
        values = kwargs["ExpressionAttributeValues"]
        for alias, attribute in names.items():
            value_alias = alias.replace("#", ":", 1)
            if not alias.startswith("#a") or value_alias not in values:
                continue
            assignment = f"{alias} = if_not_exists({alias}, {value_alias})"
            if assignment in kwargs["UpdateExpression"] and attribute in self.item:
                continue
            self.item[attribute] = deepcopy(values[value_alias])
        if kwargs["UpdateExpression"].startswith("SET isPublic"):
            self.item.update(
                isPublic=values[":pub"], publishedAt=values[":ts"],
                authorName=values[":name"], authorPicture=values[":pic"],
            )
            self.item.setdefault("viewCount", 0)
        if kwargs["UpdateExpression"] == "ADD viewCount :inc":
            self.item["viewCount"] = self.item.get("viewCount", 0) + values[":inc"]
        return {"Attributes": deepcopy(self.item)}


class ProblemTable:
    def __init__(self, spec=None):
        self.spec = deepcopy(spec)
        self.reads = []

    def get_item(self, **kwargs):
        self.reads.append(kwargs)
        return {"Item": {"id": "problem", "requirementSpec": self.spec}} if self.spec else {}


def service_with(item=None, spec=None):
    service = DynamoDBService.__new__(DynamoDBService)
    service.attempts_table = AttemptTable(item)
    service.problems_table = ProblemTable(spec)
    return service


def save(service, **overrides):
    args = {
        "user_id": "learner", "problem_id": "problem", "title": "Example",
        "difficulty": None, "category": None, "nodes": [], "edges": [],
    }
    args.update(overrides)
    user_id = args.pop("user_id")
    field_names = {
        "problem_id": "problemId",
        "elapsed_time": "elapsedTime",
        "last_assessment": "lastAssessment",
        "last_assessment_check": "lastAssessmentCheck",
        "problem_requirement_spec": "problemRequirementSpec",
        "reasoning_context": "reasoningContext",
        "interview_session": "interviewSession",
        "addressed_finding_ids": "addressedFindingIds",
    }
    request = AttemptCreate(**{
        field_names.get(name, name): value for name, value in args.items()
    })
    return service.create_or_update_attempt(user_id=user_id, request=request)


@pytest.mark.parametrize("fallback", [
    {"score": 70, "source": "rule_based", "scoreAvailable": True},
    {"score": 0, "source": "ai", "scoreAvailable": False},
    {"overall_score": 0, "source": "ai", "score_available": False},
    {"score": 40, "source": "ai", "scoreAvailable": True, "score_available": False},
    {"source": "ai", "summary": "Incomplete model output"},
    {"score": 0, "source": "ai", "verdict": "unavailable"},
])
def test_unavailable_check_preserves_previous_ai_review_without_counting_it(fallback):
    prior = ai_review()
    service = service_with(stored_attempt(lastAssessment=prior, assessmentCount=3))

    result = save(service, last_assessment=fallback, nodes=[{"id": "changed"}])

    assert result.lastAssessment == prior
    assert result.lastAssessmentCheck["scoreAvailable"] is False
    assert result.lastAssessmentCheck["score"] is None
    assert result.assessmentCount == 3
    assert result.assessmentHistory[-1].score is None
    assert result.assessmentHistory[-1].scoreAvailable is False
    reloaded = service.get_attempt_by_problem("learner", "problem")
    assert reloaded.lastAssessment == prior
    assert reloaded.lastAssessmentCheck == result.lastAssessmentCheck
    assert reloaded.nodes == [{"id": "changed"}]


@pytest.mark.parametrize("score", [None, -1, 101, 77.5, True, "88", float("nan"), float("inf"), Decimal("NaN")])
def test_incomplete_or_invalid_ai_score_never_becomes_zero_success(score):
    service = service_with()

    result = save(service, last_assessment=ai_review(score=score))

    assert result.lastAssessment is None
    assert result.assessmentCount == 0
    assert result.lastAssessmentCheck["score"] is None
    assert result.assessmentHistory[0].scoreAvailable is False


def test_invalid_backend_score_placeholder_is_not_persisted_as_nan():
    result = save(service_with(), last_assessment={
        "source": "ai", "overall_score": float("nan"), "score_available": True,
    })

    assert result.lastAssessmentCheck["overall_score"] is None
    assert result.lastAssessmentCheck["score_available"] is False


def test_success_after_outage_records_provenance_and_counts_only_the_ai_review():
    service = service_with()
    save(service, last_assessment={"source": "rule_based", "score": 70})

    result = save(service, last_assessment=ai_review(), addressed_finding_ids=["important:failover"])

    assert result.assessmentCount == 1
    assert result.lastAssessment["score"] == 88
    assert result.lastAssessmentCheck["scoreAvailable"] is True
    assert [entry.score for entry in result.assessmentHistory] == [None, 88]
    entry = result.assessmentHistory[-1]
    assert entry.scoreAvailable is True
    assert entry.rubricVersion == "2.0"
    assert entry.requirementRevision == "r1"
    assert entry.modelVersion == "model-1"
    assert entry.inputFingerprint == "canvas-1"
    assert entry.addressedFindingIds == ["important:failover"]


def test_backend_snake_case_review_metadata_is_retained_in_history():
    service = service_with()
    result = save(service, last_assessment={
        "overall_score": 91, "source": "ai", "score_available": True,
        "assessment_id": "api-review", "rubric_version": "2.1",
        "requirement_revision": "r2", "model_version": "model-2",
        "input_fingerprint": "canvas-2",
    })

    entry = result.assessmentHistory[0]
    assert entry.id == "api-review"
    assert entry.score == 91
    assert entry.rubricVersion == "2.1"
    assert entry.requirementRevision == "r2"
    assert entry.modelVersion == "model-2"
    assert entry.inputFingerprint == "canvas-2"


def test_real_zero_ai_score_is_distinct_from_an_unavailable_score():
    result = save(service_with(), last_assessment=ai_review(score=0))

    assert result.lastAssessment["score"] == 0
    assert result.assessmentCount == 1
    assert result.assessmentHistory[0].scoreAvailable is True


def test_old_history_remains_readable_and_new_history_is_bounded_to_ten():
    history = [{"id": f"old-{i}", "score": i, "createdAt": NOW} for i in range(10)]
    history[0]["source"] = "rule_based"
    service = service_with(stored_attempt(assessmentHistory=history, assessmentCount=10))

    old_result = service.get_user_attempts("learner")[0]
    assert old_result.assessmentHistory[0].score == 0
    assert old_result.assessmentHistory[0].scoreAvailable is False
    assert old_result.assessmentHistory[1].scoreAvailable is True
    result = save(service, last_assessment=ai_review())

    assert len(result.assessmentHistory) == 10
    assert result.assessmentHistory[0].id == "old-1"
    assert result.assessmentHistory[0].score == 1
    assert result.assessmentHistory[-1].id == "review-1"


def test_source_less_legacy_review_is_preserved_but_a_bare_score_is_unscored():
    meaningful = {"score": 82, "feedback": [{"message": "Explain replication"}]}
    trusted = save(service_with(), last_assessment=meaningful)
    ambiguous = save(service_with(), last_assessment={"score": 82})

    assert trusted.assessmentCount == 1
    assert trusted.lastAssessment["score"] == 82
    assert ambiguous.assessmentCount == 0
    assert ambiguous.lastAssessment is None


def test_canvas_save_preserves_review_sharing_unknown_attributes_and_context():
    original = stored_attempt(
        lastAssessment=ai_review(), assessmentCount=1,
        reasoningContext={"requirements": "Original scope"},
        addressedFindingIds=["important:old"],
        isPublic=True, publishedAt=NOW, authorName="Owner", viewCount=12,
        futureWorkflowState={"keep": "this"},
    )
    service = service_with(original)

    result = save(service, nodes=[{"id": "api", "position": {"x": 1.5, "y": 0}}])

    assert result.lastAssessment == ai_review()
    assert result.assessmentCount == 1
    assert result.reasoningContext.requirements == "Original scope"
    assert result.addressedFindingIds == ["important:old"]
    assert result.isPublic is True
    assert result.viewCount == 12
    assert service.attempts_table.item["futureWorkflowState"] == {"keep": "this"}
    assert service.attempts_table.item["nodes"][0]["position"]["x"] == Decimal("1.5")


def test_resaving_retained_review_and_latest_check_does_not_duplicate_history():
    service = service_with()
    review = ai_review()
    fallback = {"source": "rule_based", "scoreAvailable": False, "assessmentId": "check-1"}
    save(service, last_assessment=review)
    save(service, last_assessment=review, last_assessment_check=fallback)
    result = save(service, last_assessment=review, last_assessment_check=fallback)

    assert result.assessmentCount == 1
    assert len(result.assessmentHistory) == 2
    assert result.lastAssessmentCheck["assessmentId"] == "check-1"


def test_autosaving_retained_review_does_not_erase_latest_outage_state():
    service = service_with()
    review = ai_review()
    save(service, last_assessment=review)
    save(service, last_assessment={"source": "rule_based", "score": 70})

    result = save(service, last_assessment=review)

    assert result.lastAssessmentCheck["source"] == "rule_based"
    assert result.lastAssessmentCheck["scoreAvailable"] is False
    assert result.assessmentCount == 1
    assert len(result.assessmentHistory) == 2


def test_new_attempt_pins_server_approved_spec_and_existing_snapshot_never_upgrades():
    service = service_with(spec=requirement_spec())
    first = save(service)
    assert first.problemRequirementSpec.revision == "r1"

    service.problems_table.spec = requirement_spec("r2", "New requirement")
    updated = save(service, problem_requirement_spec=requirement_spec("r2"))

    assert updated.problemRequirementSpec == first.problemRequirementSpec
    assert service.attempts_table.item["problemRequirementSpec"]["revision"] == "r1"


def test_old_attempt_has_no_implicit_requirement_revision_upgrade():
    service = service_with(stored_attempt(lastAssessment=ai_review(requirementRevision=None)), requirement_spec("r2"))

    result = save(service)

    assert result.problemRequirementSpec is None
    assert service.problems_table.reads == []
    assert "problemRequirementSpec" not in service.attempts_table.item


def test_explicit_valid_revision_pins_approved_content_not_client_edited_content():
    service = service_with(stored_attempt(), requirement_spec())
    result = save(service, last_assessment=ai_review(),
                  problem_requirement_spec=requirement_spec(text="Tampered client requirement"))

    assert result.problemRequirementSpec.functional[0].text == "Redirect visitors"


def test_current_frontend_autosave_does_not_upgrade_legacy_attempt_context():
    prior = ai_review(requirementRevision=None)
    service = service_with(stored_attempt(lastAssessment=prior), requirement_spec("r2"))

    result = save(service, problem_requirement_spec=requirement_spec("r2"))

    assert result.problemRequirementSpec is None
    assert result.lastAssessment == prior
    assert service.problems_table.reads == []


def test_unknown_supplied_revision_is_rejected_before_writing():
    service = service_with(spec=requirement_spec("r2"))
    stale_spec = requirement_spec("r1")
    with pytest.raises(ValueError, match="revision is not available"):
        save(service, problem_requirement_spec=stale_spec)
    assert service.attempts_table.writes == []


def test_older_assessment_revision_is_not_attached_to_current_problem_brief():
    result = save(service_with(spec=requirement_spec("r2")), last_assessment=ai_review())

    assert result.problemRequirementSpec is None
    assert result.lastAssessment["requirementRevision"] == "r1"


def test_custom_problem_save_still_works_without_catalog_spec():
    result = save(service_with(), problem_requirement_spec=requirement_spec())
    assert result.problemRequirementSpec is None


@pytest.mark.parametrize("assessment", [
    None, {"source": "rule_based", "score": 99},
    {"source": "ai", "score": 99, "score_available": False},
    {"source": "ai"}, {"score": 99},
])
def test_unscored_results_cannot_qualify_for_ai_reviewed_publication(assessment):
    service = service_with(stored_attempt(lastAssessment=assessment))

    with pytest.raises(ValueError, match="scored AI assessment is required"):
        service.publish_attempt("learner", "problem", "Learner")

    assert service.attempts_table.writes == []


@pytest.mark.parametrize("assessment", [ai_review(), {"score": 81, "summary": "Review of the design"}])
def test_valid_ai_and_meaningful_legacy_reviews_can_be_published(assessment):
    service = service_with(stored_attempt(lastAssessment=assessment))
    result = service.publish_attempt("learner", "problem", "Learner")

    assert result["publishedAt"]
    assert service.attempts_table.item["isPublic"] is True


def test_publication_cannot_succeed_if_review_changes_between_read_and_write():
    service = service_with(stored_attempt(lastAssessment=ai_review()))
    writes = []

    def changed_review(**kwargs):
        writes.append(kwargs)
        assert kwargs["ExpressionAttributeNames"]["#assessment"] == "lastAssessment"
        assert kwargs["ExpressionAttributeValues"][":assessment"]["assessmentId"] == "review-1"
        assert "#assessment = :assessment" in kwargs["ConditionExpression"]
        assert "attribute_not_exists(#check)" in kwargs["ConditionExpression"]
        raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem")

    service.attempts_table.update_item = changed_review
    assert service.publish_attempt("learner", "problem", "Learner") is None
    assert len(writes) == 1


def test_retained_review_with_latest_outage_does_not_qualify_new_submission():
    service = service_with(stored_attempt(
        lastAssessment=ai_review(), lastAssessmentCheck={"source": "rule_based", "score": 70},
    ))
    with pytest.raises(ValueError, match="scored AI assessment is required"):
        service.publish_attempt("learner", "problem", "Learner")


def test_leaderboard_filters_unscored_results_and_scans_all_pages_before_sorting():
    service = service_with()

    class Pages:
        def __init__(self):
            self.calls = []

        def scan(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return {"Items": [
                    stored_attempt(userId="fallback", lastAssessment={"source": "rule_based", "score": 100}),
                    stored_attempt(userId="missing", lastAssessment={"source": "ai"}),
                    stored_attempt(userId="first", lastAssessment=ai_review(score=80)),
                ], "LastEvaluatedKey": {"userId": "first", "problemId": "problem"}}
            return {"Items": [
                stored_attempt(userId="outage", lastAssessment=ai_review(score=100), lastAssessmentCheck={"source": "ai", "score_available": False}),
                stored_attempt(userId="legacy", lastAssessment={"score": Decimal("90"), "summary": "Meaningful review"}),
                stored_attempt(userId="zero", lastAssessment=ai_review(score=0)),
            ]}

    service.attempts_table = Pages()
    entries = service.get_problem_leaderboard("problem", limit=3)

    assert [(entry.attemptId, entry.score) for entry in entries] == [
        ("legacy#problem", 90), ("first#problem", 80), ("zero#problem", 0),
    ]
    assert len(service.attempts_table.calls) == 2
    assert service.attempts_table.calls[1]["ExclusiveStartKey"]["userId"] == "first"


def test_existing_public_fallback_is_readable_but_never_advertises_a_score():
    service = service_with(stored_attempt(isPublic=True, lastAssessment={"source": "rule_based", "score": 70}))

    result = service.get_public_solution("learner", "problem")

    assert result.lastAssessment["scoreAvailable"] is False
    assert result.lastAssessment["score"] is None


def test_models_accept_new_fields_and_legacy_history_aliases():
    request = AttemptCreate(
        problemId="problem", title="Example", problemRequirementSpec=requirement_spec(),
        lastAssessmentCheck={"source": "rule_based", "scoreAvailable": False},
    )
    entry = AssessmentHistoryEntry(
        id="old", score=0, createdAt=NOW, score_available=False,
        rubric_version="old-rubric", requirement_revision="r1",
    )

    assert request.problemRequirementSpec.revision == "r1"
    assert request.lastAssessmentCheck["scoreAvailable"] is False
    assert entry.scoreAvailable is False
    assert entry.rubricVersion == "old-rubric"
    assert entry.requirementRevision == "r1"
