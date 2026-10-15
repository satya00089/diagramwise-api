"""DynamoDB access for canvases.

Canvases are items in the existing diagrams table, so they need no new table:

- userId: the design owner (the table's partition key)
- id:     "{workspaceId}#canvas#{canvasId}" (the table's sort key)
- recordType: "canvas", so diagram lists and summaries skip these items

Writes are conditional so two tabs or devices cannot silently overwrite each other:
content saves require the caller's expected version to match.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from app.models.canvas_models import CanvasRecord
from app.services.dynamodb_service import (
    CANVAS_RECORD_TYPE,
    convert_decimal_to_float,
    convert_floats_to_decimal,
)

UPDATED_AT_PLACEHOLDER = "#updatedAt"


class CanvasVersionConflict(Exception):
    """The canvas changed since the caller last read it."""

    def __init__(self, current_version: Optional[int] = None):
        super().__init__("Canvas was modified by another session")
        self.current_version = current_version


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_conditional_failure(error: ClientError) -> bool:
    return error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"


def canvas_item_key(workspace_id: str, canvas_id: str) -> str:
    """Sort-key value for a canvas item. Prefix-queryable per workspace."""
    return f"{workspace_id}#canvas#{canvas_id}"


def canvas_item_prefix(workspace_id: str) -> str:
    return f"{workspace_id}#canvas#"


class CanvasRepository:
    """Canvas access for one design owner. No business rules live here."""

    def __init__(
        self, table: Any, owner_id: str, design_title: str = "Untitled Design"
    ):
        self.table = table
        self.owner_id = owner_id
        self.design_title = design_title

    def _key(self, workspace_id: str, canvas_id: str) -> Dict[str, str]:
        return {"userId": self.owner_id, "id": canvas_item_key(workspace_id, canvas_id)}

    def _from_item(self, item: Dict[str, Any]) -> CanvasRecord:
        data = convert_decimal_to_float(dict(item))
        data.setdefault("nodeCount", len(data.get("nodes", [])))
        data.setdefault("edgeCount", len(data.get("edges", [])))
        # The parent design is authoritative; older canvas rows may not have a title.
        data["title"] = self.design_title
        # The model calls the canvas ID `id`; the stored sort key is a composite.
        data["id"] = data.pop("canvasId")
        data.pop("userId", None)
        data.pop("recordType", None)
        return CanvasRecord(**data)

    def _to_item(self, canvas: CanvasRecord) -> Dict[str, Any]:
        # mode="json" keeps enums (canvas kind) as plain strings that DynamoDB can store.
        data = canvas.model_dump(mode="json")
        data["nodeCount"] = len(canvas.nodes)
        data["edgeCount"] = len(canvas.edges)
        canvas_id = data.pop("id")
        data["canvasId"] = canvas_id
        data["userId"] = self.owner_id
        data["id"] = canvas_item_key(canvas.workspaceId, canvas_id)
        data["recordType"] = CANVAS_RECORD_TYPE
        return convert_floats_to_decimal(data)

    def list_canvases(self, workspace_id: str) -> List[CanvasRecord]:
        """Every active canvas in a workspace, in tab order."""
        query: Dict[str, Any] = {
            "KeyConditionExpression": Key("userId").eq(self.owner_id)
            & Key("id").begins_with(canvas_item_prefix(workspace_id)),
        }
        items: List[Dict[str, Any]] = []
        while True:
            response = self.table.query(**query)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            query["ExclusiveStartKey"] = last_key

        canvases = [self._from_item(item) for item in items]
        active = [c for c in canvases if c.deletedAt is None]
        return sorted(active, key=lambda c: c.order)

    def list_canvas_summaries(self, workspace_id: str) -> List[Dict[str, Any]]:
        """Query canvas metadata without loading graph payloads when counts exist."""
        names = {
            "#user": "userId",
            "#sort": "id",
            "#canvas": "canvasId",
            "#name": "name",
            "#kind": "kind",
            "#order": "order",
            "#version": "version",
            "#updated": "updatedAt",
            "#deleted": "deletedAt",
            "#nodes": "nodeCount",
            "#edges": "edgeCount",
        }
        query: Dict[str, Any] = {
            "KeyConditionExpression": Key("userId").eq(self.owner_id)
            & Key("id").begins_with(canvas_item_prefix(workspace_id)),
            "ProjectionExpression": ", ".join(names),
            "ExpressionAttributeNames": names,
        }
        items: List[Dict[str, Any]] = []
        while True:
            response = self.table.query(**query)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            query["ExclusiveStartKey"] = last_key

        summaries: List[Dict[str, Any]] = []
        for item in items:
            if item.get("deletedAt") is not None:
                continue
            node_count = item.get("nodeCount")
            edge_count = item.get("edgeCount")
            if node_count is None or edge_count is None:
                # Legacy rows lack counts; fetch only those rows until their next save.
                canvas = self.get_canvas(workspace_id, item["canvasId"])
                if canvas is None:
                    continue
                node_count = len(canvas.nodes)
                edge_count = len(canvas.edges)
            summaries.append(
                {
                    "id": item["canvasId"],
                    "title": self.design_title,
                    "name": item["name"],
                    "kind": item["kind"],
                    "order": item["order"],
                    "nodeCount": int(node_count),
                    "edgeCount": int(edge_count),
                    "version": item["version"],
                    "updatedAt": item["updatedAt"],
                }
            )
        return sorted(summaries, key=lambda canvas: canvas["order"])

    def get_canvas(self, workspace_id: str, canvas_id: str) -> Optional[CanvasRecord]:
        response = self.table.get_item(Key=self._key(workspace_id, canvas_id))
        item = response.get("Item")
        if not item:
            return None
        canvas = self._from_item(item)
        return canvas if canvas.deletedAt is None else None

    def put_new_canvas(self, canvas: CanvasRecord) -> bool:
        """Insert a canvas only if the ID is free. Returns False if it already exists."""
        try:
            self.table.put_item(
                Item=self._to_item(canvas),
                ConditionExpression=Attr("id").not_exists(),
            )
            return True
        except ClientError as error:
            if _is_conditional_failure(error):
                return False
            raise

    def update_meta(
        self,
        workspace_id: str,
        canvas_id: str,
        updates: Dict[str, Any],
    ) -> Optional[CanvasRecord]:
        """Set name, kind and/or order on an active canvas."""
        if not updates:
            return self.get_canvas(workspace_id, canvas_id)

        names = {UPDATED_AT_PLACEHOLDER: "updatedAt"}
        values: Dict[str, Any] = {":updatedAt": _utc_now()}
        set_parts = [f"{UPDATED_AT_PLACEHOLDER} = :updatedAt"]
        # Placeholder prefixes avoid boto3's own generated #n0/:v0 names used by the condition.
        for index, (field, value) in enumerate(updates.items()):
            names[f"#fld{index}"] = field
            values[f":val{index}"] = convert_floats_to_decimal(value)
            set_parts.append(f"#fld{index} = :val{index}")

        try:
            response = self.table.update_item(
                Key=self._key(workspace_id, canvas_id),
                UpdateExpression="SET " + ", ".join(set_parts),
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
                ConditionExpression=Attr("id").exists() & Attr("deletedAt").not_exists(),
                ReturnValues="ALL_NEW",
            )
        except ClientError as error:
            if _is_conditional_failure(error):
                return None
            raise
        return self._from_item(response["Attributes"])

    def save_content(
        self,
        workspace_id: str,
        canvas_id: str,
        nodes: List[Any],
        edges: List[Any],
        expected_version: int,
    ) -> CanvasRecord:
        """Replace nodes and edges if the stored version still equals expected_version."""
        try:
            response = self.table.update_item(
                Key=self._key(workspace_id, canvas_id),
                UpdateExpression=(
                    "SET #nodes = :nodes, #edges = :edges, #nodeCount = :nodeCount, "
                    "#edgeCount = :edgeCount, #version = :next, "
                    f"{UPDATED_AT_PLACEHOLDER} = :updatedAt"
                ),
                ExpressionAttributeNames={
                    "#nodes": "nodes",
                    "#edges": "edges",
                    "#nodeCount": "nodeCount",
                    "#edgeCount": "edgeCount",
                    "#version": "version",
                    UPDATED_AT_PLACEHOLDER: "updatedAt",
                },
                ExpressionAttributeValues={
                    ":nodes": convert_floats_to_decimal(nodes),
                    ":edges": convert_floats_to_decimal(edges),
                    ":nodeCount": len(nodes),
                    ":edgeCount": len(edges),
                    ":next": expected_version + 1,
                    ":updatedAt": _utc_now(),
                },
                ConditionExpression=Attr("version").eq(expected_version)
                & Attr("deletedAt").not_exists(),
                ReturnValues="ALL_NEW",
            )
        except ClientError as error:
            if _is_conditional_failure(error):
                current = self.get_canvas(workspace_id, canvas_id)
                raise CanvasVersionConflict(
                    current.version if current else None
                ) from error
            raise
        return self._from_item(response["Attributes"])

    def soft_delete(self, workspace_id: str, canvas_id: str) -> bool:
        """Mark a canvas deleted. Content is kept so the delete can be undone or audited."""
        try:
            self.table.update_item(
                Key=self._key(workspace_id, canvas_id),
                UpdateExpression=(
                    f"SET #deletedAt = :now, {UPDATED_AT_PLACEHOLDER} = :now"
                ),
                ExpressionAttributeNames={
                    "#deletedAt": "deletedAt",
                    UPDATED_AT_PLACEHOLDER: "updatedAt",
                },
                ExpressionAttributeValues={":now": _utc_now()},
                ConditionExpression=Attr("id").exists() & Attr("deletedAt").not_exists(),
            )
        except ClientError as error:
            if _is_conditional_failure(error):
                return False
            raise
        return True
