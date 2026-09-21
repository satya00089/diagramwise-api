"""Migrate generic canvas descriptions to the canonical ``purpose`` key.

The default mode is a read-only dry run. Pass ``--apply`` only after reviewing
the JSON report. The migration is deliberately scoped to nested canvas node
and edge data plus generic catalog property definitions; top-level metadata and
specialized Body/Content fields are not changed.
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


def _rename_legacy_value(
    data: dict[str, Any],
    location: str,
    report: dict[str, Any],
) -> bool:
    """Rename one scoped dictionary key, preserving the canonical value."""
    if "description" not in data:
        return False

    report["legacy_candidates"] += 1
    if "purpose" in data:
        report["conflicts"].append(location)
    else:
        data["purpose"] = data["description"]
        report["migrated_fields"] += 1
    del data["description"]
    return True


def _migrate_canvas_item(
    item: dict[str, Any],
    report: dict[str, Any],
) -> tuple[dict[str, Any], bool, bool]:
    """Return a copied item, whether it changed, and whether it was skipped."""
    updated = dict(item)
    changed = False
    skipped = False

    for collection_name in ("nodes", "edges"):
        collection = item.get(collection_name)
        if collection is None:
            continue
        if not isinstance(collection, list):
            report["skipped_records"] += 1
            report["skipped_details"].append(
                f"{item.get('id', item.get('problemId', '<unknown>'))}: invalid {collection_name}"
            )
            skipped = True
            continue

        copied_collection: list[Any] = []
        for index, entry in enumerate(collection):
            if not isinstance(entry, dict):
                copied_collection.append(entry)
                report["skipped_fields"] += 1
                continue
            copied_entry = dict(entry)
            entry_data = entry.get("data")
            if not isinstance(entry_data, dict):
                copied_collection.append(copied_entry)
                continue

            copied_data = dict(entry_data)
            changed_entry = _rename_legacy_value(
                copied_data,
                f"{collection_name}[{index}].data",
                report,
            )

            nested_properties = entry_data.get("properties")
            if isinstance(nested_properties, dict):
                copied_properties = dict(nested_properties)
                changed_entry = (
                    _rename_legacy_value(
                        copied_properties,
                        f"{collection_name}[{index}].data.properties",
                        report,
                    )
                    or changed_entry
                )
                copied_data["properties"] = copied_properties
            elif nested_properties is not None:
                report["skipped_fields"] += 1

            copied_entry["data"] = copied_data
            copied_collection.append(copied_entry)
            changed = changed_entry or changed

        updated[collection_name] = copied_collection

    return updated, changed, skipped


def _migrate_catalog_item(
    item: dict[str, Any],
    report: dict[str, Any],
) -> tuple[dict[str, Any], bool, bool]:
    """Rename only generic property definitions in a catalog item."""
    properties = item.get("properties")
    if properties is None:
        return dict(item), False, False
    if not isinstance(properties, list):
        report["skipped_records"] += 1
        report["skipped_details"].append(
            f"{item.get('platform', '<unknown>')}/{item.get('id', '<unknown>')}: invalid properties"
        )
        return dict(item), False, True

    updated = dict(item)
    updated_properties: list[Any] = []
    changed = False
    for index, property_definition in enumerate(properties):
        if not isinstance(property_definition, dict):
            updated_properties.append(property_definition)
            report["skipped_fields"] += 1
            continue
        copied_property = dict(property_definition)
        if (
            copied_property.get("key") == "description"
            and copied_property.get("label") == "Description"
        ):
            copied_property["key"] = "purpose"
            copied_property["label"] = "Purpose"
            copied_property["placeholder"] = (
                "What does this component do in the architecture?"
            )
            report["migrated_fields"] += 1
            changed = True
        updated_properties.append(copied_property)
    updated["properties"] = updated_properties
    return updated, changed, False


def new_report(table_name: str) -> dict[str, Any]:
    return {
        "table": table_name,
        "scanned_records": 0,
        "migrated_records": 0,
        "migrated_fields": 0,
        "legacy_candidates": 0,
        "conflicts": [],
        "skipped_records": 0,
        "skipped_fields": 0,
        "skipped_details": [],
        "updates": [],
    }


def scan_all(table: Any) -> list[dict[str, Any]]:
    """Scan a DynamoDB table, following pagination tokens."""
    items: list[dict[str, Any]] = []
    response = table.scan()
    items.extend(response.get("Items", []))
    while response.get("LastEvaluatedKey"):
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))
    return items


def process_table(
    table: Any,
    table_name: str,
    kind: str,
    key_names: tuple[str, str],
) -> dict[str, Any]:
    report = new_report(table_name)
    for item in scan_all(table):
        report["scanned_records"] += 1
        if kind == "catalog":
            updated, changed, skipped = _migrate_catalog_item(item, report)
        else:
            updated, changed, skipped = _migrate_canvas_item(item, report)
        if changed:
            keys = {key: item.get(key) for key in key_names}
            report["updates"].append({"key": keys, "item": updated})
            report["migrated_records"] += 1
        elif skipped:
            continue
    return report


def apply_report(table: Any, report: dict[str, Any], kind: str) -> None:
    """Apply only the changed scoped attributes from a report."""
    for update in report["updates"]:
        item = update["item"]
        if kind == "catalog":
            table.update_item(
                Key=update["key"],
                UpdateExpression="SET #properties = :properties",
                ExpressionAttributeNames={"#properties": "properties"},
                ExpressionAttributeValues={":properties": item["properties"]},
            )
        else:
            table.update_item(
                Key=update["key"],
                UpdateExpression="SET #nodes = :nodes, #edges = :edges",
                ExpressionAttributeNames={"#nodes": "nodes", "#edges": "edges"},
                ExpressionAttributeValues={
                    ":nodes": item.get("nodes", []),
                    ":edges": item.get("edges", []),
                },
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the reported changes; without this flag the script is dry-run only",
    )
    args = parser.parse_args()

    settings = get_settings()
    dynamodb = boto3.resource(
        "dynamodb",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
    tables = [
        (
            settings.dynamodb_diagrams_table,
            dynamodb.Table(settings.dynamodb_diagrams_table),
            "canvas",
            ("userId", "id"),
        ),
        (
            settings.dynamodb_attempts_table,
            dynamodb.Table(settings.dynamodb_attempts_table),
            "canvas",
            ("userId", "problemId"),
        ),
        (
            settings.components_table_name,
            dynamodb.Table(settings.components_table_name),
            "catalog",
            ("platform", "id"),
        ),
    ]

    reports: list[dict[str, Any]] = []
    for table_name, table, kind, key_names in tables:
        report = process_table(table, table_name, kind, key_names)
        reports.append(report)
        if args.apply:
            apply_report(table, report, kind)

    summary = {
        "mode": "apply" if args.apply else "dry-run",
        "tables": reports,
        "verification": {
            "scanned_records": sum(r["scanned_records"] for r in reports),
            "migrated_records": sum(r["migrated_records"] for r in reports),
            "migrated_fields": sum(r["migrated_fields"] for r in reports),
            "conflicts": sum(len(r["conflicts"]) for r in reports),
            "skipped_records": sum(r["skipped_records"] for r in reports),
            "skipped_fields": sum(r["skipped_fields"] for r in reports),
            "remaining_legacy_candidates": (
                0
                if args.apply
                else sum(r["legacy_candidates"] for r in reports)
            ),
        },
    }
    print(json.dumps(summary, indent=2, default=str))
    if not args.apply:
        print("Dry run only; no records were changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
