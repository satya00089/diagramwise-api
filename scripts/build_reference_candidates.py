"""Build reviewable reference candidates from public snapshots; never publish them.

Edits are authored design decisions, not assessment answers or score hints.
The original AWS fixtures are retained unchanged for audit and rollback.
"""

from __future__ import annotations

import json
import hashlib
import argparse
import os
import re
import secrets
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "tests/fixtures/walkthroughs"
OUTPUT = ROOT / "data/assessment-reference-candidates/walkthroughs"
DOCUMENT_ID = "6901ef1b9420d83630aca871"
SNAPSHOT_STEM_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
FIXTURE_PATH_ERROR = "Fixture paths must stay inside the API or frontend repository"


def requirement_id(problem: dict, field: str, index: int) -> str:
    row = {"sourceAttribute": field, "sourceIndex": index,
           "text": problem[field][index], "originalScope": None}
    canonical = json.dumps([problem["id"], row], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "req-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def update_document(guide: dict, problem: dict) -> None:
    steps = {step["stepNumber"]: step for step in guide["steps"]}
    steps[4]["content"] = (
        "## Route by document, not by client IP\n\nEditors of the same document may have different client IPs. "
        "Resolve document_id to its active collaboration owner when upgrading a WebSocket. "
        "A fenced ownership term prevents two servers from independently ordering one document. "
        "On owner failure, clients reconnect to the replacement owner and resume from their last acknowledged sequence."
    )
    lb = steps[5]["component"]
    lb["highlightReason"] = "Routes a document's editing sessions to its current owner; client-IP affinity alone is insufficient."
    lb["properties"].update({"algorithm": "document-ID affinity", "routingKey": "document_id",
        "description": "REST uses stateless routing. WebSocket upgrades resolve document_id through the owner registry; "
        "all editors of one document reach its single active OT owner. Ownership terms fence stale owners, "
        "and connection draining triggers reconnect/resume rather than silently losing edits."})
    lb["description"] = "REST routing and document-owner WebSocket affinity"
    collaboration = steps[8]["component"]["properties"]
    collaboration.update({
        "description": "Owns an assigned document shard and runs OT over a canonical sequence. Document-ID routing "
        "and fenced ownership keep all editors of a document at one active ordering authority. "
        "Acknowledge edits after the operation log is durable, then broadcast the accepted result. "
        "Recover from the latest committed snapshot plus subsequent durable operations when an owner fails.",
        "operationIdentity": "document_id + client_id + operation_id; retrying the same operation returns its prior result",
        "acknowledgement": "After durable operation-log append, before broadcast; unacknowledged edits can be safely retried",
        "reconnectProtocol": "Client sends last acknowledged document sequence; replay missing operations, deduplicate retries, "
            "and transform edits based on the canonical sequence. Use a fresh snapshot if retained replay is unavailable.",
        "documentOwnership": "Document-ID owner registry with monotonically increasing fencing term; only the active owner accepts writes",
        "authorization": "Check document ACL version for every accepted edit; revoked sessions cannot publish further operations",
        "hotDocuments": "Move ownership with fencing and replay; cap active editors per owner and shed excess load with retry guidance",
        "formats": "Versioned rich-text operation schema and markdown import/export; attachments remain outside the edit stream",
    })
    steps[8]["component"]["highlightReason"] = "A single fenced owner orders each document's OT operations and supports durable reconnect/replay."
    steps[8]["content"] += "\n\nThe applied design records operation identity, the durable acknowledgement boundary, reconnect replay, " \
        "per-edit authorization, rich-text/markdown handling, and hot-document ownership transfer. Inspect those decisions before applying."
    steps[9]["connection"]["label"] = "WebSocket (document owner)"
    steps[9]["connection"]["connectionType"] = "websocket"
    steps[9]["connection"]["description"] = "Resolve document_id to the fenced OT owner; reconnect resumes from the last acknowledged sequence."
    steps[6]["connection"]["description"] = "Gateway forwards REST and WebSocket upgrades over TLS; the load balancer resolves document_id to its fenced collaboration owner, not client-IP affinity."
    collaboration["ownerHandoff"] = "Stop accepting edits at the old owner, commit its watermark, acquire a newer fencing term, replay durable operations, then resume. During handoff clients buffer unacknowledged edits and retry operation IDs; stale terms are rejected."
    collaboration["importLimits"] = "Validate rich-text schema, sanitize markdown HTML and bound operation sizes; large imports use multipart object uploads then a serialized versioned replace/import command rather than oversized WebSocket frames."
    steps[12]["connection"]["description"] = "Append document-partitioned operations with quorum acknowledgement before acknowledging the edit; independent idempotent consumers materialize snapshots and indexes outside the editing path."
    database = steps[14]["component"]["properties"]
    database.update({
        "versionManifest": "Per-document head references only a complete immutable snapshot; compare-and-swap head/version updates",
        "snapshotRecovery": "Writer uploads immutable snapshot, then commits manifest and outbox in one Postgres transaction; "
            "retries are idempotent by document/version. Incomplete uploads are unreferenced and garbage-collected.",
        "rollback": "Authorized restore creates a new head/version from the selected revision; publish cache/search events via outbox",
        "documentLifecycle": "Create, edit, soft-delete and restore documents; versioned tombstones propagate to search/caches "
            "and invalidate sessions; retain immutable versions according to an explicit retention policy",
        "folderHierarchy": "Document metadata includes workspace_id, parent_folder_id, title, ownership, ACL version and current head",
        "versionRetention": "Keep committed history for the workspace retention policy; compact operation logs only after a verified snapshot watermark. Deletion removes active access immediately; purge retained snapshots asynchronously according to that policy.",
    })
    database["description"] = "Authoritative document/workspace metadata, folder hierarchy, ACL versions and immutable version manifests. Content lives in object storage. A closure table supports ancestor/subtree queries with indexes; transactions protect folder moves and permission inheritance."
    storage = steps[17]["component"]
    storage["componentType"] = "object-storage"
    storage["properties"].pop("type", None)
    storage["properties"].update({"provider": "S3", "versioning": True, "checksumValidation": True,
        "snapshotPolicy": "Immutable snapshot every 50 accepted operations; replay the durable operation log after its watermark",
        "attachmentAccess": "Short-lived, scope-bound presigned URLs issued after authorization; private buckets; validate upload size/type",
        "description": "S3-compatible object storage holds immutable document snapshots and large attachments. "
            "Postgres stores committed version manifests and object keys. Multipart presigned uploads keep large bytes out of the OT service."})
    session = steps[19]["component"]["properties"]
    session["description"] = "Redis holds replaceable session state and best-effort presence. The durable Kafka operation log, " \
        "not an evictable Redis buffer, is authoritative for acknowledged edits. Recover warm state from a snapshot plus replay."
    session["durabilityBoundary"] = "Loss of Redis cannot lose acknowledged operations; durable log is authoritative"
    auth = steps[26]["component"]["properties"]
    auth.update({"revocation": "Increment ACL version, publish invalidation, close revoked sessions, and check current ACL before accepting edits",
        "permissionChecks": "Authorize reads, edits, share changes, rollback, exports and attachment URLs; fail closed when ACL cannot be confirmed",
        "linkSharing": "Scoped expiring/revocable share tokens; never treat possession of an object-storage URL as permanent permission"})
    auth["description"] = "OAuth/JWT identity and document authorization for reads, edits, shares, rollback, exports and attachment URLs. ACL-versioned cached roles fail closed on uncertain permission. Public links carry explicit viewer/editor scope, expiry and revocation; current ACL is checked before content or edit acceptance."
    search = steps[23]["component"]["properties"]
    search["authorization"] = "Filter search by workspace/document ACL and recheck permission before returning content; apply tombstones and ACL invalidations"
    search["description"] = "Asynchronous full-text content index from committed snapshots. Query-time workspace/ACL filtering plus authorization recheck prevents unauthorized snippets. Idempotent versioned updates and tombstones tolerate duplicate events and rebuild from committed documents; freshness is eventual rather than part of the edit acknowledgement."
    steps[20]["connection"]["description"] = "Replaceable presence and session state only; snapshot plus the durable operation log recovers acknowledged edits. Redis Pub/Sub is best-effort and never the durability boundary."
    steps[28]["component"]["properties"]["invalidation"] = "Version and ACL-aware cache keys; transactional-outbox events invalidate document updates, deletions and revocations"

    changes = {
        35: ("guided_database", {"highAvailability": "Multi-AZ Postgres with monitored automated failover; writes reconnect with bounded retries"}),
        36: ("guided_database", {"disasterRecovery": "WAL archiving and point-in-time restore plus immutable snapshot backups; test restores and state recovery runbooks"}),
        37: ("guided_file_storage", {"encryption": "TLS in transit and managed-key encryption at rest; least-privilege access and secrets rotation"}),
        38: ("guided_cache_session", {"topology": "Sharded replaceable sessions/presence; persistent operation log remains separate; monitor hot keys and failover"}),
        39: ("guided_api_gateway", {"rateLimiting": "Per-user and per-IP token buckets, edit-size validation and bounded WebSocket ingress; retry/backoff guidance"}),
        40: ("guided_file_storage", {"staticAssetDelivery": "CDN for public static assets only; private documents/attachments keep authorization and short-lived access"}),
        41: ("guided_monitoring", {"tracing": "Correlate document/session/operation IDs across gateway, OT owner, Kafka and snapshot/search writers",
            "logging": "Structured failure/replay/revocation logs without document contents",
            "alerts": "Alert on edit-ack latency, operation-log lag, reconnect failures, snapshot failures and permission-invalidations; attach recovery runbooks"}),
    }
    for number, (node_id, properties) in changes.items():
        steps[number]["type"] = "update_component"
        steps[number]["componentUpdate"] = {"nodeId": node_id, "properties": properties}
        steps[number]["content"] += "\n\nChoose **Use this design decision** to record this strategy on the component. Reading this lesson does not apply it."
    requirements = {3: [("requirements", 0)], 8: [("requirements", 1), ("requirements", 6), ("constraints", 0), ("constraints", 4)],
                    14: [("requirements", 0), ("requirements", 2), ("requirements", 4)],
                    17: [("requirements", 2), ("constraints", 2), ("constraints", 3)],
                    23: [("requirements", 3)], 26: [("requirements", 5)], 28: [("constraints", 1)], 41: [("constraints", 1)]}
    for number, rows in requirements.items():
        steps[number]["requirementIds"] = [requirement_id(problem, field, index) for field, index in rows]


def _prior_component(steps: list[dict], step: dict) -> dict | None:
    prior = [candidate["component"] for candidate in steps
             if candidate.get("component") and candidate["stepNumber"] < step["stepNumber"]]
    return prior[-1] if prior else None


def _capture_decision(steps: list[dict], step: dict) -> None:
    choice = step["decision"]
    anchor = _prior_component(steps, step)
    if anchor is None:
        return
    step["componentUpdate"] = {
        "nodeId": anchor["nodeId"],
        "properties": {
            f"decision_{step['id']}": (
                f"{choice['question']} Choice: {choice['chosen']}. "
                f"Rationale: {choice['chosenReason']}"
            )
        },
    }


def _capture_scale_trigger(steps: list[dict], step: dict) -> None:
    trigger = step["scaleTrigger"]
    if not any(candidate.get("component") for candidate in steps):
        return
    anchor = _prior_component(steps, step)
    if anchor is None:
        return
    step["componentUpdate"] = {
        "nodeId": anchor["nodeId"],
        "properties": {
            f"scale_{step['id']}": (
                f"When {trigger['metric']}: {trigger['action']}. "
                f"Impact: {trigger['impact']}"
            )
        },
    }


def capture_explicit_choices(guide: dict) -> None:
    steps = guide["steps"]
    for step in steps:
        if step.get("decision"):
            _capture_decision(steps, step)
        if step.get("scaleTrigger"):
            _capture_scale_trigger(steps, step)


def fill_required_behaviors(guide: dict) -> None:
    """Authored missing capabilities from the unchanged source brief, not score hints."""
    components = {step["component"]["nodeId"]: step for step in guide["steps"] if step.get("component")}
    changes = {}
    if guide["problem_id"] == "6901ef1b9420d83630aca869":
        changes = {
            "guided_job_store": {"priorityModel": "Jobs have tenant_id, importance priority, scheduled_at, run_id and status. Index due, claimable jobs by priority and scheduled time; break ties by job ID. Preserve priority on retries.",
                                 "retryState": "Persist attempt_count, max_attempts, base_delay, max_delay, next_run_at, logical run_id and lease fencing term. A fenced status transition writes the next retry time and its scheduling outbox entry in the same transaction."},
            "guided_scheduler": {"priorityDispatch": "Claim only eligible due jobs using compare-and-set leases. Select importance bands before dispatch with bounded weighted fairness and aging so lower-priority jobs do not starve; break ties by scheduled_at then ID. Publish to priority-specific ready topics."},
            "guided_kafka": {"priorityQueues": "Separate ready-job topics for importance bands. Workers use weighted priority consumption; FIFO is preserved inside a band/partition, not mistaken for global priority ordering."},
            "guided_worker_pool": {"priorityConsumption": "Consume due jobs according to weighted importance bands with aging; validate the lease/run_id and retain existing idempotent execution and heartbeat handling.",
                                   "retryBackoff": "On a retryable failure, increase attempt_count and choose full-jitter exponential backoff: delay uniformly between zero and min(max_delay, base_delay * 2^(attempt_count - 1)). The job's configured policy supplies the base, cap and maximum attempts; non-retryable or exhausted failures go to the DLQ.",
                                   "retryReschedule": "Use the current lease fencing term to atomically persist pending_retry, next_run_at and an outbox record in Postgres. Keep the logical run_id stable for handler idempotency. A stale worker cannot overwrite a newer attempt; do not immediately republish the failed job to the ready queue."},
            "guided_redis": {"retryTimers": "An idempotent outbox relay upserts pending retries into the scheduling ZSET by next_run_at. Redis timers are rebuilt from Postgres pending jobs after loss; Redis is not the sole durable record of a retry."},
            "guided_dlq": {"exhaustedRetries": "The fenced terminal-failure transition records the last error and logical run_id and creates an idempotent DLQ outbox event. A relay delivers it without allowing lost or duplicated terminal state."},
        }
    if guide["problem_id"] == "6901ef1b9420d83630aca86c":
        changes = {
            "er_alerts": {"alertCriteria": "mode = absolute_threshold | percentage_drop; threshold_amount or percent_drop, product/source/currency scope, baseline_price at alert creation, baseline_observed_at, cooldown_until, last_triggered_version and active flag. Validate a positive baseline and percentage range."},
            "alert_service": {"percentageEvaluation": "Persist the latest valid price for the same source, variant and currency as the baseline. An absolute alert matches current_price <= threshold_amount; percentage drop matches 100 * (baseline_price - current_price) / baseline_price >= percent_drop. Reject missing/zero baseline, out-of-order observations and mismatched currency rather than issuing an incorrect alert.",
                              "fluctuationPolicy": "Deduplicate by alert_id + price_observation_version; notify once on crossing, suppress repeats during cooldown, and re-arm only after recovery above the threshold with a hysteresis margin. User changes can explicitly reset the baseline; ordinary polling does not silently reset it."},
        }
    for node_id, properties in changes.items():
        step = components[node_id]
        step["component"]["properties"].update(properties)
        step["content"] += "\n\n### Required behavior recorded by this step\n\n" + "\n\n".join(properties.values())
    if guide["problem_id"] == "6901ef1b9420d83630aca869":
        retry_step = next(step for step in guide["steps"] if step["stepNumber"] == 23)
        retry_step["type"] = "update_component"
        retry_step["componentUpdate"] = {"nodeId": "guided_scheduler", "properties": {
            "retryPromotion": "A retry is eligible only when its persisted next_run_at is due. Recover missing timers from Postgres, atomically claim a new fenced attempt, then dispatch through the existing priority-aware ready topics. Acknowledge outbox delivery idempotently; never busy-loop an immediate retry."
        }}
        retry_step["content"] += "\n\n### Apply the retry recovery decision\n\n" + retry_step["componentUpdate"]["properties"]["retryPromotion"]


def repository_path(path: Path) -> Path:
    """Resolve CLI paths and keep generated fixtures inside this checkout."""
    resolved = path.resolve()
    allowed_roots = (ROOT, (ROOT.parent / "diagramwise").resolve())
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise ValueError(FIXTURE_PATH_ERROR)
    return resolved


def repository_output_path(path: Path) -> Path:
    """Keep output paths lexical so the writer can reject every symlink hop."""
    target = Path(os.path.abspath(path))
    resolved = target.resolve()
    allowed_roots = (ROOT.resolve(), (ROOT.parent / "diagramwise").resolve())
    if not any(target == root or root in target.parents for root in allowed_roots):
        raise ValueError(FIXTURE_PATH_ERROR)
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise ValueError(FIXTURE_PATH_ERROR)
    if resolved != target:
        raise ValueError("Fixture output paths must not traverse symlinks")
    return target


def repository_output_file(directory: Path, name: str) -> Path:
    """Reject generated child paths redirected through pre-existing symlinks."""
    if Path(name).name != name or name in (".", ".."):
        raise ValueError("Generated fixture filenames must be simple child names")
    directory = Path(os.path.abspath(directory))
    if directory.resolve() != directory:
        raise ValueError("Generated fixture directory must not traverse symlinks")
    target = Path(os.path.abspath(directory / name))
    if target.parent != directory:
        raise ValueError("Generated fixture files must stay inside their output directory")
    if target.is_symlink():
        raise ValueError("Generated fixture files must not be symlinks")
    resolved = target.resolve()
    if resolved != target:
        raise ValueError("Generated fixture files must stay inside their output directory")
    return resolved


def _repository_output_root(path: Path) -> tuple[Path, Path]:
    target = repository_output_path(path)
    roots = (ROOT.resolve(), (ROOT.parent / "diagramwise").resolve())
    for root in roots:
        if target == root or root in target.parents:
            return root, target.relative_to(root)
    raise ValueError(FIXTURE_PATH_ERROR)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend-fixture", type=Path, help="Optional generated document apply-path fixture for the frontend test suite")
    parser.add_argument("--frontend-fixture-dir", type=Path, help="Optional generated apply-path fixtures for all five frontend tests")
    args = parser.parse_args()
    if args.frontend_fixture:
        args.frontend_fixture = repository_output_path(args.frontend_fixture)
    if args.frontend_fixture_dir:
        args.frontend_fixture_dir = repository_output_path(args.frontend_fixture_dir)
    return args


def _prepare_directories() -> tuple[Path, Path]:
    snapshot_dir = repository_path(SNAPSHOTS)
    output_dir = repository_path(OUTPUT)
    if snapshot_dir != SNAPSHOTS or output_dir != OUTPUT:
        raise ValueError("Fixture input/output directories must not redirect through symlinks")
    output_dir.mkdir(parents=True, exist_ok=True)
    return snapshot_dir, output_dir


def _load_problems(snapshot_dir: Path) -> dict:
    problems_path = repository_path(snapshot_dir / "problems.json")
    if problems_path.parent != snapshot_dir:
        raise ValueError("Problem snapshot must stay inside the walkthrough fixtures directory")
    return {problem["id"]: problem for problem in json.loads(problems_path.read_text(encoding="utf-8"))}


def _snapshot_sources(snapshot_dir: Path):
    for source in sorted(snapshot_dir.glob("*.json")):
        source = repository_path(source)
        if source.parent != snapshot_dir:
            raise ValueError("Walkthrough snapshots must stay inside their fixture directory")
        if source.name == "problems.json":
            continue
        yield source


def _candidate_filename(source: Path) -> str:
    """Use only a validated fixture basename for output paths, never JSON fields."""
    if source.suffix != ".json" or not SNAPSHOT_STEM_PATTERN.fullmatch(source.stem):
        raise ValueError("Walkthrough snapshot filename is invalid")
    return source.name


def _prepare_guide(source: Path, problems: dict) -> dict:
    guide = json.loads(source.read_text(encoding="utf-8"))
    if guide.get("problem_id") != source.stem:
        raise ValueError("Walkthrough ID must match its snapshot filename")
    guide["steps"].sort(key=lambda step: step["stepNumber"])
    guide["version"] = "2.1-candidate" if guide["problem_id"] == "6901ef1b9420d83630aca869" else "2.0-candidate"
    guide["requirementRevision"] = "requirements-v2-preserved"
    if guide["problem_id"] == DOCUMENT_ID:
        update_document(guide, problems[DOCUMENT_ID])
    capture_explicit_choices(guide)
    fill_required_behaviors(guide)
    return guide


def _frontend_fixture(guide: dict) -> dict:
    return {
        "problem_id": guide["problem_id"],
        "version": guide["version"],
        "requirementRevision": guide["requirementRevision"],
        "steps": [step for step in guide["steps"]
                  if step.get("component") or step.get("connection") or step.get("componentUpdate")],
    }


def _write_repository_fixture(path: Path, fixture: dict) -> None:
    """Write JSON only to a checked repository path without following a file symlink."""
    root, relative_path = _repository_output_root(path)
    if not relative_path.parts:
        raise ValueError("Generated fixture path must name a file")
    payload = json.dumps(fixture, indent=2, ensure_ascii=False) + "\n"
    if _supports_directory_relative_open():
        _write_repository_fixture_relative(root, relative_path, payload)
    else:
        _write_repository_fixture_path(path, payload)


def _supports_directory_relative_open() -> bool:
    return (
        hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and os.open in os.supports_dir_fd
        and os.mkdir in os.supports_dir_fd
        and os.rename in os.supports_dir_fd
        and os.unlink in os.supports_dir_fd
    )


def _write_repository_fixture_relative(root: Path, relative_path: Path, payload: str) -> None:
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory_fd = os.open(root, directory_flags)
    opened_directories = [directory_fd]
    try:
        for part in relative_path.parts[:-1]:
            try:
                os.mkdir(part, dir_fd=directory_fd)
            except FileExistsError:
                pass
            directory_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            opened_directories.append(directory_fd)
        _replace_repository_file(directory_fd, relative_path.parts[-1], payload)
    finally:
        for opened_fd in reversed(opened_directories):
            os.close(opened_fd)


def _replace_repository_file(directory_fd: int, filename: str, payload: str) -> None:
    temporary_name = f".{filename}.{secrets.token_hex(16)}.tmp"
    temporary_fd = os.open(
        temporary_name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o666,
        dir_fd=directory_fd,
    )
    try:
        with os.fdopen(temporary_fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
        os.rename(temporary_name, filename, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
    finally:
        try:
            os.unlink(temporary_name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def _write_repository_fixture_path(path: Path, payload: str) -> None:
    """Use path checks on platforms without directory-relative no-follow opens."""
    path = repository_output_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    output = repository_output_file(path.parent, path.name)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output.parent, prefix=f".{output.name}.",
            suffix=".tmp", delete=False,
        ) as stream:
            stream.write(payload)
            temporary_path = Path(stream.name)
        output = repository_output_file(output.parent, output.name)
        temporary_path.replace(output)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _write_frontend_fixture(path: Path, fixture: dict) -> None:
    _write_repository_fixture(path, fixture)


def _write_candidate_outputs(guide: dict, source: Path, output_dir: Path, args: argparse.Namespace) -> None:
    filename = _candidate_filename(source)
    if guide.get("problem_id") != source.stem:
        raise ValueError("Candidate problem ID must match its validated snapshot filename")
    output_dir = repository_output_path(output_dir)
    _write_repository_fixture(output_dir / filename, guide)
    if args.frontend_fixture and guide["problem_id"] == DOCUMENT_ID:
        _write_frontend_fixture(args.frontend_fixture, _frontend_fixture(guide))
    if args.frontend_fixture_dir:
        _write_frontend_fixture(args.frontend_fixture_dir / filename, _frontend_fixture(guide))


def main() -> None:
    args = _parse_arguments()
    snapshot_dir, output_dir = _prepare_directories()
    problems = _load_problems(snapshot_dir)
    for source in _snapshot_sources(snapshot_dir):
        guide = _prepare_guide(source, problems)
        _write_candidate_outputs(guide, source, output_dir, args)
    print(json.dumps({"candidateGuides": len(list(output_dir.glob("*.json"))), "status": "not_published"}))


if __name__ == "__main__":
    main()
