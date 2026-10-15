"""Workspace canvas operations: business rules on top of CanvasRepository.

`legacy_fallback` is the virtual canvas built from a pre-multi-canvas diagram.
It is shown when a workspace has no canvas records yet, and it is persisted
(idempotently) before the first write so it becomes a real record.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import logging

from app.models.canvas_models import (
    CanvasKind,
    CanvasRecord,
    CanvasValidationError,
    build_canvas,
    dedupe_canvas_name,
    ensure_not_last_canvas,
    new_canvas_id,
    normalize_canvas_name,
    primary_canvas,
    canvas_summary,
    validate_canvas_graph,
)
from app.services.canvas_repository import CanvasRepository, CanvasVersionConflict

logger = logging.getLogger(__name__)
SYNC_RETRY_ATTEMPTS = 3


class CanvasNotFound(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CanvasService:
    def __init__(
        self, repository: CanvasRepository, design_title: str = "Untitled Design"
    ):
        self.repository = repository
        self.design_title = design_title

    def list_canvases(
        self, workspace_id: str, legacy_fallback: Optional[CanvasRecord]
    ) -> List[CanvasRecord]:
        canvases = self.repository.list_canvases(workspace_id)
        if canvases:
            return canvases
        return [legacy_fallback] if legacy_fallback else []

    def list_canvas_summaries(
        self, workspace_id: str, legacy_fallback: Optional[CanvasRecord]
    ) -> List[Dict[str, Any]]:
        summaries = self.repository.list_canvas_summaries(workspace_id)
        if summaries:
            return summaries
        return [canvas_summary(legacy_fallback)] if legacy_fallback else []

    def get_canvas(
        self,
        workspace_id: str,
        canvas_id: str,
        legacy_fallback: Optional[CanvasRecord],
    ) -> CanvasRecord:
        canvas = self.repository.get_canvas(workspace_id, canvas_id)
        if canvas:
            return canvas
        if legacy_fallback and legacy_fallback.id == canvas_id:
            return legacy_fallback
        raise CanvasNotFound(canvas_id)

    def materialize_legacy(
        self, workspace_id: str, legacy_fallback: Optional[CanvasRecord]
    ) -> None:
        """Persist the legacy canvas once. Safe to call repeatedly and concurrently."""
        if legacy_fallback is None:
            return
        if self.repository.list_canvases(workspace_id):
            return
        self.repository.put_new_canvas(legacy_fallback)

    def sync_primary_from_legacy(
        self, workspace_id: str, nodes: List[dict], edges: List[dict]
    ) -> bool:
        """Apply a pre-multi-canvas save to the primary canvas.

        Only runs when the workspace already has canvas records. Returns False
        when there is nothing to sync, or when the legacy payload is not a valid
        canvas graph (the legacy save still succeeds; the canvas keeps its state).
        """
        try:
            validate_canvas_graph(nodes, edges)
        except CanvasValidationError:
            logger.warning(
                "Skipping primary canvas sync because the legacy graph is invalid."
            )
            return False
        for _ in range(SYNC_RETRY_ATTEMPTS):
            primary = primary_canvas(self.repository.list_canvases(workspace_id))
            if primary is None:
                return False
            try:
                self.repository.save_content(
                    workspace_id, primary.id, nodes, edges, primary.version
                )
                return True
            except CanvasVersionConflict:
                continue
        raise CanvasVersionConflict(None)

    def create_canvas(
        self,
        workspace_id: str,
        name: str,
        kind: CanvasKind,
        legacy_fallback: Optional[CanvasRecord],
    ) -> CanvasRecord:
        self.materialize_legacy(workspace_id, legacy_fallback)
        existing = self.repository.list_canvases(workspace_id)
        canvas = build_canvas(
            workspace_id,
            name,
            kind,
            existing,
            _now(),
            canvas_id=new_canvas_id(),
            title=self.design_title,
        )
        if not self.repository.put_new_canvas(canvas):
            raise CanvasValidationError("Canvas could not be created, please retry")
        return canvas

    def update_canvas(
        self,
        workspace_id: str,
        canvas_id: str,
        legacy_fallback: Optional[CanvasRecord],
        name: Optional[str] = None,
        kind: Optional[CanvasKind] = None,
    ) -> CanvasRecord:
        self.materialize_legacy(workspace_id, legacy_fallback)
        updates = {}
        if name is not None:
            clean = normalize_canvas_name(name)
            others = [
                c.name
                for c in self.repository.list_canvases(workspace_id)
                if c.id != canvas_id
            ]
            updates["name"] = dedupe_canvas_name(clean, others)
        if kind is not None:
            updates["kind"] = kind.value
        updated = self.repository.update_meta(workspace_id, canvas_id, updates)
        if updated is None:
            raise CanvasNotFound(canvas_id)
        return updated

    def reorder_canvases(
        self,
        workspace_id: str,
        ordered_ids: List[str],
        legacy_fallback: Optional[CanvasRecord],
    ) -> List[CanvasRecord]:
        """Apply a full new tab order. The list must name every active canvas exactly once."""
        self.materialize_legacy(workspace_id, legacy_fallback)
        active = self.repository.list_canvases(workspace_id)
        active_ids = [c.id for c in active]
        if sorted(ordered_ids) != sorted(active_ids):
            raise CanvasValidationError(
                "Reorder must list every canvas in the workspace exactly once"
            )
        for position, canvas_id in enumerate(ordered_ids):
            current = next(c for c in active if c.id == canvas_id)
            if current.order != position:
                self.repository.update_meta(workspace_id, canvas_id, {"order": position})
        return self.repository.list_canvases(workspace_id)

    def save_content(
        self,
        workspace_id: str,
        canvas_id: str,
        nodes: List[dict],
        edges: List[dict],
        expected_version: int,
        legacy_fallback: Optional[CanvasRecord],
    ) -> CanvasRecord:
        validate_canvas_graph(nodes, edges)
        self.materialize_legacy(workspace_id, legacy_fallback)
        return self.repository.save_content(
            workspace_id, canvas_id, nodes, edges, expected_version
        )

    def delete_canvas(
        self,
        workspace_id: str,
        canvas_id: str,
        legacy_fallback: Optional[CanvasRecord],
    ) -> None:
        self.materialize_legacy(workspace_id, legacy_fallback)
        active = self.repository.list_canvases(workspace_id)
        if not any(c.id == canvas_id for c in active):
            raise CanvasNotFound(canvas_id)
        ensure_not_last_canvas(active)
        if not self.repository.soft_delete(workspace_id, canvas_id):
            raise CanvasNotFound(canvas_id)

    def duplicate_canvas(
        self,
        workspace_id: str,
        canvas_id: str,
        legacy_fallback: Optional[CanvasRecord],
    ) -> CanvasRecord:
        source = self.get_canvas(workspace_id, canvas_id, legacy_fallback)
        self.materialize_legacy(workspace_id, legacy_fallback)
        existing = self.repository.list_canvases(workspace_id)
        copy_name = dedupe_canvas_name(f"{source.name} copy"[:60], [c.name for c in existing])
        # Node and edge IDs only need to be unique within a canvas, so they are copied as-is.
        canvas = build_canvas(
            workspace_id,
            copy_name,
            source.kind,
            existing,
            _now(),
            canvas_id=new_canvas_id(),
            title=self.design_title,
        )
        canvas = canvas.model_copy(
            update={
                "nodes": list(source.nodes),
                "edges": list(source.edges),
                "nodeCount": len(source.nodes),
                "edgeCount": len(source.edges),
            }
        )
        if not self.repository.put_new_canvas(canvas):
            raise CanvasValidationError("Canvas could not be duplicated, please retry")
        return canvas


__all__ = ["CanvasService", "CanvasNotFound", "CanvasVersionConflict"]
