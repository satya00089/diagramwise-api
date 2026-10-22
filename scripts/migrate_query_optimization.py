"""Provision query indexes and backfill materialized query records.

Run this once against the target AWS account before deploying the application
version that reads the diagram shares table or leaderboard index. The script is
idempotent and does not delete source diagram or attempt records.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import time
from decimal import Decimal
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.problem_models import problem_slug


REGION = os.getenv("AWS_REGION", "us-east-1")
DIAGRAMS_TABLE = os.getenv("DYNAMODB_DIAGRAMS_TABLE", "diagrammatic_diagrams")
SHARES_TABLE = os.getenv("DYNAMODB_DIAGRAM_SHARES_TABLE", "diagrammatic_diagram_shares")
PROBLEMS_TABLE = os.getenv("DYNAMODB_PROBLEMS_TABLE", "diagrammatic_problems")
ATTEMPTS_TABLE = os.getenv(
    "DYNAMODB_ATTEMPTS_TABLE", "diagrammatic_problem_attempts"
)
PROBLEM_SLUG_INDEX = "slug-index"
LEADERBOARD_INDEX = "leaderboard-index"


def _table_exists(client: Any, table_name: str) -> bool:
    try:
        client.describe_table(TableName=table_name)
        return True
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            return False
        raise


def _wait_for_index(client: Any, table_name: str, index_name: str) -> None:
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        table = client.describe_table(TableName=table_name)["Table"]
        indexes = table.get("GlobalSecondaryIndexes", [])
        index = next((item for item in indexes if item.get("IndexName") == index_name), None)
        if index and index.get("IndexStatus") == "ACTIVE":
            return
        if table.get("TableStatus") not in ("ACTIVE", "UPDATING"):
            raise RuntimeError(f"Table {table_name} is {table.get('TableStatus')}")
        time.sleep(5)
    raise TimeoutError(f"Timed out waiting for {table_name}/{index_name}")


def _validate_existing_index(
    client: Any,
    table: Dict[str, Any],
    table_name: str,
    index_name: str,
    existing: Dict[str, Any],
    expected_key_schema: list[tuple[str, str]],
    expected_attribute_types: Dict[str, str],
) -> None:
    actual_key_schema = [
        (item["AttributeName"], item["KeyType"])
        for item in existing.get("KeySchema", [])
    ]
    if actual_key_schema != expected_key_schema:
        raise RuntimeError(
            f"{table_name}/{index_name} has key schema {actual_key_schema}; "
            f"expected {expected_key_schema}"
        )
    actual_attribute_types = {
        item["AttributeName"]: item["AttributeType"]
        for item in table.get("AttributeDefinitions", [])
    }
    if any(
        actual_attribute_types.get(name) != attribute_type
        for name, attribute_type in expected_attribute_types.items()
    ):
        raise RuntimeError(
            f"{table_name}/{index_name} has incompatible key attribute types"
        )
    if existing.get("Projection", {}).get("ProjectionType") != "ALL":
        raise RuntimeError(f"{table_name}/{index_name} must use an ALL projection")
    if existing.get("IndexStatus") != "ACTIVE":
        _wait_for_index(client, table_name, index_name)


def _build_index_update(
    table: Dict[str, Any],
    table_name: str,
    index_name: str,
    partition_key: str,
    partition_type: str,
    sort_key: Optional[str],
    sort_type: Optional[str],
) -> Dict[str, Any]:
    definitions_by_name = {
        item["AttributeName"]: item["AttributeType"]
        for item in table.get("AttributeDefinitions", [])
    }
    definitions_by_name[partition_key] = partition_type
    key_schema = [{"AttributeName": partition_key, "KeyType": "HASH"}]
    if sort_key and sort_type:
        definitions_by_name[sort_key] = sort_type
        key_schema.append({"AttributeName": sort_key, "KeyType": "RANGE"})
    definitions = [
        {"AttributeName": name, "AttributeType": attribute_type}
        for name, attribute_type in definitions_by_name.items()
    ]
    create_index: Dict[str, Any] = {
        "IndexName": index_name,
        "KeySchema": key_schema,
        "Projection": {"ProjectionType": "ALL"},
    }
    if table.get("BillingModeSummary", {}).get("BillingMode") != "PAY_PER_REQUEST":
        provisioned = table.get("ProvisionedThroughput", {})
        create_index["ProvisionedThroughput"] = {
            "ReadCapacityUnits": max(1, int(provisioned.get("ReadCapacityUnits", 5))),
            "WriteCapacityUnits": max(1, int(provisioned.get("WriteCapacityUnits", 5))),
        }
    return {
        "TableName": table_name,
        "AttributeDefinitions": definitions,
        "GlobalSecondaryIndexUpdates": [{"Create": create_index}],
    }


def _ensure_index(
    client: Any,
    table_name: str,
    index_name: str,
    partition_key: str,
    partition_type: str,
    sort_key: Optional[str] = None,
    sort_type: Optional[str] = None,
) -> None:
    expected_key_schema = [(partition_key, "HASH")]
    if sort_key and sort_type:
        expected_key_schema.append((sort_key, "RANGE"))

    table = client.describe_table(TableName=table_name)["Table"]
    expected_attribute_types = {partition_key: partition_type}
    if sort_key and sort_type:
        expected_attribute_types[sort_key] = sort_type
    existing = next(
        (
            item
            for item in table.get("GlobalSecondaryIndexes", [])
            if item.get("IndexName") == index_name
        ),
        None,
    )
    if existing is not None:
        _validate_existing_index(
            client,
            table,
            table_name,
            index_name,
            existing,
            expected_key_schema,
            expected_attribute_types,
        )
        return

    client.update_table(
        **_build_index_update(
            table,
            table_name,
            index_name,
            partition_key,
            partition_type,
            sort_key,
            sort_type,
        )
    )
    _wait_for_index(client, table_name, index_name)


def _ensure_shares_table(client: Any, resource: Any) -> Any:
    if not _table_exists(client, SHARES_TABLE):
        client.create_table(
            TableName=SHARES_TABLE,
            KeySchema=[
                {"AttributeName": "collaboratorUserId", "KeyType": "HASH"},
                {"AttributeName": "diagramId", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "collaboratorUserId", "AttributeType": "S"},
                {"AttributeName": "diagramId", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
    client.get_waiter("table_exists").wait(TableName=SHARES_TABLE)
    table_description = client.describe_table(TableName=SHARES_TABLE)["Table"]
    actual_key_schema = [
        (item["AttributeName"], item["KeyType"])
        for item in table_description.get("KeySchema", [])
    ]
    expected_key_schema = [
        ("collaboratorUserId", "HASH"),
        ("diagramId", "RANGE"),
    ]
    if actual_key_schema != expected_key_schema:
        raise RuntimeError(
            f"{SHARES_TABLE} has key schema {actual_key_schema}; "
            f"expected {expected_key_schema}"
        )
    actual_attribute_types = {
        item["AttributeName"]: item["AttributeType"]
        for item in table_description.get("AttributeDefinitions", [])
    }
    if any(
        actual_attribute_types.get(name) != "S"
        for name in ("collaboratorUserId", "diagramId")
    ):
        raise RuntimeError(f"{SHARES_TABLE} must use string key attributes")
    return resource.Table(SHARES_TABLE)


def _scan_problem_rows(problems_table: Any) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    scan: Dict[str, Any] = {
        "ProjectionExpression": "#id, #title, #slug",
        "ExpressionAttributeNames": {
            "#id": "id",
            "#title": "title",
            "#slug": "slug",
        },
    }
    while True:
        response = problems_table.scan(**scan)
        rows.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan["ExclusiveStartKey"] = last_key
    return rows


def _problem_slug_candidate(
    item: Dict[str, Any],
) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    current_slug = item.get("slug")
    title = item.get("title")
    if current_slug is not None and not isinstance(current_slug, str):
        raise RuntimeError(
            f"Problem {item.get('id')} has a non-string slug; "
            "resolve it before creating slug-index"
        )
    effective_slug = current_slug if isinstance(current_slug, str) and current_slug else None
    missing_slug = "slug" not in item or current_slug in ("", None)
    if not missing_slug:
        return effective_slug, None
    if not isinstance(title, str):
        raise RuntimeError(
            f"Problem {item.get('id')} has no usable title for slug backfill"
        )
    generated_slug = problem_slug(title)
    if not generated_slug:
        raise RuntimeError(
            f"Problem {item.get('id')} title does not produce a usable slug; "
            "resolve it before creating slug-index"
        )
    candidate = {
        "id": item["id"],
        "title": title,
        "slug": generated_slug,
        "has_slug": "slug" in item,
        "current_slug": current_slug,
    }
    return generated_slug, candidate


def _collect_problem_slug_candidates(
    rows: list[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], Dict[str, List[str]]]:
    slug_owners: Dict[str, List[str]] = {}
    candidates: List[Dict[str, Any]] = []
    for item in rows:
        effective_slug, candidate = _problem_slug_candidate(item)
        if candidate is not None:
            candidates.append(candidate)
        if effective_slug and item.get("id"):
            slug_owners.setdefault(effective_slug, []).append(str(item["id"]))
    return candidates, slug_owners


def _assert_unique_problem_slugs(slug_owners: Dict[str, List[str]]) -> None:
    collisions = {
        slug: problem_ids
        for slug, problem_ids in slug_owners.items()
        if len(problem_ids) > 1
    }
    if collisions:
        examples = "; ".join(
            f"{slug}: {', '.join(problem_ids)}"
            for slug, problem_ids in list(collisions.items())[:10]
        )
        raise RuntimeError(
            "Problem slug collisions must be resolved before creating slug-index: "
            + examples
        )


def _problem_slug_update(candidate: Dict[str, Any]) -> Dict[str, Any]:
    condition = "#title = :title"
    values: Dict[str, Any] = {
        ":title": candidate["title"],
        ":slug": candidate["slug"],
    }
    if not candidate["has_slug"]:
        condition += " AND attribute_not_exists(#slug)"
    elif candidate["current_slug"] == "":
        condition += " AND #slug = :empty"
        values[":empty"] = ""
    elif candidate["current_slug"] is None:
        condition += " AND attribute_type(#slug, :null_type)"
        values[":null_type"] = "NULL"
    return {
        "Key": {"id": candidate["id"]},
        "UpdateExpression": "SET #slug = :slug",
        "ConditionExpression": condition,
        "ExpressionAttributeNames": {"#slug": "slug", "#title": "title"},
        "ExpressionAttributeValues": values,
    }


def _backfill_problem_slug(problems_table: Any, candidate: Dict[str, Any]) -> None:
    try:
        problems_table.update_item(**_problem_slug_update(candidate))
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise RuntimeError(
                f"Problem {candidate['id']} changed during slug backfill; "
                "pause catalog writes and rerun the migration"
            ) from error
        raise


def _backfill_missing_problem_slugs(problems_table: Any) -> int:
    """Persist model-derived slugs where legacy catalog rows have none."""
    candidates, slug_owners = _collect_problem_slug_candidates(
        _scan_problem_rows(problems_table)
    )
    _assert_unique_problem_slugs(slug_owners)
    for candidate in candidates:
        _backfill_problem_slug(problems_table, candidate)
    return len(candidates)


def _diagram_share_items(diagram: Dict[str, Any]) -> List[Dict[str, Any]]:
    if diagram.get("recordType") in {"canvas", "public_snapshot"}:
        return []
    owner_id = diagram.get("userId")
    diagram_id = diagram.get("id")
    if not owner_id or not diagram_id:
        return []
    return [
        {
            "collaboratorUserId": str(collaborator["userId"]),
            "diagramId": str(diagram_id),
            "ownerId": str(owner_id),
            "permission": str(collaborator.get("permission", "read")),
            "email": collaborator.get("email", ""),
            "name": collaborator.get("name", ""),
            "picture": collaborator.get("picture"),
            "addedAt": collaborator.get("addedAt", ""),
        }
        for collaborator in diagram.get("collaborators", []) or []
        if collaborator.get("userId")
    ]


def _backfill_diagram_shares(diagrams_table: Any, shares_table: Any) -> int:
    total = 0
    scan: Dict[str, Any] = {
        "ProjectionExpression": "#owner, #id, #collaborators, #record_type",
        "ExpressionAttributeNames": {
            "#owner": "userId",
            "#id": "id",
            "#collaborators": "collaborators",
            "#record_type": "recordType",
        },
    }
    while True:
        response = diagrams_table.scan(**scan)
        with shares_table.batch_writer() as batch:
            for diagram in response.get("Items", []):
                for share_item in _diagram_share_items(diagram):
                    batch.put_item(Item=share_item)
                    total += 1
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return total
        scan["ExclusiveStartKey"] = last_key


def _assessment_is_available(assessment: Any) -> bool:
    if not isinstance(assessment, dict):
        return False
    score = assessment.get("score", assessment.get("overall_score"))
    valid_score = not (
        isinstance(score, bool)
        or not isinstance(score, (int, float, Decimal))
        or (isinstance(score, Decimal) and not score.is_finite())
        or not 0 <= score <= 100
        or score != int(score)
    )
    source = assessment.get("source")
    has_legacy_review = source in (None, "") and any(
        assessment.get(field)
        for field in (
            "findings", "feedback", "scores", "summary",
            "detailedAnalysis", "detailed_analysis",
        )
    )
    return bool(
        valid_score
        and (source == "ai" or has_legacy_review)
        and assessment.get("scoreAvailable", True) is True
        and assessment.get("score_available", True) is True
        and assessment.get("verdict") != "unavailable"
    )


def _qualifying_score(item: Dict[str, Any]) -> Optional[int]:
    assessment = item.get("lastAssessment")
    if not isinstance(assessment, dict) or not _assessment_is_available(assessment):
        return None

    latest_check = item.get("lastAssessmentCheck")
    if latest_check and not _assessment_is_available(latest_check):
        return None
    score = assessment.get("score", assessment.get("overall_score"))
    return int(score)


def _leaderboard_update_request(item: Dict[str, Any], score: int) -> Dict[str, Any]:
    condition = "isPublic = :public"
    values: Dict[str, Any] = {
        ":public": True,
        ":problem": item["problemId"],
        ":score": Decimal(score),
    }
    names = {"#updated": "updatedAt"}
    if "updatedAt" in item:
        condition += " AND #updated = :updated"
        values[":updated"] = item["updatedAt"]
    else:
        condition += " AND attribute_not_exists(#updated)"
    return {
        "Key": {"userId": item["userId"], "problemId": item["problemId"]},
        "UpdateExpression": (
            "SET leaderboardProblemId = :problem, "
            "leaderboardScore = :score"
        ),
        "ConditionExpression": condition,
        "ExpressionAttributeNames": names,
        "ExpressionAttributeValues": values,
    }


def _backfill_leaderboard_item(attempts_table: Any, item: Dict[str, Any]) -> bool:
    score = _qualifying_score(item) if item.get("isPublic") else None
    if score is None:
        return False
    if (
        item.get("leaderboardProblemId") == item["problemId"]
        and item.get("leaderboardScore") == Decimal(score)
    ):
        return False
    try:
        attempts_table.update_item(**_leaderboard_update_request(item, score))
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise RuntimeError(
                f"Attempt {item.get('userId')}#{item.get('problemId')} "
                "changed during leaderboard backfill; pause attempt writes "
                "and rerun the migration"
            ) from error
        raise
    return True


def _backfill_leaderboard(attempts_table: Any) -> int:
    total = 0
    scan: Dict[str, Any] = {
        "ProjectionExpression": (
            "#user, #problem, #public, #assessment, #check, "
            "#author_name, #author_picture, #published, #elapsed, #updated, "
            "#leaderboard_problem, #leaderboard_score"
        ),
        "ExpressionAttributeNames": {
            "#user": "userId",
            "#problem": "problemId",
            "#public": "isPublic",
            "#assessment": "lastAssessment",
            "#check": "lastAssessmentCheck",
            "#author_name": "authorName",
            "#author_picture": "authorPicture",
            "#published": "publishedAt",
            "#elapsed": "elapsedTime",
            "#updated": "updatedAt",
            "#leaderboard_problem": "leaderboardProblemId",
            "#leaderboard_score": "leaderboardScore",
        },
    }
    while True:
        response = attempts_table.scan(**scan)
        for item in response.get("Items", []):
            total += _backfill_leaderboard_item(attempts_table, item)
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return total
        scan["ExclusiveStartKey"] = last_key


def main() -> None:
    session = boto3.Session(region_name=REGION)
    client = session.client("dynamodb")
    resource = session.resource("dynamodb")
    shares_table = _ensure_shares_table(client, resource)

    problem_slug_count = _backfill_missing_problem_slugs(
        resource.Table(PROBLEMS_TABLE)
    )
    leaderboard_count = _backfill_leaderboard(resource.Table(ATTEMPTS_TABLE))
    shares_count = _backfill_diagram_shares(
        resource.Table(DIAGRAMS_TABLE), shares_table
    )
    _ensure_index(
        client,
        PROBLEMS_TABLE,
        PROBLEM_SLUG_INDEX,
        "slug",
        "S",
    )
    _ensure_index(
        client,
        ATTEMPTS_TABLE,
        LEADERBOARD_INDEX,
        "leaderboardProblemId",
        "S",
        "leaderboardScore",
        "N",
    )

    print(f"Backfilled {problem_slug_count} missing problem slugs")
    print(f"Backfilled {shares_count} diagram share memberships")
    print(f"Indexed {leaderboard_count} qualifying public attempts")


if __name__ == "__main__":
    main()
