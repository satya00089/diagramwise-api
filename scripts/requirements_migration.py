"""Public-catalog export, editorial audit, and guarded additive migration.

Local input is the default. AWS is contacted only by export --remote-read or
apply/rollback --apply --approved. No app imports, dotenv loading, or cache writes.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
READ_ROOTS = (ROOT, ROOT.parent, Path(tempfile.gettempdir()).resolve())
WRITE_ROOTS = (ROOT, Path(tempfile.gettempdir()).resolve())
DYNAMODB_DECIMAL_KEY = "$dynamodbDecimal"


PUBLIC_FIELDS = (
    "id", "slug", "title", "description", "requirements", "constraints",
    "requirementSpec", "requirementSpecProvenance", "difficulty", "category",
    "domain", "estimatedTime", "estimated_time", "has_guided_walkthrough",
    "hints", "tags", "companies", "createdAt", "updatedAt",
)
GUARD_FIELDS = (
    "id", "slug", "title", "description", "requirements", "constraints",
    "requirementSpec", "requirementSpecProvenance", "has_guided_walkthrough",
)
WRITE_FIELDS = ("requirementSpec", "requirementSpecProvenance")
CACHE_NOTE = {
    "catalogPages": "Version diagrammatic:problem-catalog:page:v1 for the release (TTL 86400s).",
    "counts": "Counts do not change; preserve diagrammatic:problem-catalog:count:v1.",
    "walkthroughs": "Version only changed problem walkthrough/session caches when publishing a new guide.",
    "static": "Publish the matching reviewed static requirement projection and guide revision.",
    "rollback": "Restore matching static projection/cache release version; no global FLUSHDB.",
}


class MigrationError(ValueError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return {DYNAMODB_DECIMAL_KEY: str(value)}
    raise TypeError(f"Unsupported public value: {type(value).__name__}")


def _json_hook(value: dict) -> Any:
    return Decimal(value[DYNAMODB_DECIMAL_KEY]) if set(value) == {DYNAMODB_DECIMAL_KEY} else value


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      default=_json_default, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _validated_local_path(path: str | Path, *, writing: bool = False) -> Path:
    """Resolve local CLI paths and reject traversal through or around symlinks."""
    candidate = Path(path).expanduser().resolve()
    roots = WRITE_ROOTS if writing else READ_ROOTS
    if not any(candidate == root or root in candidate.parents for root in roots):
        access = "write" if writing else "read"
        raise MigrationError(f"Refusing to {access} outside approved local directories: {path}")
    return candidate


def read_json(path: str | Path) -> Any:
    safe_path = _validated_local_path(path)
    return json.loads(safe_path.read_text(encoding="utf-8-sig"), object_hook=_json_hook)


def write_json(path: str | Path, value: Any, *, replace: bool = False) -> None:
    """Keep reports local and refuse accidental overwrites; journal refresh is atomic."""
    target = _validated_local_path(path, writing=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, indent=2, ensure_ascii=False, default=_json_default,
                         allow_nan=False) + "\n"
    if not replace:
        with target.open("x", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    else:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         delete=False, suffix=".tmp") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            temporary = Path(stream.name)
        temporary.replace(target)


def records(payload: Any) -> list[dict]:
    """Accept the parent's plain snapshot or an AWS CLI typed Items/Item envelope."""
    values = payload if isinstance(payload, list) else payload.get("records", payload.get("Items"))
    if values is None and isinstance(payload, dict) and "Item" in payload:
        values = [payload["Item"]]
    if not isinstance(values, list):
        raise MigrationError("Expected a public records list, snapshot, or AWS Items envelope")
    if values and isinstance(values[0].get("id"), dict):
        from boto3.dynamodb.types import TypeDeserializer
        deserializer = TypeDeserializer()
        values = [{key: deserializer.deserialize(value) for key, value in item.items()}
                  for item in values]
    return values


def scan_public(table: Any) -> list[dict]:
    names = {f"#p{i}": field for i, field in enumerate(PUBLIC_FIELDS)}
    kwargs: dict = {"ProjectionExpression": ", ".join(names),
                    "ExpressionAttributeNames": names, "ConsistentRead": True}
    result = []
    seen = set()
    while True:
        page = table.scan(**kwargs)
        result.extend(page.get("Items", []))
        cursor = page.get("LastEvaluatedKey")
        if not cursor:
            return result
        token = canonical(cursor)
        if token in seen:
            raise MigrationError("Repeated scan cursor; incomplete export refused")
        seen.add(token)
        kwargs["ExclusiveStartKey"] = cursor


