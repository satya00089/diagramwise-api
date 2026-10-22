"""Observable guide-structure checks, used only after an AI review fails."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.models.request_models import AssessmentRequest

logger = logging.getLogger(__name__)


def _role(catalog_id: str) -> str:
    aliases = {"loadbalancer": "load-balancer", "backend-server": "backend",
               "scheduler": "backend", "search": "backend", "search-engine": "backend",
               "object-storage": "storage", "file-storage": "storage", "database": "database",
               "auth-service": "security", "tracing": "monitoring"}
    value = catalog_id.lower().replace("_", "-")
    return aliases.get(value, value)


def _match_reference_components(
    request: AssessmentRequest, steps: list[dict]
) -> tuple[dict[str, str], list[dict[str, str]]]:
    expected = [step["component"] for step in steps if step.get("type") == "add_component" and step.get("component")]
    used: set[str] = set()
    mapping: dict[str, str] = {}
    checks = []
    for component in expected:
        role = _role(component["componentType"])
        candidates = [candidate for candidate in request.components if candidate.id not in used
                      and _role(str((candidate.properties or {}).get("componentId") or candidate.type.value)) == role]
        # Labels disambiguate repeated roles, but IDs/provider/positions are not required.
        candidate = next((node for node in candidates if node.label.lower() == component["label"].lower()),
                         candidates[0] if len(candidates) == 1 else None)
        if candidate:
            used.add(candidate.id)
            mapping[component["nodeId"]] = candidate.id
        checks.append({"title": f"Reference role: {component['label']}",
                       "status": "supported" if candidate else "needs_clarification",
                       "explanation": "A matching role is visible; this does not verify its behavior."
                       if candidate else "No unambiguous matching role was found. A different architecture may still be valid."})
    return mapping, checks


def _check_reference_connections(
    request: AssessmentRequest,
    steps: list[dict],
    mapping: dict[str, str],
) -> list[dict[str, str]]:
    checks = []
    actual_connections = {(edge.source, edge.target) for edge in request.connections or []}
    for step in steps:
        connection = step.get("connection")
        if step.get("type") != "add_connection" or not connection:
            continue
        endpoints = (mapping.get(connection["sourceNodeId"]), mapping.get(connection["targetNodeId"]))
        supported = None not in endpoints and endpoints in actual_connections
        checks.append({"title": f"Reference relationship: {connection['label']}",
                       "status": "supported" if supported else "needs_clarification",
                       "explanation": "The relationship is visible; correctness has not been assessed."
                       if supported else "This reference relationship could not be confirmed from the submitted structure."})
    return checks


def compare_walkthrough_structure(request: AssessmentRequest, walkthrough: dict[str, Any]) -> list[dict[str, str]]:
    """One-to-one role matching checks structure, never architectural quality."""
    steps = walkthrough.get("steps", [])
    mapping, checks = _match_reference_components(request, steps)
    checks.extend(_check_reference_connections(request, steps, mapping))
    return checks


async def get_fallback_reference_checks(request: AssessmentRequest) -> list[dict[str, str]]:
    if not request.problem or not request.problem.id or request.problem.id.startswith("custom-"):
        return []
    try:
        from app.services.dynamodb_service import dynamodb_service
        data = await asyncio.wait_for(asyncio.to_thread(
            dynamodb_service.get_walkthrough_by_problem_id, request.problem.id,
        ), timeout=3)
        if not data:
            return []
        requested_revision = request.problem.requirementRevision or (
            request.problem.requirementSpec.revision if request.problem.requirementSpec else None
        )
        # A legacy guide is not a compatible reference for a newly versioned
        # brief. Both may be unversioned during the compatibility rollout.
        if data.get("requirementRevision") != requested_revision:
            return []
        return compare_walkthrough_structure(request, data)
    except Exception:
        logger.warning("Reference checks unavailable; retaining unscored fallback", exc_info=True)
        return []
