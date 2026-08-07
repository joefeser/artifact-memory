"""Portable tombstone propagation, acknowledgement, and suppression helpers."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, expected_receipt_id, receipt_with_digest, sha256_bytes
from .knowledge import knowledge_schema
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json_bytes, validate


AUTHORITY_BOUNDARY = "revocation propagation grants no execution, disclosure, routing, mutation, or erasure authority"
OUTCOMES = {"acknowledged", "duplicate", "rejected", "unsupported", "unavailable", "partially-complete"}
SUPPRESSION_STATES = {"applied", "not-applied", "not-applicable", "unknown"}


class SQLiteRevocationReplayLedger:
    """Durable v0 replay ledger with atomic first-writer-wins retention."""

    capability_id = "artifact-memory/revocation-replay-ledger/sqlite-v1"
    _schema_id = "artifact-memory/revocation-replay-ledger-state/v1"

    def __init__(self, path: Path) -> None:
        candidate = Path(path)
        if candidate.is_symlink():
            raise ValidationFailure("revocation-ledger-invalid", "revocation replay ledger must not be a symbolic link")
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            self.path = candidate.parent.resolve() / candidate.name
        except OSError as exc:
            raise ValidationFailure("revocation-ledger-unavailable", "revocation replay ledger path is unavailable") from exc
        if self.path.exists() and (self.path.is_symlink() or not self.path.is_file()):
            raise ValidationFailure("revocation-ledger-invalid", "revocation replay ledger must be a regular file")
        try:
            if not self.path.exists():
                try:
                    descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                except FileExistsError:
                    pass
                else:
                    os.close(descriptor)
            with closing(self._connect(validate_contract=False)) as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS replay_ledger_metadata (
                        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                        schema_id TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS revocation_acknowledgements (
                        acknowledgement_key TEXT PRIMARY KEY,
                        receipt_json BLOB NOT NULL
                    ) WITHOUT ROWID;
                    INSERT OR IGNORE INTO replay_ledger_metadata (singleton, schema_id)
                    VALUES (1, 'artifact-memory/revocation-replay-ledger-state/v1');
                    PRAGMA user_version = 1;
                    """
                )
                self._validate_contract(connection)
            if os.name == "posix":
                os.chmod(self.path, 0o600)
        except (OSError, sqlite3.Error, ValidationFailure) as exc:
            raise ValidationFailure("revocation-ledger-invalid", "revocation replay ledger contract is invalid") from exc

    def _connect(self, *, validate_contract: bool = True) -> sqlite3.Connection:
        if self.path.is_symlink():
            raise ValidationFailure("revocation-ledger-invalid", "revocation replay ledger must not be a symbolic link")
        connection = sqlite3.connect(self.path, timeout=5.0)
        try:
            connection.execute("PRAGMA journal_mode = DELETE")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA trusted_schema = OFF")
            connection.execute("PRAGMA busy_timeout = 5000")
            if validate_contract:
                self._validate_contract(connection)
        except Exception:
            connection.close()
            raise
        return connection

    def _validate_contract(self, connection: sqlite3.Connection) -> None:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if tables != {"replay_ledger_metadata", "revocation_acknowledgements"}:
            raise ValidationFailure("revocation-ledger-invalid", "revocation replay ledger tables are invalid")
        triggers = connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger'").fetchone()
        metadata = connection.execute(
            "SELECT singleton, schema_id FROM replay_ledger_metadata ORDER BY singleton"
        ).fetchall()
        version = connection.execute("PRAGMA user_version").fetchone()
        columns = connection.execute("PRAGMA table_info(revocation_acknowledgements)").fetchall()
        column_contract = [(row[1], row[2], row[3], row[5]) for row in columns]
        if (
            triggers != (0,)
            or metadata != [(1, self._schema_id)]
            or version != (1,)
            or column_contract != [("acknowledgement_key", "TEXT", 1, 1), ("receipt_json", "BLOB", 1, 0)]
        ):
            raise ValidationFailure("revocation-ledger-invalid", "revocation replay ledger metadata is invalid")

    def retain(self, acknowledgement_key: str, receipt: dict[str, Any]) -> dict[str, Any]:
        """Commit once and return the original canonical receipt across restarts."""
        if not isinstance(acknowledgement_key, str) or not acknowledgement_key:
            raise ValidationFailure("revocation-ledger-key-invalid", "revocation replay ledger key is invalid")
        requested_bytes = canonical_bytes(receipt)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR IGNORE INTO revocation_acknowledgements (acknowledgement_key, receipt_json) VALUES (?, ?)",
                (acknowledgement_key, requested_bytes),
            )
            row = connection.execute(
                "SELECT receipt_json FROM revocation_acknowledgements WHERE acknowledgement_key = ?",
                (acknowledgement_key,),
            ).fetchone()
            connection.commit()
        if row is None or not isinstance(row[0], bytes):
            raise ValidationFailure("revocation-ledger-invalid", "revocation replay ledger lost the retained receipt")
        retained = load_json_bytes(row[0])
        if not isinstance(retained, dict) or canonical_bytes(retained) != row[0]:
            raise ValidationFailure("revocation-ledger-invalid", "revocation replay ledger receipt is not canonical")
        return retained