def export_snapshot(items: list[dict], source: dict | None = None) -> dict:
    public = [{key: deepcopy(item[key]) for key in PUBLIC_FIELDS if key in item} for item in items]
    ids = [item.get("id") for item in public]
    if any(not isinstance(key, str) or not key for key in ids) or len(ids) != len(set(ids)):
        raise MigrationError("Missing or duplicate problem IDs in snapshot")
    public.sort(key=lambda item: item["id"])
    return {"formatVersion": 1, "kind": "public-problem-snapshot", "exportedAt": now(),
            "source": source or {"kind": "local"}, "records": public,
            "recordCount": len(public), "recordsHash": digest(public),
            "note": "Public catalog only. Scan is paginated, not a point-in-time transaction; apply rechecks fields."}


def attribute_state(item: dict, field: str) -> dict:
    return {"exists": True, "value": deepcopy(item[field])} if field in item else {"exists": False}


def source_rows(item: dict) -> list[dict]:
    rows = []
    for field in ("requirements", "constraints"):
        entries = item.get(field, [])
        if not isinstance(entries, list):
            raise MigrationError(f"{item.get('id')}: {field} must be a list")
        for index, entry in enumerate(entries):
            text = entry.get("text") if isinstance(entry, dict) else entry
            scope = entry.get("scope") if isinstance(entry, dict) else None
            if not isinstance(text, str) or not text.strip() or scope not in (None, "core", "extension"):
                raise MigrationError(f"{item.get('id')}: invalid {field}[{index}]")
            rows.append({"sourceAttribute": field, "sourceIndex": index, "text": text,
                         "originalScope": scope})
    return rows


def classify(text: str) -> tuple[str, str | None]:
    # Suggestions only. Every row requires explicit editorial review.
    patterns = {
        "scale": r"\b(scale|scalab|million|billion|\d+[mbk]\b|throughput|per (day|second)|dau|read.heavy)",
        "latency": r"\b(latency|\d+\s*ms|response time)",
        "availability": r"\b(availability|uptime|99\.\d|highly available)",
        "consistency": r"\b(consisten|unique|idempoten|exactly.once)",
        "security": r"\b(encrypt|secur|authentication|authorization)",
        "durability": r"\b(durab|backup|data loss)",
    }
    for category, pattern in patterns.items():
        if re.search(pattern, text, re.IGNORECASE):
            return "nonFunctional", category
    return "functional", None


def _draft_change(item: dict, revision: str | None) -> dict:
    original = {key: attribute_state(item, key) for key in GUARD_FIELDS}
    prior = item.get("requirementSpec") or {}
    existing = {entry["text"]: (bucket, entry) for bucket in ("functional", "nonFunctional")
                for entry in prior.get(bucket, [])}
    spec = {"schemaVersion": 1, "revision": revision or f"catalog-v1-{digest(original)[:12]}",
            "functional": [], "nonFunctional": [], "assumptions": deepcopy(prior.get("assumptions", []))}
    provenance = []
    for row in source_rows(item):
        bucket, category = classify(row["text"])
        if row["sourceAttribute"] == "constraints":
            bucket, category = "constraint", None
        previous_bucket, previous = existing.get(row["text"], (None, {}))
        bucket = previous_bucket or bucket
        req_id = previous.get("id") or "req-" + digest([item["id"], row])[:16]
        scope = row["originalScope"] or previous.get("scope") or "core"
        entry = {"id": req_id, "text": row["text"], "scope": scope}
        category = previous.get("category") or category
        if category:
            entry["category"] = category
        if bucket != "constraint":
            spec[bucket].append(entry)
        provenance.append({**row, "id": req_id, "classification": bucket, "scope": scope,
                           "category": category, "status": "needs_review",
                           "reviewer": None, "reason": "Heuristic suggestion; original exercise scope requires review."})
    return {"id": item["id"], "slug": item.get("slug"),
            "baseRevision": prior.get("revision"), "original": original,
            "sourceHash": digest(original), "proposedSpec": spec,
            "provenance": provenance,
            "review": {"status": "needs_review", "reviewer": None}}


