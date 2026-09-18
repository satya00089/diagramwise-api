"""Backfill persisted node and edge counts for diagram list responses.

The default mode is read-only. Run with ``--apply`` only after reviewing the
reported plan. The operation is idempotent and paginates through the table.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.utils.config import get_settings


def scan_diagrams(table: Any) -> list[dict[str, Any]]:
    """Read only the fields required to calculate missing counts."""
    projection_names = {
        "#user_id": "userId",
        "#id": "id",
        "#nodes": "nodes",
        "#edges": "edges",
    }
    scan_kwargs = {
        "ProjectionExpression": "#user_id, #id, #nodes, #edges",
        "ExpressionAttributeNames": projection_names,
    }
    items: list[dict[str, Any]] = []
    response = table.scan(**scan_kwargs)
    items.extend(response.get("Items", []))
    while response.get("LastEvaluatedKey"):
        response = table.scan(
            **scan_kwargs,
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))
    return items


def count_fields(item: dict[str, Any]) -> tuple[int, int]:
    nodes = item.get("nodes")
    edges = item.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError(
            f"Diagram {item.get('userId')}/{item.get('id')} has invalid nodes or edges"
        )
    return len(nodes), len(edges)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write nodeCount and edgeCount values after reviewing the plan",
    )
    args = parser.parse_args()

    settings = get_settings()
    table = boto3.resource(
        "dynamodb",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    ).Table(settings.dynamodb_diagrams_table)

    updates: list[dict[str, Any]] = []
    for item in scan_diagrams(table):
        node_count, edge_count = count_fields(item)
        if (
            item.get("nodeCount") == node_count
            and item.get("edgeCount") == edge_count
        ):
            continue
        updates.append(
            {
                "userId": item.get("userId"),
                "id": item.get("id"),
                "nodeCount": node_count,
                "edgeCount": edge_count,
            }
        )

    print(
        json.dumps(
            {
                "table": settings.dynamodb_diagrams_table,
                "updates": updates,
                "count": len(updates),
                "mode": "apply" if args.apply else "dry-run",
            },
            indent=2,
            default=str,
        )
    )

    if not args.apply:
        print("Dry run only; no records were changed.")
        return 0

    for update in updates:
        if not update["userId"] or not update["id"]:
            raise RuntimeError(f"Cannot update diagram without a key: {update}")
        table.update_item(
            Key={"userId": update["userId"], "id": update["id"]},
            UpdateExpression="SET nodeCount = :node_count, edgeCount = :edge_count",
            ExpressionAttributeValues={
                ":node_count": update["nodeCount"],
                ":edge_count": update["edgeCount"],
            },
        )

    print(f"Backfilled {len(updates)} diagram count record(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
