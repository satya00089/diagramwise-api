from copy import deepcopy
from decimal import Decimal

import pytest

from scripts.requirements_migration import (
    MigrationError, apply_manifest, approval_digest, audit_catalog, dry_run,
    export_snapshot, main, make_draft, read_json, rollback_manifest, scan_public,
    validation_errors, write_json,
)


class MockTable:
    """Small expression interpreter to test actual per-attribute conditions and writes."""

    def __init__(self, item):
        self.item = deepcopy(item)
        self.writes = []
        self.reads = []
        self.before_update = None
        self.corrupt_readback = False

    def get_item(self, **kwargs):
        self.reads.append(kwargs)
        item = deepcopy(self.item)
        if self.corrupt_readback and self.writes:
            item["requirementSpec"]["revision"] = "concurrent-revision"
        return {"Item": item} if item else {}

    def update_item(self, **kwargs):
        if self.before_update:
            self.before_update(self.item)
            self.before_update = None
        names, values = kwargs["ExpressionAttributeNames"], kwargs["ExpressionAttributeValues"]
        for condition in kwargs["ConditionExpression"].split(" AND "):
            if condition.startswith("attribute_not_exists("):
                field = names[condition[len("attribute_not_exists("):-1]]
                if field in self.item:
                    raise RuntimeError("ConditionalCheckFailedException")
            else:
                name, value = condition.split(" = ")
                if names[name] not in self.item or self.item[names[name]] != values[value]:
                    raise RuntimeError("ConditionalCheckFailedException")
        expression = kwargs["UpdateExpression"]
        parts = expression.split(" REMOVE ") if expression.startswith("SET ") else ["", expression[7:]]
        if parts[0]:
            for assignment in parts[0][4:].split(", "):
                name, value = assignment.split(" = ")
                self.item[names[name]] = deepcopy(values[value])
        if len(parts) == 2:
            for name in parts[1].split(", "):
                self.item.pop(names[name], None)
        self.writes.append(deepcopy(kwargs))


@pytest.fixture
def problem():
    return {"id": "p1", "slug": "public-problem", "title": "Public exercise", "description": "Brief",
            "requirements": ["Create a URL. Preserve aliases.", "99.9% availability", "Support optional expiration"],
            "constraints": ["URLs should not expire", "Use an approved region"],
            "has_guided_walkthrough": True, "unrelatedField": {"owner": "untouched"}}


def approved(problem):
    manifest = make_draft(export_snapshot([problem]), "requirements-v2-preserved")
    for change in manifest["changes"]:
        change["review"] = {"status": "reviewed", "reviewer": "human-editor"}
        for row in change["provenance"]:
            row.update(status="reviewed", reviewer="human-editor", reason="Preserved stated exercise scope")
    manifest["readerCompatibility"] = {"status": "verified", "schemaVersions": [1],
                                       "deployment": "test-deployment", "evidence": "Test attestation"}
    manifest["cachePlan"].update(reviewed=True, releaseVersion="catalog-v2")
    manifest["approved"] = True
    manifest["approval"] = {"reviewer": "human-editor", "digest": approval_digest(manifest)}
    return manifest


def test_local_export_strips_private_and_unrecognized_fields(problem):
    problem["privateAttempts"] = [{"answer": "private"}]
    snapshot = export_snapshot([problem])
    assert "privateAttempts" not in snapshot["records"][0]
    assert "unrelatedField" not in snapshot["records"][0]
    assert snapshot["records"][0]["constraints"] == problem["constraints"]


def test_pagination_including_empty_intermediate_page():
    class Scan:
        def __init__(self):
            self.calls = []

        def scan(self, **kwargs):
            self.calls.append(kwargs)
            return [
                {"Items": [{"id": "a"}], "LastEvaluatedKey": {"id": "a"}},
                {"Items": [], "LastEvaluatedKey": {"id": "b"}},
                {"Items": [{"id": "c"}]},
            ][len(self.calls) - 1]

    table = Scan()
    assert scan_public(table) == [{"id": "a"}, {"id": "c"}]
    assert table.calls[2]["ExclusiveStartKey"] == {"id": "b"}
    assert all(call["ConsistentRead"] for call in table.calls)
    assert "privateAttempts" not in table.calls[0]["ExpressionAttributeNames"].values()


def test_repeated_scan_cursor_is_not_accepted():
    class Scan:
        def scan(self, **kwargs):
            return {"Items": [], "LastEvaluatedKey": {"id": "a"}}
    table = Scan()
    with pytest.raises(MigrationError, match="Repeated scan"):
        scan_public(table)