def make_draft(snapshot: dict, revision: str | None = None) -> dict:
    items = records(snapshot)
    if snapshot.get("recordsHash") != digest(items):
        raise MigrationError("Snapshot records hash mismatch")
    changes = [_draft_change(item, revision) for item in items]
    return {"formatVersion": 1, "kind": "requirement-migration-manifest", "createdAt": now(),
            "source": deepcopy(snapshot["source"]), "snapshotHash": snapshot["recordsHash"],
            "changes": changes, "approved": False,
            "readerCompatibility": {"status": "unverified", "schemaVersions": [],
                                    "deployment": None, "evidence": None},
            "cachePlan": {"reviewed": False, "releaseVersion": None, "notes": CACHE_NOTE},
            "catalogReconciliation": {"job-scheduler": {"status": "unresolved_alias",
                "note": "Static-only slug; reviewer must resolve relationship to live scheduler. No ID/slug creation."}}}


def audit_catalog(snapshot: dict, guide_dir: Path) -> dict:
    guide_dir = _validated_local_path(guide_dir)
    if not guide_dir.is_dir():
        raise MigrationError(f"Guide directory does not exist: {guide_dir}")
    items = records(snapshot)
    if snapshot.get("recordsHash") != digest(items):
        raise MigrationError("Snapshot hash mismatch")
    guides = {path.stem: read_json(path) for path in sorted(guide_dir.glob("*.json"))}
    live: dict[str, list[str]] = {}
    matrix = []
    for item in items:
        slug = item.get("slug")
        if slug:
            live.setdefault(slug, []).append(item["id"])
        guide = guides.get(slug, {})
        public_requirements = guide.get("requirements", {})
        live_texts = [row["text"] for row in source_rows(item)]
        guide_texts = [text for bucket in ("functional", "nonFunctional")
                       for text in public_requirements.get(bucket, [])]
        differences = [text for text in guide_texts if text not in live_texts]
        matrix.append({"id": item["id"], "slug": slug,
                       "activeRevision": (item.get("requirementSpec") or {}).get("revision"),
                       "originalRequirements": deepcopy(item.get("requirements", [])),
                       "originalConstraints": deepcopy(item.get("constraints", [])),
                       "guideRequirementsDifferingFromLive": differences,
                       "referenceAssumptions": deepcopy(guide.get("assumptions", [])),
                       "status": "needs_review", "requirementEvidenceMapping": [],
                       "editorialDecisions": ["Review classifications, scope, provided targets, and guide/walkthrough conflicts."],
                       "note": "Differences are editorial leads, not automatic contradictions or authorized requirements."})
    static_only = sorted(set(guides) - set(live))
    return {"formatVersion": 1, "kind": "read-only-requirement-audit", "snapshotHash": digest(items),
            "liveCount": len(items), "staticCount": len(guides),
            "observedPlanCounts": {"live": 145, "static": 146},
            "matchesPlanCounts": len(items) == 145 and len(guides) == 146,
            "liveOnlySlugs": sorted(set(live) - set(guides)), "staticOnlySlugs": static_only,
            "missingSlugs": [item["id"] for item in items if not item.get("slug")],
            "duplicateSlugs": {slug: ids for slug, ids in live.items() if len(ids) > 1},
            "aliases": [{"slug": slug, "status": "unresolved_alias" if slug == "job-scheduler" else "needs_review"}
                        for slug in static_only], "matrix": matrix}


def _validate_spec_header(spec: dict) -> list[str]:
    errors = []
    if set(spec) != {"schemaVersion", "revision", "functional", "nonFunctional", "assumptions"}:
        errors.append("requirementSpec has missing or unexpected fields")
    if type(spec.get("schemaVersion")) not in (int, Decimal) or spec.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")
    if not isinstance(spec.get("revision"), str) or not spec["revision"].strip():
        errors.append("revision must be a nonempty string")
    return errors


