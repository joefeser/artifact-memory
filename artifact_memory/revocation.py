"""Portable tombstone propagation, acknowledgement, and suppression helpers."""

from __future__ import annotations

from collections.abc import Iterable, MutableSet
from datetime import datetime, timezone
from typing import Any

from .canonical import canonical_bytes, receipt_with_digest, sha256_bytes
from .schema_resources import load_schema
from .validator import ValidationFailure, validate


AUTHORITY_BOUNDARY = "revocation propagation grants no execution, disclosure, routing, mutation, or erasure authority"
OUTCOMES = {"acknowledged", "duplicate", "rejected", "unsupported", "unavailable", "partially-complete"}
SUPPRESSION_STATES = {"applied", "not-applied", "not-applicable", "unknown"}


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


def build_revocation_envelope(
    tombstone: dict[str, Any],
    *,
    target_revision_digest: str,
    issuer_ref: str,
    audience_ref: str,
    correlation_id: str,
    expires_at: str,
    scope: str = "exchange-recipient",
) -> dict[str, Any]:
    """Build a digest-bound revocation envelope from a validated tombstone."""
    schema_id = tombstone.get("schema_id") if isinstance(tombstone, dict) else None
    if schema_id not in {"artifact-memory/tombstone/v1", "artifact-memory/tombstone/v2"}:
        raise ValidationFailure("tombstone-unsupported", "revocation requires a supported tombstone")
    validate(tombstone, load_schema("core", _tombstone_schema_name(schema_id)))
    body = {
        "tombstone_ref": tombstone["tombstone_id"],
        "target_ref": tombstone["target_ref"],
        "target_revision_digest": target_revision_digest,
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
    body = {
        "envelope_ref": envelope["envelope_id"],
        "recipient_ref": recipient_ref,
        "target_ref": envelope["target_ref"],
        "target_revision_digest": envelope["target_revision_digest"],
        "outcome": outcome,
        "suppression_state": suppression_state,
        "endpoint_receipt_refs": sorted(set(endpoint_receipt_refs)),
        "diagnostics": list(diagnostics),
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
    endpoint_receipt_refs: Iterable[str] = (),
    diagnostics: Iterable[dict[str, str]] = (),
    expected_audience_ref: str | None = None,
    seen_envelope_ids: MutableSet[str] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Create one receiver acknowledgement without deleting bytes."""
    validate(envelope, load_schema("core", "revocation-envelope.v1.schema.json"))
    if envelope["envelope_id"] != _envelope_ref({**{key: value for key, value in envelope.items() if key != "envelope_id"}, "schema_id": envelope["schema_id"]}):
        raise ValidationFailure("revocation-identity-mismatch", "revocation envelope identity is invalid")
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
    if seen_envelope_ids is not None and envelope["envelope_id"] in seen_envelope_ids:
        return _ack_receipt(envelope, recipient_ref=recipient_ref, outcome="duplicate", suppression_state="not-applicable", endpoint_receipt_refs=endpoint_receipt_refs, diagnostics=[{"code": "replay", "message": "revocation envelope was already acknowledged"}])
    if outcome == "acknowledged" and suppression_state != "applied":
        raise ValidationFailure("suppression-state-invalid", "acknowledged revocation requires applied suppression")
    if outcome in {"unavailable", "rejected", "unsupported"} and suppression_state == "applied":
        raise ValidationFailure("suppression-state-invalid", "unavailable or rejected revocation cannot claim applied suppression")
    receipt = _ack_receipt(envelope, recipient_ref=recipient_ref, outcome=outcome, suppression_state=suppression_state, endpoint_receipt_refs=endpoint_receipt_refs, diagnostics=diagnostics)
    if seen_envelope_ids is not None and outcome == "acknowledged":
        seen_envelope_ids.add(envelope["envelope_id"])
    return receipt


def aggregate_revocation(envelope: dict[str, Any], acknowledgements: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Bind recipient acknowledgements into one immutable propagation receipt."""
    validate(envelope, load_schema("core", "revocation-envelope.v1.schema.json"))
    receipts = list(acknowledgements)
    for receipt in receipts:
        validate(receipt, load_schema("core", "revocation-receipt.v1.schema.json"))
        if receipt["envelope_ref"] != envelope["envelope_id"]:
            raise ValidationFailure("revocation-receipt-mismatch", "acknowledgement references another envelope")
    if not receipts:
        raise ValidationFailure("revocation-acknowledgement-missing", "at least one recipient acknowledgement is required")
    recipients = [receipt["recipient_ref"] for receipt in receipts]
    if len(set(recipients)) != len(recipients):
        raise ValidationFailure("revocation-recipient-duplicate", "recipient acknowledgements must be unique")
    successful = [receipt["recipient_ref"] for receipt in receipts if receipt["outcome"] in {"acknowledged", "duplicate"}]
    unresolved = [receipt["recipient_ref"] for receipt in receipts if receipt["outcome"] not in {"acknowledged", "duplicate"}]
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
        schema_id = tombstone.get("schema_id") if isinstance(tombstone, dict) else None
        if schema_id not in {"artifact-memory/tombstone/v1", "artifact-memory/tombstone/v2"}:
            raise ValidationFailure("tombstone-unsupported", "suppression requires a supported tombstone")
        validate(tombstone, load_schema("core", _tombstone_schema_name(schema_id)))
        if isinstance(tombstone["target_ref"], str) and tombstone["target_ref"].startswith("record://"):
            result.add(tombstone["target_ref"])
    return result


def filter_revoked_records(records: Iterable[dict[str, Any]], tombstones: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter canonical records using only explicitly validated tombstones."""
    blocked = suppressed_record_ids(tombstones)
    return [record for record in records if record.get("record_id") not in blocked]
