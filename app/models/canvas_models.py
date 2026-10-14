"""Canvas (tab) models and pure rules for multi-canvas workspaces.

A workspace (one design or one problem attempt) holds an ordered list of
canvases. Everything in this module is storage-agnostic so the rules can be
tested without DynamoDB.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Sequence
from uuid import uuid4

from pydantic import BaseModel, Field

MAX_CANVASES_PER_WORKSPACE = 10
MAX_CANVAS_NAME_LENGTH = 60
LEGACY_CANVAS_NAME = "Main"


class CanvasKind(str, Enum):
    """Label-only canvas type in v1. Palettes are not kind-specific yet."""

    HIGH_LEVEL = "high_level"
    FLOW = "flow"
    ER = "er"
    UML = "uml"
    LOW_LEVEL = "low_level"
    OTHER = "other"


class CanvasRecord(BaseModel):
    """One tab of a workspace."""

    id: str
    workspaceId: str
    name: str = Field(..., min_length=1, max_length=MAX_CANVAS_NAME_LENGTH)
    kind: CanvasKind = CanvasKind.OTHER
    order: int = Field(..., ge=0)
    nodes: List[Any] = Field(default_factory=list)
    edges: List[Any] = Field(default_factory=list)
    version: int = Field(default=1, ge=1)
    createdAt: str
    updatedAt: str
    deletedAt: Optional[str] = None


class CanvasCreate(BaseModel):
    """Request body for creating a canvas."""

    name: str = Field(..., min_length=1, max_length=MAX_CANVAS_NAME_LENGTH)
    kind: CanvasKind = CanvasKind.OTHER


class CanvasUpdate(BaseModel):
    """Request body for renaming, re-kinding or reordering a canvas."""

    name: Optional[str] = Field(None, min_length=1, max_length=MAX_CANVAS_NAME_LENGTH)
    kind: Optional[CanvasKind] = None
    order: Optional[int] = Field(None, ge=0)


class CanvasContentUpdate(BaseModel):
    """Request body for saving canvas content. `version` guards against lost updates."""

    nodes: List[Any] = Field(default_factory=list)
    edges: List[Any] = Field(default_factory=list)
    version: int = Field(..., ge=1)


class CanvasValidationError(ValueError):
    """Raised when a canvas or workspace rule is violated."""


def normalize_canvas_name(raw: str) -> str:
    """Trim and collapse whitespace; reject empty names and over-long names."""
    name = " ".join((raw or "").split())
    if not name:
        raise CanvasValidationError("Canvas name cannot be empty")
    if len(name) > MAX_CANVAS_NAME_LENGTH:
        raise CanvasValidationError(
            f"Canvas name cannot exceed {MAX_CANVAS_NAME_LENGTH} characters"
        )
    return name


def dedupe_canvas_name(name: str, existing_names: Sequence[str]) -> str:
    """Return `name`, or `name (2)`, `name (3)`... if it collides case-insensitively."""
    taken = {existing.casefold() for existing in existing_names}
    if name.casefold() not in taken:
        return name
    counter = 2
    while True:
        suffix = f" ({counter})"
        base = name[: MAX_CANVAS_NAME_LENGTH - len(suffix)]
        candidate = f"{base}{suffix}"
        if candidate.casefold() not in taken:
            return candidate
        counter += 1


def _collect_canvas_node_ids(nodes: List[Any]) -> set:
    node_ids: set = set()
    for node in nodes:
        node_id = node.get("id") if isinstance(node, dict) else None
        if not node_id or not isinstance(node_id, str):
            raise CanvasValidationError("Every node needs a string id")
        if node_id in node_ids:
            raise CanvasValidationError(f"Duplicate node id: {node_id}")
        node_ids.add(node_id)
    return node_ids


def _validate_canvas_edge(edge: Any, node_ids: set) -> None:
    if not isinstance(edge, dict):
        raise CanvasValidationError("Every edge must be an object")
    for endpoint in ("source", "target"):
        ref = edge.get(endpoint)
        if ref not in node_ids:
            raise CanvasValidationError(
                "Edge "
                f"{edge.get('id', '?')} references a node that is not on this canvas: {ref}"
            )


def validate_canvas_graph(nodes: List[Any], edges: List[Any]) -> None:
    """Ensure IDs are unique and every edge targets nodes on this canvas."""
    node_ids = _collect_canvas_node_ids(nodes)
    for edge in edges:
        _validate_canvas_edge(edge, node_ids)


def ensure_canvas_capacity(active_canvases: Sequence[CanvasRecord]) -> None:
    """Block creating a canvas once the workspace reaches the limit."""
    if len(active_canvases) >= MAX_CANVASES_PER_WORKSPACE:
        raise CanvasValidationError(
            f"A workspace can have at most {MAX_CANVASES_PER_WORKSPACE} canvases"
        )


def ensure_not_last_canvas(active_canvases: Sequence[CanvasRecord]) -> None:
    """A workspace always keeps at least one canvas."""
    if len(active_canvases) <= 1:
        raise CanvasValidationError("A workspace must keep at least one canvas")


def new_canvas_id() -> str:
    return str(uuid4())


def build_canvas(
    workspace_id: str,
    name: str,
    kind: CanvasKind,
    existing: Sequence[CanvasRecord],
    now: str,
    canvas_id: Optional[str] = None,
) -> CanvasRecord:
    """Create a canvas at the end of the tab order with a unique, normalized name."""
    ensure_canvas_capacity(existing)
    clean_name = normalize_canvas_name(name)
    unique_name = dedupe_canvas_name(clean_name, [c.name for c in existing])
    next_order = max((c.order for c in existing), default=-1) + 1
    return CanvasRecord(
        id=canvas_id or new_canvas_id(),
        workspaceId=workspace_id,
        name=unique_name,
        kind=kind,
        order=next_order,
        nodes=[],
        edges=[],
        version=1,
        createdAt=now,
        updatedAt=now,
    )


def primary_canvas(canvases: Sequence[CanvasRecord]) -> Optional[CanvasRecord]:
    """The first active canvas in tab order. Used by legacy clients and default assessment."""
    active = sorted(
        (c for c in canvases if c.deletedAt is None), key=lambda c: c.order
    )
    return active[0] if active else None


def legacy_canvas_from_diagram(
    diagram_id: str,
    nodes: List[Any],
    edges: List[Any],
    created_at: str,
    updated_at: str,
) -> CanvasRecord:
    """Present a pre-multi-canvas diagram as one canvas.

    The canvas ID equals the diagram ID so existing links and public snapshots
    keep resolving. Nothing is written by this function; persistence happens on
    the first real write.
    """
    return CanvasRecord(
        id=diagram_id,
        workspaceId=diagram_id,
        name=LEGACY_CANVAS_NAME,
        kind=CanvasKind.OTHER,
        order=0,
        nodes=nodes,
        edges=edges,
        version=1,
        createdAt=created_at,
        updatedAt=updated_at,
    )


def canvas_summary(canvas: CanvasRecord) -> Dict[str, Any]:
    """Metadata-only view used in workspace responses (no node or edge payload)."""
    return {
        "id": canvas.id,
        "name": canvas.name,
        "kind": canvas.kind.value,
        "order": canvas.order,
        "nodeCount": len(canvas.nodes),
        "edgeCount": len(canvas.edges),
        "version": canvas.version,
        "updatedAt": canvas.updatedAt,
    }