def _validate_requirement_row(row: dict) -> list[str]:
    errors = []
    if set(row) - {"id", "text", "scope", "category"}:
        errors.append("Unexpected requirement fields")
    if not all(isinstance(row.get(field), str) and row[field].strip() for field in ("id", "text")):
        errors.append("Requirement id/text must be nonempty strings")
    if row.get("scope") not in ("core", "extension"):
        errors.append("Invalid requirement scope")
    if "category" in row and row["category"] is not None and not isinstance(row["category"], str):
        errors.append("category must be a string or null")
    return errors


def validate_spec(spec: dict) -> list[str]:
    if not isinstance(spec, dict):
        return ["requirementSpec must be an object"]
    errors = _validate_spec_header(spec)
    ids = []
    for bucket in ("functional", "nonFunctional"):
        rows = spec.get(bucket)
        if not isinstance(rows, list):
            errors.append(f"{bucket} must be a list")
            continue
        for row in rows:
            if not isinstance(row, dict):
                errors.append("requirement must be an object")
                continue
            errors.extend(_validate_requirement_row(row))
            ids.append(row.get("id"))
    if len(ids) != len(set(map(str, ids))):
        errors.append("Duplicate requirement IDs")
    assumptions = spec.get("assumptions")
    if not isinstance(assumptions, list) or any(not isinstance(value, str) for value in assumptions):
        errors.append("assumptions must be a string list")
    return errors


def approval_digest(manifest: dict) -> str:
    return digest({key: value for key, value in manifest.items() if key not in ("approval", "approved")})


def _original_item(change: dict, prefix: str) -> tuple[dict | None, list[str]]:
    original = change.get("original", {})
    if set(original) != set(GUARD_FIELDS) or digest(original) != change.get("sourceHash"):
        return None, [prefix + "Invalid originals/source hash"]
    malformed = any(
        not isinstance(state, dict)
        or type(state.get("exists")) is not bool
        or set(state) != ({"exists", "value"} if state.get("exists") else {"exists"})
        for state in original.values()
    )
    if malformed:
        return None, [prefix + "Malformed original attribute states"]
    return (
        {field: state["value"] for field, state in original.items() if state["exists"]},
        [],
    )


def _validate_provenance_source(row: dict, source: dict, prior_entries: dict, prefix: str) -> list[str]:
    errors = []
    if any(row.get(key) != value for key, value in source.items()):
        errors.append(prefix + "Original sentence/source/scope altered")
    if source["originalScope"] is not None and row.get("scope") != source["originalScope"]:
        errors.append(prefix + "Explicit original scope altered")
    if source["text"] in prior_entries:
        previous = prior_entries[source["text"]]
        if row.get("id") != previous["id"] or row.get("scope") != previous["scope"]:
            errors.append(prefix + "Existing requirement ID/scope altered")
    return errors


def _validated_classification(row: dict, prefix: str) -> tuple[list[str], str | None, dict | None]:
    errors = []
    bucket = row.get("classification")
    if bucket not in ("functional", "nonFunctional", "constraint") or row.get("scope") not in ("core", "extension"):
        errors.append(prefix + "Invalid classification/scope")
        bucket = None
    if bucket == "constraint" and row.get("sourceAttribute") != "constraints":
        errors.append(prefix + "Legacy requirement omitted from specification")
    entry = None
    if bucket in ("functional", "nonFunctional"):
        entry = {key: row.get(key) for key in ("id", "text", "scope")}
        if row.get("category"):
            entry["category"] = row["category"]
    return errors, bucket, entry


def _validate_review_status(row: dict, publish: bool, prefix: str) -> list[str]:
    if publish and (row.get("status") != "reviewed" or not row.get("reviewer") or not row.get("reason")):
        return [prefix + "Unreviewed/ambiguous sentence blocks publishing"]
    return []


def _validate_provenance_row(
    row: dict,
    source: dict,
    prior_entries: dict,
    *,
    publish: bool,
    prefix: str,
) -> tuple[list[str], str | None, dict | None]:
    errors = _validate_provenance_source(row, source, prior_entries, prefix)
    classification_errors, bucket, entry = _validated_classification(row, prefix)
    errors.extend(classification_errors)
    errors.extend(_validate_review_status(row, publish, prefix))
    return errors, bucket, entry