def test_draft_preserves_every_sentence_provenance_and_original_scope(problem):
    problem["requirements"].append({"text": "Optional export", "scope": "extension"})
    manifest = make_draft(export_snapshot([problem]), "requirements-v2-preserved")
    change = manifest["changes"][0]
    assert len(change["provenance"]) == 6
    assert change["provenance"][0]["text"] == "Create a URL. Preserve aliases."
    assert change["provenance"][3]["scope"] == "extension"
    assert all(row["status"] == "needs_review" for row in change["provenance"])
    assert change["proposedSpec"]["assumptions"] == []
    assert change["proposedSpec"]["nonFunctional"][0]["text"] == "99.9% availability"
    assert not validation_errors(manifest)
    assert any("Unreviewed" in error for error in validation_errors(manifest, publish=True))
    assert make_draft(export_snapshot([problem]))["changes"][0]["provenance"][0]["id"] == change["provenance"][0]["id"]


@pytest.mark.parametrize("mutation", ["sentence", "omit", "scope", "guide_assumption", "base_revision", "identity"])
def test_preservation_failures_block_publication(problem, mutation):
    problem["requirements"] = [{"text": "Core sentence", "scope": "core"}]
    manifest = approved(problem)
    change = manifest["changes"][0]
    if mutation == "sentence":
        change["provenance"][0]["text"] = "Richer public guide sentence"
    elif mutation == "omit":
        change["provenance"].pop()
    elif mutation == "scope":
        change["provenance"][0]["scope"] = "extension"
    elif mutation == "guide_assumption":
        change["proposedSpec"]["assumptions"] = ["1B invented requests"]
    elif mutation == "base_revision":
        change["baseRevision"] = "stale-v1"
    else:
        change["slug"] = "new-slug"
    assert validation_errors(manifest, publish=True)


def test_dry_run_never_contacts_table(problem):
    table = MockTable(problem)
    report = apply_manifest(table, make_draft(export_snapshot([problem])))
    assert report["remoteWrites"] is False
    assert not table.writes
    assert not table.reads
    assert report["changes"][0]["before"]["requirementSpec"] == {"exists": False}


def test_reader_gate_and_approval_tampering_block_before_reads(problem):
    manifest = approved(problem)
    manifest["readerCompatibility"]["status"] = "unverified"
    table = MockTable(problem)
    with pytest.raises(MigrationError, match="compatibility"):
        apply_manifest(table, manifest, apply=True, save_journal=lambda value: None)
    assert not table.reads
    manifest = approved(problem)
    manifest["changes"][0]["proposedSpec"]["revision"] = "changed-after-approval"
    with pytest.raises(MigrationError, match="changed after approval"):
        apply_manifest(table, manifest, apply=True, save_journal=lambda value: None)


def test_apply_and_rollback_modify_only_approved_attributes(problem):
    original = deepcopy(problem)
    manifest = approved(problem)
    table = MockTable(problem)
    journals = []
    applied = apply_manifest(table, manifest, apply=True, save_journal=journals.append)
    assert journals[0]["entries"] == []
    assert journals[1]["entries"][0]["status"] == "pending"
    assert applied["status"] == "verified"
    assert table.item["requirements"] == original["requirements"]
    assert table.item["constraints"] == original["constraints"]
    assert table.item["id"] == original["id"]
    assert table.item["slug"] == original["slug"]
    assert table.item["unrelatedField"] == original["unrelatedField"]
    assert all(call["ConsistentRead"] for call in table.reads)
    table.item["unrelatedField"] = {"owner": "later-unrelated-edit"}
    rolled = rollback_manifest(table, manifest, applied, apply=True, save_journal=journals.append)
    assert rolled["status"] == "rolled_back"
    assert "requirementSpec" not in table.item
    assert "requirementSpecProvenance" not in table.item
    assert table.item["unrelatedField"] == {"owner": "later-unrelated-edit"}
    assert table.item["constraints"] == original["constraints"]
    assert table.writes[-1]["UpdateExpression"].startswith("REMOVE")


def test_preflight_all_rows_prevents_partial_known_stale_batch(problem):
    second = {**deepcopy(problem), "id": "p2", "slug": "p2"}
    manifest = approved(problem)
    another = approved(second)["changes"][0]
    manifest["changes"].append(another)
    manifest["approval"]["digest"] = approval_digest(manifest)
    table = MockTable(problem)
    with pytest.raises(MigrationError, match="missing"):
        apply_manifest(table, manifest, apply=True, save_journal=lambda value: None)
    assert not table.writes