def _tombstone_schema_name(schema_id: str) -> str:
    return "tombstone." + schema_id.rsplit("/", 1)[-1] + ".schema.json"


def _now(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValidationFailure("revocation-time-invalid", "revocation time is invalid") from exc
    if parsed.utcoffset() is None:
        raise ValidationFailure("revocation-time-invalid", "revocation time requires a timezone")
    return parsed


def _envelope_ref(envelope: dict[str, Any]) -> str:
    body = {key: value for key, value in envelope.items() if key not in {"envelope_id"}}
    return "revocation://" + sha256_bytes(canonical_bytes(body)).removeprefix("sha-256:")


def _validated_tombstone(tombstone: Any) -> dict[str, Any]:
    schema_id = tombstone.get("schema_id") if isinstance(tombstone, dict) else None
    if schema_id not in {"artifact-memory/tombstone/v1", "artifact-memory/tombstone/v2"}:
        raise ValidationFailure("tombstone-unsupported", "revocation requires a supported tombstone")
    validate(tombstone, load_schema("core", _tombstone_schema_name(schema_id)))
    body = {key: value for key, value in tombstone.items() if key not in {"schema_id", "tombstone_id"}}
    expected = "tombstone://" + sha256_bytes(canonical_bytes(body)).removeprefix("sha-256:")
    if tombstone["tombstone_id"] != expected:
        raise ValidationFailure("tombstone-identity-mismatch", "tombstone identity is invalid")
    return tombstone


def _validated_acknowledgement(receipt: Any) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise ValidationFailure("revocation-receipt-invalid", "revocation acknowledgement must be an object")
    validate(receipt, load_schema("core", "revocation-receipt.v1.schema.json"))
    if receipt["receipt_id"] != expected_receipt_id(receipt, "revocation-receipt://"):
        raise ValidationFailure("revocation-receipt-identity-mismatch", "revocation acknowledgement identity is invalid")
    return receipt


def _validated_envelope(envelope: Any) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise ValidationFailure("revocation-envelope-invalid", "revocation envelope must be an object")
    validate(envelope, load_schema("core", "revocation-envelope.v1.schema.json"))
    if envelope["envelope_id"] != _envelope_ref(envelope):
        raise ValidationFailure("revocation-identity-mismatch", "revocation envelope identity is invalid")
    return envelope


def build_revocation_envelope(
    tombstone: dict[str, Any],
    *,
    target_record: dict[str, Any],
    issuer_ref: str,
    audience_ref: str,
    correlation_id: str,
    expires_at: str,
    scope: str = "exchange-recipient",
) -> dict[str, Any]:
    """Build a digest-bound revocation envelope from a validated tombstone."""
    marker = _validated_tombstone(tombstone)
    validate(target_record, knowledge_schema(target_record))
    if marker["target_ref"] != target_record["record_id"]:
        raise ValidationFailure("revocation-target-mismatch", "tombstone target does not match the supplied record")
    body = {
        "tombstone_ref": marker["tombstone_id"],
        "deletion_receipt_ref": marker["deletion_receipt_ref"],
        "target_ref": marker["target_ref"],
        "target_revision_digest": sha256_bytes(canonical_bytes(target_record)),
        "issuer_ref": issuer_ref,
        "audience_ref": audience_ref,
        "correlation_id": correlation_id,
        "expires_at": expires_at,
        "scope": scope,
        "authority_boundary": AUTHORITY_BOUNDARY,
    }
    result = {"schema_id": "artifact-memory/revocation-envelope/v1", "envelope_id": _envelope_ref({**body, "schema_id": "artifact-memory/revocation-envelope/v1"}), **body}
    validate(result, load_schema("core", "revocation-envelope.v1.schema.json"))
    return result


def _ack_receipt(
    envelope: dict[str, Any],
    *,
    recipient_ref: str,
    outcome: str,
    suppression_state: str,
    endpoint_receipt_refs: Iterable[str] = (),
    diagnostics: Iterable[dict[str, str]] = (),
) -> dict[str, Any]:
    endpoint_values = list(endpoint_receipt_refs)
    if any(not isinstance(value, str) or not value for value in endpoint_values):
        raise ValidationFailure("endpoint-receipt-invalid", "endpoint receipt references must be non-empty strings")
    diagnostic_values = list(diagnostics)
    for diagnostic in diagnostic_values:
        if (
            not isinstance(diagnostic, Mapping)
            or set(diagnostic) != {"code", "message"}
            or any(not isinstance(diagnostic.get(key), str) or not diagnostic[key] for key in ("code", "message"))
        ):
            raise ValidationFailure("revocation-diagnostic-invalid", "revocation diagnostics must contain non-empty code and message strings")
    body = {
        "envelope_ref": envelope["envelope_id"],
        "recipient_ref": recipient_ref,
        "target_ref": envelope["target_ref"],
        "target_revision_digest": envelope["target_revision_digest"],
        "outcome": outcome,
        "suppression_state": suppression_state,
        "endpoint_receipt_refs": sorted(set(endpoint_values)),
        "diagnostics": [dict(value) for value in diagnostic_values],
        "audit_state": "immutable-receipt-retained",
        "authority_boundary": AUTHORITY_BOUNDARY,
    }
    receipt = receipt_with_digest("artifact-memory/revocation-receipt/v1", "revocation-receipt://", body)
    validate(receipt, load_schema("core", "revocation-receipt.v1.schema.json"))
    return receipt


def acknowledge_revocation(
    envelope: dict[str, Any],
    *,
    recipient_ref: str,
    outcome: str,
    suppression_state: str,
    replay_ledger: SQLiteRevocationReplayLedger | None = None,
    endpoint_receipt_refs: Iterable[str] = (),
    diagnostics: Iterable[dict[str, str]] = (),
    expected_audience_ref: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Create one receiver acknowledgement without deleting bytes."""
    _validated_envelope(envelope)
    if not isinstance(recipient_ref, str) or not recipient_ref:
        raise ValidationFailure("recipient-invalid", "recipient identity is required")
    if outcome not in OUTCOMES:
        raise ValidationFailure("revocation-outcome-invalid", "revocation outcome is unsupported")
    if suppression_state not in SUPPRESSION_STATES:
        raise ValidationFailure("suppression-state-invalid", "suppression state is unsupported")
    if expected_audience_ref is not None and envelope["audience_ref"] != expected_audience_ref:
        return _ack_receipt(envelope, recipient_ref=recipient_ref, outcome="rejected", suppression_state="not-applied", endpoint_receipt_refs=endpoint_receipt_refs, diagnostics=[{"code": "audience-mismatch", "message": "revocation audience does not match this recipient"}])
    if _now(now) >= _now(envelope["expires_at"]):
        return _ack_receipt(envelope, recipient_ref=recipient_ref, outcome="rejected", suppression_state="not-applied", endpoint_receipt_refs=endpoint_receipt_refs, diagnostics=[{"code": "expired", "message": "revocation envelope is expired"}])
    if outcome == "acknowledged" and suppression_state != "applied":
        raise ValidationFailure("suppression-state-invalid", "acknowledged revocation requires applied suppression")
    if outcome in {"unavailable", "rejected", "unsupported"} and suppression_state == "applied":
        raise ValidationFailure("suppression-state-invalid", "unavailable or rejected revocation cannot claim applied suppression")
    endpoint_values = list(endpoint_receipt_refs)
    diagnostic_values = list(diagnostics)
    requested_receipt = _ack_receipt(
        envelope,
        recipient_ref=recipient_ref,
        outcome=outcome,
        suppression_state=suppression_state,
        endpoint_receipt_refs=endpoint_values,
        diagnostics=diagnostic_values,
    )
    if outcome != "acknowledged":
        return requested_receipt
    if replay_ledger is None:
        return _ack_receipt(envelope, recipient_ref=recipient_ref, outcome="unavailable", suppression_state="unknown", endpoint_receipt_refs=endpoint_values, diagnostics=[{"code": "replay-ledger-unavailable", "message": "a durable atomic replay ledger is required"}])
    if type(replay_ledger) is not SQLiteRevocationReplayLedger:
        return _ack_receipt(envelope, recipient_ref=recipient_ref, outcome="unavailable", suppression_state="unknown", endpoint_receipt_refs=endpoint_values, diagnostics=[{"code": "replay-ledger-unapproved", "message": "the replay ledger does not provide the approved durable v0 capability"}])
    replay_key = envelope["envelope_id"] + "\x00" + recipient_ref
    try:
        retained_receipt = replay_ledger.retain(replay_key, requested_receipt)
        retained_receipt = _validated_acknowledgement(retained_receipt)
    except Exception:
        return _ack_receipt(envelope, recipient_ref=recipient_ref, outcome="unavailable", suppression_state="unknown", endpoint_receipt_refs=endpoint_values, diagnostics=[{"code": "replay-ledger-unavailable", "message": "the durable atomic replay ledger could not retain the acknowledgement"}])
    if (
        retained_receipt["envelope_ref"] != envelope["envelope_id"]
        or retained_receipt["recipient_ref"] != recipient_ref
        or retained_receipt["target_ref"] != envelope["target_ref"]
        or retained_receipt["target_revision_digest"] != envelope["target_revision_digest"]
        or retained_receipt["outcome"] != "acknowledged"
        or retained_receipt["suppression_state"] != "applied"
    ):
        return _ack_receipt(envelope, recipient_ref=recipient_ref, outcome="unavailable", suppression_state="unknown", endpoint_receipt_refs=endpoint_values, diagnostics=[{"code": "replay-ledger-invalid", "message": "the durable replay ledger returned an invalid acknowledgement binding"}])
    return retained_receipt


def aggregate_revocation(envelope: dict[str, Any], acknowledgements: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Bind recipient acknowledgements into one immutable propagation receipt."""
    _validated_envelope(envelope)
    receipts = list(acknowledgements)
    for receipt in receipts:
        _validated_acknowledgement(receipt)
        if receipt["envelope_ref"] != envelope["envelope_id"]:
            raise ValidationFailure("revocation-receipt-mismatch", "acknowledgement references another envelope")
        if receipt["target_ref"] != envelope["target_ref"] or receipt["target_revision_digest"] != envelope["target_revision_digest"]:
            raise ValidationFailure("revocation-receipt-mismatch", "acknowledgement target does not match the envelope")
    if not receipts:
        raise ValidationFailure("revocation-acknowledgement-missing", "at least one recipient acknowledgement is required")
    recipients = [receipt["recipient_ref"] for receipt in receipts]
    if len(set(recipients)) != len(recipients):
        raise ValidationFailure("revocation-recipient-duplicate", "recipient acknowledgements must be unique")
    successful = [receipt["recipient_ref"] for receipt in receipts if receipt["outcome"] == "acknowledged" and receipt["suppression_state"] == "applied"]
    unresolved = [receipt["recipient_ref"] for receipt in receipts if receipt["recipient_ref"] not in successful]
    outcome = "acknowledged" if not unresolved else "partially-complete"
    body = {
        "envelope_ref": envelope["envelope_id"],
        "outcome": outcome,
        "recipient_receipt_refs": sorted(receipt["receipt_id"] for receipt in receipts),
        "acknowledged_recipient_refs": sorted(successful),
        "unresolved_recipient_refs": sorted(unresolved),
        "audit_state": "immutable-receipt-retained",
        "authority_boundary": AUTHORITY_BOUNDARY,
    }
    result = receipt_with_digest("artifact-memory/revocation-propagation-receipt/v1", "revocation-propagation-receipt://", body)
    validate(result, load_schema("core", "revocation-propagation-receipt.v1.schema.json"))
    return result


def suppressed_record_ids(tombstones: Iterable[dict[str, Any]]) -> set[str]:
    """Return record identities suppressed by validated tombstones."""
    result: set[str] = set()
    for tombstone in tombstones:
        tombstone = _validated_tombstone(tombstone)
        if isinstance(tombstone["target_ref"], str) and tombstone["target_ref"].startswith("record://"):
            result.add(tombstone["target_ref"])
    return result


def validated_suppressions(
    records: Iterable[dict[str, Any]],
    acknowledgements: Iterable[dict[str, Any]],
) -> dict[str, str]:
    """Return exact record-to-receipt bindings proven to have applied suppression."""
    record_list = list(records)
    revisions: dict[str, str] = {}
    for record in record_list:
        validate(record, knowledge_schema(record))
        record_id = record["record_id"]
        if record_id in revisions:
            raise ValidationFailure("duplicate-record-id", "canonical record IDs must be unique")
        revisions[record_id] = sha256_bytes(canonical_bytes(record))
    result: dict[str, str] = {}
    for receipt in acknowledgements:
        receipt = _validated_acknowledgement(receipt)
        if receipt["outcome"] != "acknowledged" or receipt["suppression_state"] != "applied":
            raise ValidationFailure("suppression-not-applied", "revocation acknowledgement does not prove applied suppression")
        target = receipt["target_ref"]
        if target not in revisions or receipt["target_revision_digest"] != revisions[target]:
            raise ValidationFailure("suppression-target-mismatch", "revocation acknowledgement does not bind the supplied record revision")
        previous = result.get(target)
        if previous is not None and previous != receipt["receipt_id"]:
            raise ValidationFailure("suppression-duplicate", "multiple suppression receipts target one record revision")
        result[target] = receipt["receipt_id"]
    return result


def filter_revoked_records(records: Iterable[dict[str, Any]], acknowledgements: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter canonical records using exact, applied revocation acknowledgements."""
    materialized = list(records)
    blocked = validated_suppressions(materialized, acknowledgements)
    return [record for record in materialized if record["record_id"] not in blocked]