def _project_provenance(
    provenance: list[dict],
    expected_rows: list[dict],
    prior: dict,
    *,
    publish: bool,
    prefix: str,
) -> tuple[dict[str, list[dict]], list[str]]:
    projected: dict[str, list[dict]] = {"functional": [], "nonFunctional": []}
    prior_entries = {entry["text"]: entry for bucket in projected for entry in prior.get(bucket, [])}
    errors = []
    for row, source in zip(provenance, expected_rows):
        if not isinstance(row, dict):
            errors.append(prefix + "Malformed provenance row")
            continue
        row_errors, bucket, entry = _validate_provenance_row(
            row, source, prior_entries, publish=publish, prefix=prefix
        )
        errors.extend(row_errors)
        if entry is not None and bucket in projected:
            projected[bucket].append(entry)
    return projected, errors


def _validate_change(change: dict, *, publish: bool) -> list[str]:
    prefix = str(change.get("id")) + ": "
    item, errors = _original_item(change, prefix)
    if item is None:
        return errors
    if item.get("id") != change.get("id") or item.get("slug") != change.get("slug"):
        errors.append(prefix + "Identity/slug changed")
    prior = item.get("requirementSpec") or {}
    if prior.get("revision") != change.get("baseRevision"):
        errors.append(prefix + "Active base revision mismatch")

    spec = change.get("proposedSpec", {})
    spec_errors = validate_spec(spec)
    errors.extend(prefix + error for error in spec_errors)
    if spec_errors:
        return errors
    if spec["revision"] == change.get("baseRevision"):
        errors.append(prefix + "New content requires a new revision")
    if spec["assumptions"] != prior.get("assumptions", []):
        errors.append(prefix + "Assumptions changed; scope-changing editorial revisions need separate review")
    try:
        expected_rows = source_rows(item)
    except MigrationError as error:
        errors.append(str(error))
        return errors
    provenance = change.get("provenance", [])
    if len(provenance) != len(expected_rows):
        errors.append(prefix + "Original sentences omitted or duplicated")
        return errors
    projected, provenance_errors = _project_provenance(
        provenance, expected_rows, prior, publish=publish, prefix=prefix
    )
    errors.extend(provenance_errors)
    if any(spec[bucket] != projected[bucket] for bucket in projected):
        errors.append(prefix + "Spec differs from preserved source/provenance; guide imports are prohibited")
    prior_ids = {entry["id"] for bucket in projected for entry in prior.get(bucket, [])}
    new_ids = {entry["id"] for bucket in projected for entry in spec[bucket]}
    if not prior_ids <= new_ids:
        errors.append(prefix + "Existing spec requirements would be lost")
    if publish and (change.get("review", {}).get("status") != "reviewed" or not change.get("review", {}).get("reviewer")):
        errors.append(prefix + "Problem review required")
    return errors


def _validate_publish_gates(manifest: dict) -> list[str]:
    errors = []
    gate = manifest.get("readerCompatibility", {})
    if gate.get("status") != "verified" or 1 not in gate.get("schemaVersions", []) or not gate.get("deployment") or not gate.get("evidence"):
        errors.append("Deployed forward-reader compatibility evidence required")
    cache = manifest.get("cachePlan", {})
    if cache.get("reviewed") is not True or not cache.get("releaseVersion") or not cache.get("notes"):
        errors.append("Reviewed targeted cache/static release plan required")
    return errors


def validation_errors(manifest: dict, *, publish: bool = False) -> list[str]:
    if manifest.get("formatVersion") != 1 or manifest.get("kind") != "requirement-migration-manifest":
        return ["Unsupported manifest format"]
    changes = manifest.get("changes", [])
    if not isinstance(changes, list) or not changes:
        return ["Manifest must contain changes"]
    ids = [row.get("id") for row in changes]
    errors = ["Duplicate manifest IDs"] if len(ids) != len(set(map(str, ids))) else []
    for change in changes:
        errors.extend(_validate_change(change, publish=publish))
    if publish:
        errors.extend(_validate_publish_gates(manifest))
    return errors


def require_approval(manifest: dict) -> None:
    errors = validation_errors(manifest, publish=True)
    approval = manifest.get("approval", {})
    if manifest.get("approved") is not True or not approval.get("reviewer") or approval.get("digest") != approval_digest(manifest):
        errors.append("Explicit approved manifest missing or changed after approval")
    if errors:
        raise MigrationError("; ".join(errors))