def test_conditional_update_rejects_race_after_preflight(problem):
    table = MockTable(problem)
    table.before_update = lambda item: item["requirements"].append("Concurrent change")
    journals = []
    manifest = approved(problem)
    with pytest.raises(MigrationError, match="ConditionalCheckFailed"):
        apply_manifest(table, manifest, apply=True, save_journal=journals.append)
    assert not table.writes
    assert journals[-1]["status"] == "stopped"


def test_readback_mismatch_is_preserved_in_rollback_journal(problem):
    table = MockTable(problem)
    table.corrupt_readback = True
    journals = []
    manifest = approved(problem)
    with pytest.raises(MigrationError, match="concurrent"):
        apply_manifest(table, manifest, apply=True, save_journal=journals.append)
    assert len(table.writes) == 1
    assert journals[-1]["entries"][0]["status"] == "applied"
    assert "error" in journals[-1]["entries"][0]


def test_rollback_rejects_later_spec_edit(problem):
    manifest = approved(problem)
    table = MockTable(problem)
    journal = apply_manifest(table, manifest, apply=True, save_journal=lambda value: None)
    table.item["requirementSpec"]["revision"] = "later-editor-revision"
    with pytest.raises(MigrationError, match="concurrent"):
        rollback_manifest(table, manifest, journal, apply=True, save_journal=lambda value: None)
    assert len(table.writes) == 1


def test_pending_uncertain_write_can_be_rolled_back_only_if_exact_current(problem):
    manifest = approved(problem)
    table = MockTable(problem)
    journal = apply_manifest(table, manifest, apply=True, save_journal=lambda value: None)
    journal["entries"][0]["status"] = "pending"
    rollback_manifest(table, manifest, journal, apply=True, save_journal=lambda value: None)
    assert "requirementSpec" not in table.item


def test_rollback_journal_tampering_and_wrong_manifest_rejected(problem):
    manifest = approved(problem)
    table = MockTable(problem)
    journal = apply_manifest(table, manifest, apply=True, save_journal=lambda value: None)
    journal["entries"][0]["original"]["requirementSpec"] = {"exists": True, "value": {"bad": "restore"}}
    with pytest.raises(MigrationError, match="Tampered"):
        rollback_manifest(table, manifest, journal)


def test_decimal_snapshots_roundtrip_losslessly(tmp_path, problem):
    problem["requirementSpecProvenance"] = {"exact": Decimal("1.123456789123456789")}
    path = tmp_path / "snapshot.json"
    snapshot = export_snapshot([problem])
    write_json(path, snapshot)
    assert read_json(path) == snapshot
    with pytest.raises(FileExistsError):
        write_json(path, snapshot)


def test_catalog_alias_and_richer_guide_are_audit_only(tmp_path, problem):
    write_json(tmp_path / "public-problem.json", {"requirements": {"functional": ["Richer optional expiration"],
                                                                 "nonFunctional": ["10B redirects per month"]}})
    write_json(tmp_path / "job-scheduler.json", {})
    snapshot = export_snapshot([problem])
    audit = audit_catalog(snapshot, tmp_path)
    assert audit["aliases"] == [{"slug": "job-scheduler", "status": "unresolved_alias"}]
    assert audit["matrix"][0]["guideRequirementsDifferingFromLive"] == ["Richer optional expiration", "10B redirects per month"]
    assert make_draft(snapshot)["changes"][0]["proposedSpec"]["assumptions"] == []


def test_cli_local_export_and_default_apply_are_offline(tmp_path, problem, monkeypatch):
    import scripts.requirements_migration as migration
    monkeypatch.setattr(migration, "aws_table", lambda *args: pytest.fail("Unexpected AWS access"))
    raw, snapshot_path, manifest_path, report_path = [tmp_path / name for name in
                                                   ("raw.json", "snapshot.json", "manifest.json", "dryrun.json")]
    write_json(raw, [problem])
    assert main(["export", "--input", str(raw), "--output", str(snapshot_path)]) == 0
    manifest = make_draft(read_json(snapshot_path))
    write_json(manifest_path, manifest)
    assert main(["apply", "--manifest", str(manifest_path), "--output", str(report_path)]) == 0
    assert not read_json(report_path)["remoteWrites"]
    unsafe_args = ["apply", "--manifest", str(manifest_path), "--apply",
                   "--output", str(tmp_path / "unused.json")]
    with pytest.raises(SystemExit):
        main(unsafe_args)
