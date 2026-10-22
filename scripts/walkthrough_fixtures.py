"""Pure replay of public walkthrough action payloads for local evaluation.

This is an apply-like oracle, not proof of frontend parity. The frontend's own
apply/save/reload tests establish that separately. Lesson content is never
serialized as a learner decision. Generated labels remain editorial drafts.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.requirements_migration import digest, read_json, records, validate_spec


SEMANTIC_TYPES = {
    "frontend", "backend", "database", "cache", "load-balancer", "api-gateway",
    "message-broker", "queue", "cdn", "monitoring", "analytics", "external-api",
    "storage", "security", "custom",
}
TYPE_ALIASES = {"object-storage": "storage"}
LAYOUT_FIELDS = {"position", "positionAbsolute", "width", "height", "selected", "dragging",
                 "measured", "icon", "iconUrl", "style", "className", "zIndex"}
COMPLETE_SUFFIX = ":complete"
SUPPORTED_NON_MUTATING_ACTIONS = {
    "explanation", "decision_point", "scale_trigger", "update_component",
    "record_decision", "implementation", "acceptance", "conclusion", "example",
}


class FixtureError(ValueError):
    pass


def semantic_properties(value: dict) -> dict:
    if not isinstance(value, dict):
        raise FixtureError("Component properties must be an object")
    return {key: deepcopy(item) for key, item in value.items() if key not in LAYOUT_FIELDS}


def _validated_walkthrough_steps(
    walkthrough: dict,
    applied_step_ids: list[str] | None,
) -> tuple[list[dict], set[str]]:
    if not walkthrough.get("problem_id") or not walkthrough.get("version"):
        raise FixtureError("A versioned public walkthrough with problem_id is required")
    steps = walkthrough.get("steps")
    if not isinstance(steps, list) or not steps:
        raise FixtureError("Walkthrough has no steps")
    ids = [step.get("id") for step in steps]
    if any(not isinstance(key, str) or not key for key in ids) or len(ids) != len(set(ids)):
        raise FixtureError("Missing or duplicate walkthrough step IDs")
    numbers = [step.get("stepNumber") for step in steps]
    if any(type(number) is not int for number in numbers) or len(numbers) != len(set(numbers)):
        raise FixtureError("Missing or duplicate step numbers")
    if walkthrough.get("totalSteps", len(steps)) != len(steps):
        raise FixtureError("Walkthrough totalSteps differs from actual steps")
    selected = set(ids if applied_step_ids is None else applied_step_ids)
    if selected - set(ids):
        raise FixtureError("Applied steps contain unknown IDs")
    return steps, selected


def _add_component(step: dict, nodes: dict[str, dict]) -> None:
    component = step.get("component")
    if not isinstance(component, dict) or not component.get("nodeId") or not component.get("label") or not component.get("componentType"):
        raise FixtureError(f"{step['id']}: invalid component action")
    node_id = component["nodeId"]
    if node_id in nodes:
        raise FixtureError(f"{step['id']}: duplicate component ID {node_id}")
    data = component.get("data") or {}
    properties = semantic_properties({**data.get("properties", {}), **component.get("properties", {})})
    catalog_id = data.get("originalComponentId") or data.get("catalogId") or component["componentType"]
    raw_role = component.get("semanticRole") or data.get("semanticRole") or component["componentType"]
    role = TYPE_ALIASES.get(raw_role, raw_role)
    semantic_type = role if role in SEMANTIC_TYPES else "custom"
    properties.update({"originalComponentId": catalog_id, "semanticRole": role})
    if component.get("description") and not properties.get("description") and not properties.get("purpose"):
        properties["purpose"] = component["description"]
    nodes[node_id] = {
        "id": node_id,
        "type": semantic_type,
        "label": component["label"],
        "properties": properties,
    }


def _add_connection(step: dict, nodes: dict[str, dict], edges: dict[str, dict]) -> None:
    connection = step.get("connection")
    if not isinstance(connection, dict) or not all(
        connection.get(field)
        for field in ("edgeId", "sourceNodeId", "targetNodeId", "connectionType")
    ):
        raise FixtureError(f"{step['id']}: invalid connection/protocol")
    if connection["edgeId"] in edges:
        raise FixtureError(f"{step['id']}: duplicate edge ID")
    if connection["sourceNodeId"] not in nodes or connection["targetNodeId"] not in nodes:
        raise FixtureError(
            f"{step['id']}: broken reference edge {connection['edgeId']} "
            f"({connection['sourceNodeId']} -> {connection['targetNodeId']})"
        )
    edges[connection["edgeId"]] = {
        "id": connection["edgeId"],
        "source": connection["sourceNodeId"],
        "target": connection["targetNodeId"],
        "type": connection["connectionType"],
        "label": connection.get("label"),
        "description": connection.get("description") or connection.get("purpose"),
    }


def _apply_component_update(step: dict, nodes: dict[str, dict]) -> bool:
    update = step.get("componentUpdate")
    if step.get("type") == "update_component" and not update:
        raise FixtureError(f"{step['id']}: update_component requires componentUpdate")
    if not update:
        return False
    if not isinstance(update, dict) or update.get("nodeId") not in nodes:
        raise FixtureError(f"{step['id']}: componentUpdate references an absent node")
    nodes[update["nodeId"]]["properties"].update(semantic_properties(update.get("properties", {})))
    return True


def _apply_decision(
    step: dict,
    applied_step_ids: list[str] | None,
    decisions: list[dict],
) -> bool:
    kind = step.get("type")
    if kind not in ("decision_point", "record_decision"):
        return False
    if not (step.get("componentUpdate") or kind == "record_decision"):
        return False
    decision = step.get("decision") or {}
    if not decision.get("chosen"):
        raise FixtureError(f"{step['id']}: applied decision has no chosen value")
    decisions.append({
        "stepId": step["id"],
        "question": decision.get("question", ""),
        "chosen": decision["chosen"],
        "reason": decision.get("chosenReason", ""),
        "origin": "synthetic-accepted-action" if applied_step_ids is None else "accepted-action",
    })
    return True


def _apply_walkthrough_step(
    step: dict,
    nodes: dict[str, dict],
    edges: dict[str, dict],
    applied_step_ids: list[str] | None,
    decisions: list[dict],
) -> bool:
    kind = step.get("type")
    acted = False
    if kind == "add_component":
        _add_component(step, nodes)
        acted = True
    elif kind == "add_connection":
        _add_connection(step, nodes, edges)
        acted = True
    elif kind not in SUPPORTED_NON_MUTATING_ACTIONS:
        raise FixtureError(f"{step['id']}: unsupported action {kind}")
    acted = _apply_component_update(step, nodes) or acted
    acted = _apply_decision(step, applied_step_ids, decisions) or acted
    return acted


def build_architecture(walkthrough: dict, *, applied_step_ids: list[str] | None = None) -> dict:
    """Replay explicit accepted actions in step order. None simulates accepting all actions."""
    steps, selected = _validated_walkthrough_steps(walkthrough, applied_step_ids)
    nodes: dict[str, dict] = {}
    edges: dict[str, dict] = {}
    decisions = []
    applied = []
    explanation_only = []
    for step in sorted(steps, key=lambda row: row["stepNumber"]):
        if step["id"] not in selected:
            continue
        acted = _apply_walkthrough_step(step, nodes, edges, applied_step_ids, decisions)
        if acted:
            applied.append(step["id"])
        else:
            explanation_only.append(step["id"])
    if not nodes:
        raise FixtureError("Applied fixture contains no components")
    # Final integrity remains necessary for externally supplied alternative payloads.
    architecture = {"components": list(nodes.values()), "connections": list(edges.values())}
    validate_architecture(architecture)
    return {"architecture": architecture, "acceptedDecisions": decisions,
            "appliedStepIds": applied, "explanationOnlyStepIds": explanation_only,
            "provenance": {"problemId": walkthrough["problem_id"], "walkthroughVersion": walkthrough["version"],
                           "walkthroughHash": digest(walkthrough),
                           "application": "apply-like public payload replay; frontend parity tested separately",
                           "actions": "synthetic-all-actions" if applied_step_ids is None else "explicit-applied-steps"}}


def validate_architecture(architecture: dict) -> None:
    components, connections = architecture.get("components", []), architecture.get("connections", [])
    ids = [row.get("id") for row in components]
    if not ids or any(not isinstance(key, str) or not key for key in ids) or len(ids) != len(set(ids)):
        raise FixtureError("Invalid/duplicate component IDs")
    edge_ids = [row.get("id") for row in connections]
    if any(not key for key in edge_ids) or len(edge_ids) != len(set(edge_ids)):
        raise FixtureError("Invalid/duplicate connection IDs")
    for connection in connections:
        if connection.get("source") not in ids or connection.get("target") not in ids:
            raise FixtureError(f"Broken reference edge {connection.get('id')}")
        if not connection.get("type"):
            raise FixtureError(f"Missing semantic protocol {connection.get('id')}")


def make_request(problem: dict, walkthrough: dict, built: dict, spec: dict | None = None) -> dict:
    revision = walkthrough.get("requirementRevision")
    spec = spec or problem.get("requirementSpec")
    if revision and not spec:
        raise FixtureError("Walkthrough requirement revision needs a matching requirement spec")
    if spec:
        errors = validate_spec(spec)
        if errors or (revision and revision != spec["revision"]):
            raise FixtureError("Invalid/mismatched active requirement revision: " + "; ".join(errors))
        revision = spec["revision"]
    if not revision:
        revision = "legacy-" + digest([problem.get("requirements", []), problem.get("constraints", [])])[:16]
    context = {"id": problem["id"], "requirementRevision": revision, "title": problem["title"],
               "description": problem["description"], "difficulty": problem.get("difficulty"),
               "category": problem.get("category"), "requirements": "\n".join(problem.get("requirements", [])),
               "constraints": "\n".join(problem.get("constraints", []))}
    if spec:
        context["requirementSpec"] = deepcopy(spec)
    result = {**deepcopy(built["architecture"]), "problem": context}
    # Only accepted explicit choices, never complete lesson prose or generated expected labels.
    if built["acceptedDecisions"]:
        result["explanation"] = "\n".join(
            f"{row['question']} Choice: {row['chosen']}. Rationale: {row['reason']}"
            for row in built["acceptedDecisions"])
    return result


def draft_expectations(kind: str, spec: dict | None = None) -> dict:
    return {"labelStatus": "draft", "origin": "generated-not-human-truth", "reviewer": None,
            "minScore": 96 if kind != "negative" else None,
            "requiredCoreIds": [row["id"] for bucket in ("functional", "nonFunctional")
                                for row in (spec or {}).get(bucket, []) if row["scope"] == "core"],
            "requiredFindingTerms": [], "forbiddenFindingTerms": []}


def _complete_cases(
    guide_dir: Path,
    problems: dict,
    specs: dict,
    has_manifest: bool,
) -> tuple[list[dict], list[dict]]:
    cases, structures = [], []
    for path in sorted(guide_dir.glob("*.json")):
        if path.name == "problems.json":
            continue
        guide = read_json(path)
        problem_id = guide.get("problem_id")
        if problem_id not in problems:
            raise FixtureError(f"{path.name}: problem missing from public snapshot")
        built = build_architecture(guide)
        spec = specs.get(problem_id)
        request = make_request(problems[problem_id], guide, built, spec)
        case = {
            "id": problem_id + COMPLETE_SUFFIX,
            "kind": "complete",
            "request": request,
            "inputHash": digest(request),
            "provenance": {
                **built["provenance"],
                "requirementRevision": request["problem"]["requirementRevision"],
                "requirementHash": digest(request["problem"]),
                "requirementStatus": "draft" if has_manifest else "snapshot",
            },
            "expected": draft_expectations("complete", spec),
        }
        cases.append(case)
        structures.append({
            "problemId": problem_id,
            "walkthroughVersion": guide["version"],
            "components": len(request["components"]),
            "connections": len(request["connections"]),
            "appliedActions": len(built["appliedStepIds"]),
            "explanationOnlySteps": len(built["explanationOnlyStepIds"]),
            "brokenEdges": [],
        })
    return cases, structures


def _negative_case(case: dict) -> dict:
    request = deepcopy(case["request"])
    removed = request["components"].pop(0)
    request["connections"] = [
        row for row in request["connections"]
        if removed["id"] not in (row["source"], row["target"])
    ]
    if not request["components"]:
        raise FixtureError("Cannot derive a nonempty negative architecture")
    validate_architecture(request)
    expected = draft_expectations("negative")
    expected["requiredFindingTerms"] = [removed["label"]]
    expected["defect"] = {
        "kind": "missing_component",
        "removedComponent": removed,
        "note": "Draft defect: reviewer must confirm that this removal loses a core capability.",
    }
    return {
        **deepcopy(case),
        "id": case["id"].replace(COMPLETE_SUFFIX, ":negative"),
        "kind": "negative",
        "counterpart": case["id"],
        "request": request,
        "inputHash": digest(request),
        "expected": expected,
    }


def _generated_alternatives(complete: list[dict]) -> list[dict]:
    alternatives = []
    for index, base in enumerate(complete[:2]):
        request = deepcopy(base["request"])
        mapping = {row["id"]: f"alternative_{index}_{i}" for i, row in enumerate(request["components"])}
        for row in request["components"]:
            row["id"] = mapping[row["id"]]
            row.pop("position", None)
        for edge_index, row in enumerate(request["connections"]):
            row.update({
                "id": f"alternative_edge_{index}_{edge_index}",
                "source": mapping[row["source"]],
                "target": mapping[row["target"]],
            })
        validate_architecture(request)
        alternatives.append({
            **deepcopy(base),
            "id": base["id"].replace(COMPLETE_SUFFIX, ":alternative"),
            "kind": "alternative",
            "counterpart": base["id"],
            "request": request,
            "inputHash": digest(request),
            "expected": draft_expectations("alternative"),
            "transformation": "ID/geometry equivalence draft; replace with reviewed provider/design alternatives",
        })
    return alternatives


def _alternative_cases(complete: list[dict], alternative_dir: Path | None) -> list[dict]:
    if alternative_dir is None:
        return _generated_alternatives(complete)
    alternatives = []
    for path in sorted(alternative_dir.glob("*.json")):
        case = read_json(path)
        if case.get("kind") != "alternative" or not case.get("counterpart"):
            raise FixtureError("Alternatives need kind=alternative and a complete counterpart")
        validate_architecture(case["request"])
        base = next((row for row in complete if row["id"] == case["counterpart"]), None)
        if not base or case["request"].get("problem") != base["request"]["problem"]:
            raise FixtureError("Alternative must use its counterpart's frozen problem revision")
        case["inputHash"] = digest(case["request"])
        case.setdefault("provenance", deepcopy(base["provenance"]))
        case.setdefault("expected", draft_expectations("alternative"))
        alternatives.append(case)
    return alternatives


def prepare_bundle(fixture_dir: Path, walkthrough_dir: Path | None = None,
                   manifest: dict | None = None, alternative_dir: Path | None = None) -> dict:
    problems = {row["id"]: row for row in records(read_json(fixture_dir / "problems.json"))}
    guide_dir = walkthrough_dir or fixture_dir
    specs = {row["id"]: row["proposedSpec"] for row in (manifest or {}).get("changes", [])}
    cases, structures = _complete_cases(guide_dir, problems, specs, bool(manifest))
    complete = list(cases)
    cases.extend(_negative_case(case) for case in complete)
    cases.extend(_alternative_cases(complete, alternative_dir))
    return {"formatVersion": 1, "kind": "local-assessment-evaluation-bundle", "repeats": 5,
            "langfuseSdkBaseline": "4.15.2", "labelStatus": "draft",
            "fixtureScope": "public-reference-only", "structures": structures, "cases": cases,
            "note": "Structural preparation is not AI acceptance or deployed confirmation. No expected labels enter requests."}