def new_attributes(change: dict) -> dict:
    return {"requirementSpec": {"exists": True, "value": deepcopy(change["proposedSpec"])},
            "requirementSpecProvenance": {"exists": True, "value": {
                "revision": change["proposedSpec"]["revision"], "sourceHash": change["sourceHash"],
                "classification": deepcopy(change["provenance"]), "review": deepcopy(change["review"])}}}


def dry_run(manifest: dict) -> dict:
    errors = validation_errors(manifest)
    if errors:
        raise MigrationError("; ".join(errors))
    return {"kind": "requirement-dry-run", "remoteWrites": False,
            "publishBlockers": validation_errors(manifest, publish=True),
            "emptyRequirementGroups": [{"id": row["id"], "groups": [bucket for bucket in ("functional", "nonFunctional")
                                        if not row["proposedSpec"][bucket]]}
                                       for row in manifest["changes"]
                                       if any(not row["proposedSpec"][bucket] for bucket in ("functional", "nonFunctional"))],
            "changes": [{"id": row["id"], "slug": row["slug"],
                         "baseRevision": row["baseRevision"],
                         "before": {key: row["original"][key] for key in WRITE_FIELDS},
                         "after": new_attributes(row)} for row in manifest["changes"]]}


def assert_current(item: dict | None, states: dict, problem_id: str) -> None:
    if item is None or item.get("id") != problem_id:
        raise MigrationError(f"{problem_id}: item missing; refusing upsert")
    changed = [field for field, state in states.items() if attribute_state(item, field) != state]
    if changed:
        raise MigrationError(f"{problem_id}: concurrent edit/active revision conflict: {', '.join(changed)}")


def conditional_update(table: Any, problem_id: str, expected: dict, replacement: dict) -> None:
    """Only named approved attributes are set/removed; conditions cover source + current revision."""
    if set(replacement) != set(WRITE_FIELDS):
        raise MigrationError("Unapproved write attributes")
    names, values, conditions, sets, removes = {}, {}, [], [], []
    for index, (field, state) in enumerate(expected.items()):
        name = f"#g{index}"
        names[name] = field
        if state["exists"]:
            value = f":g{index}"
            values[value] = state["value"]
            conditions.append(f"{name} = {value}")
        else:
            conditions.append(f"attribute_not_exists({name})")
    for index, (field, state) in enumerate(replacement.items()):
        name = f"#w{index}"
        names[name] = field
        if state["exists"]:
            value = f":w{index}"
            values[value] = state["value"]
            sets.append(f"{name} = {value}")
        else:
            removes.append(name)
    expression = ("SET " + ", ".join(sets) if sets else "")
    expression += (" REMOVE " + ", ".join(removes) if removes else "")
    table.update_item(Key={"id": problem_id}, UpdateExpression=expression.strip(),
                      ConditionExpression=" AND ".join(conditions),
                      ExpressionAttributeNames=names, ExpressionAttributeValues=values)


def apply_manifest(table: Any, manifest: dict, *, apply: bool = False,
                   save_journal: Callable[[dict], None] | None = None) -> dict:
    if not apply:
        return dry_run(manifest)
    require_approval(manifest)
    if save_journal is None:
        raise MigrationError("Durable local journal required before remote writes")
    # Preflight every record before the first write; conditions close the race afterwards.
    for change in manifest["changes"]:
        current = table.get_item(Key={"id": change["id"]}, ConsistentRead=True).get("Item")
        assert_current(current, change["original"], change["id"])
        candidate = deepcopy(current)
        candidate.update({key: state["value"] for key, state in new_attributes(change).items()})
        if len(canonical(candidate).encode("utf-8")) > 350_000:
            raise MigrationError(f"{change['id']}: conservative item-size budget exceeded")
    journal = {"formatVersion": 1, "kind": "requirement-rollback-journal", "createdAt": now(),
               "manifestDigest": approval_digest(manifest), "source": manifest["source"],
               "cachePlan": manifest["cachePlan"], "entries": [], "status": "in_progress"}
    save_journal(deepcopy(journal))
    for change in manifest["changes"]:
        entry = {"id": change["id"], "original": deepcopy(change["original"]),
                 "written": new_attributes(change), "status": "pending"}
        journal["entries"].append(entry)
        save_journal(deepcopy(journal))
        try:
            conditional_update(table, change["id"], entry["original"], entry["written"])
            entry["status"] = "applied"
            save_journal(deepcopy(journal))
            current = table.get_item(Key={"id": change["id"]}, ConsistentRead=True).get("Item")
            assert_current(current, {**entry["original"], **entry["written"]}, change["id"])
            entry["status"] = "verified"
            save_journal(deepcopy(journal))
        except Exception as error:
            entry["error"] = type(error).__name__ + ": " + str(error)
            journal["status"] = "stopped"
            save_journal(deepcopy(journal))
            raise MigrationError(f"Apply stopped at {change['id']}; inspect journal, no automatic retry: {error}") from error
    journal["status"] = "verified"
    save_journal(deepcopy(journal))
    return journal


