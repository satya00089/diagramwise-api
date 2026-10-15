"""Remove duplicate primary-canvas graphs from Design records.

The default mode is read-only. Run with ``--apply`` only after reviewing the
plan. Existing canvas records remain canonical; designs without canvas records
are left untouched so legacy fallback can continue to serve them.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.canvas_repository import (
    CANVAS_RECORD_TYPE,
    canvas_item_prefix,
)
from app.utils.config import get_settings


def scan_designs(table: Any) -> list[dict[str, Any]]:
    names = {
        "#user": "userId",
        "#id": "id",
        "#record_type": "recordType",
        "#nodes": "nodes",
        "#edges": "edges",
        "#updated": "updatedAt",
        "#node_count": "nodeCount",
        "#edge_count": "edgeCount",
    }
    kwargs = {
        "ProjectionExpression": ", ".join(names),
        "ExpressionAttributeNames": names,
    }
    items: list[dict[str, Any]] = []
    response = table.scan(**kwargs)
    items.extend(response.get("Items", []))
    while response.get("LastEvaluatedKey"):
        response = table.scan(
            **kwargs,
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))
    return items


def canvas_primary_counts(table: Any, owner_id: str, design_id: str):
    query = {
        "KeyConditionExpression": Key("userId").eq(owner_id)
        & Key("id").begins_with(canvas_item_prefix(design_id)),
        "ProjectionExpression": "#id, #type, #order, #deleted, #nodes, #edges",
        "ExpressionAttributeNames": {
            "#id": "id",
            "#type": "recordType",
            "#order": "order",
            "#deleted": "deletedAt",
            "#nodes": "nodeCount",
            "#edges": "edgeCount",
        },
    }
    items: list[dict[str, Any]] = []
    response = table.query(**query)
    items.extend(response.get("Items", []))
    while response.get("LastEvaluatedKey"):
        response = table.query(
            **query,
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))
    active = [
        item
        for item in items
        if item.get("recordType") == CANVAS_RECORD_TYPE
        and not item.get("deletedAt")
    ]
    if not active:
        return None
    primary = min(active, key=lambda item: int(item.get("order", 0)))
    if primary.get("nodeCount") is None or primary.get("edgeCount") is None:
        detail = table.get_item(
            Key={"userId": owner_id, "id": primary["id"]}
        ).get("Item", {})
        nodes = detail.get("nodes", [])
        edges = detail.get("edges", [])
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise ValueError(
                f"Canvas {owner_id}/{primary['id']} has invalid graph arrays"
            )
        return len(nodes), len(edges)
    return int(primary["nodeCount"]), int(primary["edgeCount"])


def build_plan(table: Any) -> list[dict[str, Any]]:
    plan = []
    for design in scan_designs(table):
        if design.get("recordType") in {CANVAS_RECORD_TYPE, "public_snapshot"}:
            continue
        if "nodes" not in design and "edges" not in design:
            continue
        owner_id = design.get("userId")
        design_id = design.get("id")
        if not owner_id or not design_id:
            continue
        counts = canvas_primary_counts(table, owner_id, design_id)
        if counts is None:
            continue
        node_count, edge_count = counts
        plan.append(
            {
                "userId": owner_id,
                "id": design_id,
                "expectedUpdatedAt": design.get("updatedAt"),
                "nodeCount": node_count,
                "edgeCount": edge_count,
            }
        )
    return plan


def apply_plan(table: Any, plan: list[dict[str, Any]]) -> tuple[int, int]:
    applied = 0
    conflicts = 0
    for item in plan:
        names = {"#nodes": "nodes", "#edges": "edges"}
        values: dict[str, Any] = {
            ":node_count": item["nodeCount"],
            ":edge_count": item["edgeCount"],
        }
        condition = Attr("id").exists()
        expected_updated = item.get("expectedUpdatedAt")
        if expected_updated is not None:
            condition = condition & Attr("updatedAt").eq(expected_updated)
        try:
            table.update_item(
                Key={"userId": item["userId"], "id": item["id"]},
                UpdateExpression=(
                    "SET nodeCount = :node_count, edgeCount = :edge_count "
                    "REMOVE #nodes, #edges"
                ),
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
                ConditionExpression=condition,
            )
            applied += 1
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            conflicts += 1
    return applied, conflicts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Remove graph fields from Design records with existing canvas records",
    )
    args = parser.parse_args()

    settings = get_settings()
    table = boto3.resource(
        "dynamodb",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    ).Table(settings.dynamodb_diagrams_table)
    plan = build_plan(table)
    report: dict[str, Any] = {
        "table": settings.dynamodb_diagrams_table,
        "mode": "apply" if args.apply else "dry-run",
        "records": plan,
        "count": len(plan),
    }
    if args.apply:
        applied, conflicts = apply_plan(table, plan)
        report["applied"] = applied
        report["conflicts"] = conflicts
    print(json.dumps(report, indent=2, default=str))
    if not args.apply:
        print("Dry run only; no records were changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
