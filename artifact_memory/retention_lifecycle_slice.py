"""Synthetic #36 proof for endpoint-scoped retention and deletion semantics."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, receipt_with_digest
from .projection import logical_projection_snapshot, project_records
from .retention import deletion_receipt, overall_deletion_status, retention_disposition, tombstone
from .schema_resources import load_schema
from .validator import validate


OBSERVED_AT = "2026-07-31T00:00:00Z"
ACTIVE_ENDPOINT = "endpoint://synthetic/active-vault"
INDEX_ENDPOINT = "endpoint://synthetic/generated-index"
BACKUP_ENDPOINT = "endpoint://artifact-memory/joe-home-proxmox-vault-1"
BACKUP_GENERATION = "snapshot-synthetic-0001"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"fixture must contain an object: {path.name}")
    return value


def _indexed_record_ids(index_path: Path) -> list[str]:
    connection = sqlite3.connect(index_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return [row[0] for row in connection.execute("SELECT record_id FROM records ORDER BY record_id")]
    finally:
        connection.close()


def run_retention_lifecycle_slice(fixture_root: Path) -> dict[str, Any]:
    """Exercise four synthetic lifecycle cases without deleting external bytes."""
    policy = _load(fixture_root / "retention-policy.json")
    validate(policy, load_schema("core", "retention-policy.v2.schema.json"))
    if retention_disposition(policy, now=OBSERVED_AT) != "retained-until-expiry":
        raise RuntimeError("synthetic backup generation must remain retained until expiry")

    before_paths = sorted((fixture_root / "before").glob("*.json"))
    after_paths = sorted((fixture_root / "after").glob("*.json"))
    before = [_load(path) for path in before_paths]
    after = [_load(path) for path in after_paths]
    before_ids = {record["record_id"] for record in before}
    after_ids = {record["record_id"] for record in after}
    removed_ids = sorted(before_ids - after_ids)
    if removed_ids != ["record://synthetic/accidental-0001", "record://synthetic/owner-delete-0001"]:
        raise RuntimeError("synthetic lifecycle fixture removed an unexpected record set")
    redacted_id = "record://synthetic/redacted-0001"
    redacted = next((record for record in after if record["record_id"] == redacted_id), None)
    if redacted is None or not any(
        relationship == {"type": "redacted-from", "target_ref": "record://synthetic/accidental-0001"}
        for relationship in redacted.get("relationships", [])
    ):
        raise RuntimeError("redacted derivative is not bound to its source record")

    with tempfile.TemporaryDirectory(prefix="artifact-memory-retention-") as temporary:
        root = Path(temporary)
        before_output = root / "before-index"
        after_output = root / "after-index"
        before_projection = project_records(before_paths, before_output)
        after_projection = project_records(after_paths, after_output)
        indexed_after = _indexed_record_ids(after_output / "records.sqlite")
        generated_bytes = (after_output / "records.ndjson").read_bytes() + (after_output / "records.sqlite").read_bytes()
        forbidden_markers = [b"SYNTHETIC-ACCIDENTAL-MARKER", b"SYNTHETIC-OWNER-DELETE-MARKER"]
        if any(marker in generated_bytes for marker in forbidden_markers):
            raise RuntimeError("rebuilt generated index retained deleted synthetic content")
        if any(record_id in indexed_after for record_id in removed_ids):
            raise RuntimeError("rebuilt generated index retained a deleted record identity")

        active_receipts = [
            deletion_receipt(
                target_ref,
                "active-vault",
                "verified-absent-at-endpoint",
                observed_at=OBSERVED_AT,
                managed_scope=True,
                endpoint_ref=ACTIVE_ENDPOINT,
                authority_ref=authority_ref,
                evidence_refs=[after_projection["source_record_set_digest"]],
                issuer="synthetic",
            )
            for target_ref, authority_ref in (
                (removed_ids[0], "authority://synthetic/incident-response-0001"),
                (removed_ids[1], "authority://synthetic/owner-approval-0001"),
            )
        ]
        accidental_active, owner_active = active_receipts
        index_receipt = deletion_receipt(
            "record-set://synthetic/deletion-targets",
            "generated-index",
            "verified-absent-at-endpoint",
            observed_at=OBSERVED_AT,
            managed_scope=True,
            endpoint_ref=INDEX_ENDPOINT,
            evidence_refs=[
                after_projection["source_record_set_digest"],
                "sha-256:"
                + hashlib.sha256(
                    canonical_bytes(logical_projection_snapshot(after_output / "records.sqlite"))
                ).hexdigest(),
            ],
            issuer="synthetic",
        )
        backup_receipt = deletion_receipt(
            "record-set://synthetic/deletion-targets",
            "managed-backup",
            "retained-until-expiry",
            observed_at=OBSERVED_AT,
            managed_scope=True,
            endpoint_ref=BACKUP_ENDPOINT,
            generation_ref=BACKUP_GENERATION,
            evidence_refs=["retention-policy://synthetic/deferred-expiry"],
            limitations=[
                "named backup generation remains until managed expiry",
                "backup receipt says nothing about other generations or endpoints",
            ],
            issuer="synthetic",
        )
        unknown_receipt = deletion_receipt(
            "record-set://synthetic/deletion-targets",
            "unknown-replica",
            "scope-unknown",
            observed_at=OBSERVED_AT,
            managed_scope=False,
            limitations=["unknown or unmanaged replicas cannot be enumerated or verified"],
            issuer="synthetic",
        )

    receipts = [accidental_active, owner_active, index_receipt, backup_receipt, unknown_receipt]
    receipt_schema = load_schema("core", "deletion-receipt.v2.schema.json")
    for item in receipts:
        validate(item, receipt_schema)
    overall = overall_deletion_status(receipts)
    if overall != "partially-complete":
        raise RuntimeError("managed backup retention and unknown replicas must keep deletion partial")

    accidental_tombstone = tombstone(
        removed_ids[0],
        "redacted-derivative",
        "derivative-replaced",
        accidental_active["receipt_id"],
        created_at=OBSERVED_AT,
        superseded_by_ref=redacted_id,
    )
    owner_tombstone = tombstone(
        removed_ids[1],
        "owner-approved-deletion",
        "bytes-removed-from-scope",
        owner_active["receipt_id"],
        created_at=OBSERVED_AT,
    )
    for marker in (accidental_tombstone, owner_tombstone):
        validate(marker, load_schema("core", "tombstone.v2.schema.json"))

    body = {
        "outcome": "complete",
        "policy_id": policy["policy_id"],
        "scenario_outcomes": {
            "accidental_ingestion": "partially-complete",
            "redacted_derivative": "derivative-replaced",
            "deferred_backup_expiry": "retained-until-expiry",
            "owner_approved_deletion": "partially-complete",
        },
        "overall_deletion_outcome": overall,
        "deletion_receipt_refs": [item["receipt_id"] for item in receipts],
        "deletion_receipts": receipts,
        "tombstone_refs": [accidental_tombstone["tombstone_id"], owner_tombstone["tombstone_id"]],
        "tombstones": [accidental_tombstone, owner_tombstone],
        "before_record_set_digest": before_projection["source_record_set_digest"],
        "after_record_set_digest": after_projection["source_record_set_digest"],
        "before_record_count": before_projection["record_count"],
        "after_record_count": after_projection["record_count"],
        "removed_record_ids": removed_ids,
        "retained_record_ids": indexed_after,
        "generated_index_rebuild": "deleted-content-absent",
        "managed_backup_state": "retained-until-expiry",
        "unknown_replica_state": "scope-unknown",
        "global_erasure_claim": False,
        "destructive_execution_authority": "synthetic-fixture-only",
        "limitations": [
            "backup purge evidence applies only to a named endpoint and generation",
            "unknown and unmanaged replicas remain outside verified scope",
            "the fixture performs no deletion against a real vault, backup, or Git history",
        ],
    }
    result = receipt_with_digest(
        "artifact-memory/retention-lifecycle-slice-receipt/v1",
        "retention-lifecycle-receipt://synthetic/",
        body,
    )
    validate(result, load_schema("core", "retention-lifecycle-slice-receipt.v1.schema.json"))
    return result