def _validate_rollback_journal(manifest: dict, journal: dict) -> None:
    if journal.get("kind") != "requirement-rollback-journal" or journal.get("manifestDigest") != approval_digest(manifest) or journal.get("source") != manifest["source"]:
        raise MigrationError("Rollback journal does not match approved manifest")
    approved = {row["id"]: row for row in manifest["changes"]}
    entries = journal.get("entries", [])
    if len({row["id"] for row in entries}) != len(entries):
        raise MigrationError("Duplicate journal IDs")
    for entry in entries:
        change = approved.get(entry["id"])
        if not change or entry["original"] != change["original"] or entry["written"] != new_attributes(change):
            raise MigrationError("Tampered rollback originals/current values")


def _entry_is_already_restored(entry: dict, current: dict | None) -> bool:
    return (
        entry["status"] in ("pending", "rolled_back")
        and current is not None
        and all(attribute_state(current, key) == state for key, state in entry["original"].items())
    )


def _restore_rollback_entry(
    table: Any,
    entry: dict,
    result: dict,
    save_journal: Callable[[dict], None],
) -> None:
    expected = {**entry["original"], **entry["written"]}
    current = table.get_item(Key={"id": entry["id"]}, ConsistentRead=True).get("Item")
    # Pending may represent a failed request or a write whose acknowledgement was lost.
    if _entry_is_already_restored(entry, current):
        entry["status"] = "rolled_back"
        save_journal(deepcopy(result))
        return
    assert_current(current, expected, entry["id"])
    try:
        conditional_update(
            table,
            entry["id"],
            expected,
            {key: entry["original"][key] for key in WRITE_FIELDS},
        )
        current = table.get_item(Key={"id": entry["id"]}, ConsistentRead=True).get("Item")
        assert_current(current, entry["original"], entry["id"])
        entry["status"] = "rolled_back"
        save_journal(deepcopy(result))
    except Exception as error:
        result["status"] = "rollback_stopped"
        entry["rollbackError"] = str(error)
        save_journal(deepcopy(result))
        raise MigrationError(f"Rollback conflict/failure at {entry['id']}: {error}") from error


def rollback_manifest(table: Any, manifest: dict, journal: dict, *, apply: bool = False,
                      save_journal: Callable[[dict], None] | None = None) -> dict:
    require_approval(manifest)
    _validate_rollback_journal(manifest, journal)
    result = deepcopy(journal)
    if not apply:
        return {"kind": "requirement-rollback-dry-run", "remoteWrites": False,
                "changes": [{"id": row["id"], "expected": row["written"],
                             "restore": {key: row["original"][key] for key in WRITE_FIELDS}}
                            for row in entries]}
    if save_journal is None:
        raise MigrationError("Durable rollback journal required")
    for entry in reversed(result["entries"]):
        _restore_rollback_entry(table, entry, result, save_journal)
    result["status"] = "rolled_back"
    save_journal(deepcopy(result))
    return result


def aws_table(source: dict, profile: str | None) -> Any:
    import boto3
    if not source.get("table") or not source.get("region"):
        raise MigrationError("Manifest needs an explicit public table and region before AWS access")
    if "problem" not in source["table"] or any(word in source["table"] for word in ("attempt", "user", "diagram")) and source["table"] != "diagrammatic_problems":
        raise MigrationError("Only an explicitly named public problems table is supported")
    return boto3.Session(profile_name=profile, region_name=source["region"]).resource("dynamodb").Table(source["table"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("--input", type=Path)
    export.add_argument("--remote-read", action="store_true")
    export.add_argument("--table", default="diagrammatic_problems")
    export.add_argument("--region", default="ap-south-1")
    export.add_argument("--profile")
    export.add_argument("--output", type=Path, required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("--snapshot", type=Path, required=True)
    audit.add_argument("--guide-dir", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)
    draft = sub.add_parser("draft")
    draft.add_argument("--snapshot", type=Path, required=True)
    draft.add_argument("--revision")
    draft.add_argument("--output", type=Path, required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--publish", action="store_true")
    validate.add_argument("--approve-by")
    validate.add_argument("--output", type=Path)
    for name in ("apply", "rollback"):
        command = sub.add_parser(name)
        command.add_argument("--manifest", type=Path)
        command.add_argument("--approved", type=Path)
        command.add_argument("--apply", action="store_true")
        command.add_argument("--profile")
        command.add_argument("--journal", type=Path)
        command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output is not None:
            args.output = _validated_local_path(args.output, writing=True)
        for name in ("input", "snapshot", "manifest", "approved", "journal"):
            value = getattr(args, name, None)
            if value is not None:
                setattr(args, name, _validated_local_path(value))
        if getattr(args, "guide_dir", None) is not None:
            args.guide_dir = _validated_local_path(args.guide_dir)
        if args.command == "export":
            if args.remote_read == bool(args.input):
                parser.error("export needs exactly one of --input or explicit --remote-read")
            source = {"kind": "aws-public-catalog" if args.remote_read else "local-public-snapshot",
                      "table": args.table, "region": args.region}
            if args.input:
                source["inputHash"] = digest(read_json(args.input))
            items = scan_public(aws_table(source, args.profile)) if args.remote_read else records(read_json(args.input))
            result = export_snapshot(items, source)
        elif args.command == "audit":
            result = audit_catalog(read_json(args.snapshot), args.guide_dir)
        elif args.command == "draft":
            result = make_draft(read_json(args.snapshot), args.revision)
        elif args.command == "validate":
            manifest = read_json(args.manifest)
            errors = validation_errors(manifest, publish=args.publish or bool(args.approve_by))
            result = {"valid": not errors, "errors": errors,
                      "diff": None if errors else dry_run(manifest)}
            if args.approve_by:
                if errors or not args.output:
                    raise MigrationError("Approval requires passing publish checks and a new --output path")
                manifest["approved"] = True
                manifest["approval"] = {"reviewer": args.approve_by, "approvedAt": now(),
                                        "digest": approval_digest(manifest)}
                result = manifest
            if args.output:
                write_json(args.output, result)
            print(json.dumps({"valid": not errors, "errors": errors, "output": str(args.output)}, indent=2))
            return 1 if errors else 0
        else:
            if args.apply and not args.approved:
                parser.error("Remote mutation requires both --apply and --approved MANIFEST")
            path = args.approved or args.manifest
            if not path:
                parser.error("Provide --manifest for local dry run or --approved for reviewed apply")
            manifest = read_json(path)
            if args.apply:
                require_approval(manifest)  # Gate before SDK initialization/credential lookup.
                if not args.journal or args.journal.resolve() == args.output.resolve():
                    parser.error("Use separate --journal and --output paths")
                if args.output.exists() or (args.command == "apply" and args.journal.exists()):
                    raise MigrationError("Output/journal already exists; refusing to overwrite")
            if args.command == "apply":
                initialized = False
                def save(value: dict) -> None:
                    nonlocal initialized
                    write_json(args.journal, value, replace=initialized)
                    initialized = True
                result = apply_manifest(aws_table(manifest["source"], args.profile) if args.apply else None,
                                        manifest, apply=args.apply, save_journal=save if args.apply else None)
            else:
                if not args.journal:
                    parser.error("rollback requires the original --journal")
                result = rollback_manifest(aws_table(manifest["source"], args.profile) if args.apply else None,
                                           manifest, read_json(args.journal), apply=args.apply,
                                           save_journal=lambda value: write_json(args.journal, value, replace=True))
        write_json(args.output, result)
        print(json.dumps({"command": args.command, "output": str(args.output),
                          "remoteMutation": bool(getattr(args, "apply", False))}))
        return 0
    except (MigrationError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
