"""Bounded Artifact Memory knowledge exchange with explicit admission truth."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from .canonical import canonical_bytes, receipt_with_digest
from .schema_resources import load_schema
from .validator import ValidationFailure, validate

AUTHORITY_BOUNDARY = "knowledge exchange grants no execution, disclosure, routing, spending, credential, deployment, merge, or mutation authority"


_canonical = canonical_bytes


def make_envelope(audience_ref: str, correlation_id: str, expires_at: str, record_refs: list[dict[str, str]], artifact_refs: list[str], sensitivity: str = "public", record_bundle: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    body = {"schema_id": "artifact-memory/exchange-envelope/v1", "audience_ref": audience_ref, "correlation_id": correlation_id, "expires_at": expires_at, "record_refs": sorted(record_refs, key=lambda item: item["record_id"]), "artifact_refs": sorted(artifact_refs), "handling": {"sensitivity": sensitivity, "disclosure": "informational-only"}, "authority_boundary": AUTHORITY_BOUNDARY}
    if record_bundle is not None:
        body["record_bundle"] = sorted(record_bundle, key=lambda item: item.get("record_id", ""))
    return {**body, "envelope_id": "exchange://" + hashlib.sha256(_canonical(body)).hexdigest()}


def _safe_envelope_ref(envelope: Any) -> str:
    if isinstance(envelope, dict):
        try:
            body = {key: value for key, value in envelope.items() if key != "envelope_id"}
            return "exchange://" + hashlib.sha256(_canonical(body)).hexdigest()
        except (TypeError, ValueError):
            pass
    return "exchange://" + "0" * 64


def admit(envelope: dict[str, Any], seen_envelope_ids: set[str] | None = None, supported_schema: bool = True, now: str | None = None) -> dict[str, Any]:
    seen_envelope_ids = seen_envelope_ids or set()
    envelope_id = _safe_envelope_ref(envelope)
    if not supported_schema:
        outcome, diagnostics = "unsupported", [{"code": "schema-unsupported", "message": "exchange schema is unsupported"}]
    else:
        try:
            validate(envelope, load_schema("core", "exchange-envelope.v1.schema.json"))
        except (ValidationFailure, KeyError, TypeError):
            outcome, diagnostics = "rejected", [{"code": "invalid-envelope", "message": "exchange envelope does not satisfy the v1 contract"}]
        else:
            if envelope["envelope_id"] != envelope_id:
                outcome, diagnostics = "rejected", [{"code": "envelope-id-mismatch", "message": "exchange envelope identity does not match its canonical body"}]
            elif envelope_id in seen_envelope_ids:
                outcome, diagnostics = "duplicate", [{"code": "replay", "message": "envelope was already admitted or rejected"}]
            else:
                try:
                    expiry = datetime.fromisoformat(envelope["expires_at"].replace("Z", "+00:00"))
                    current = datetime.fromisoformat(now.replace("Z", "+00:00")) if now else datetime.now(timezone.utc)
                    if expiry <= current:
                        outcome, diagnostics = "rejected", [{"code": "expired", "message": "exchange envelope is expired"}]
                    elif not envelope["record_refs"] and not envelope["artifact_refs"]:
                        outcome, diagnostics = "quarantined", [{"code": "empty-bundle", "message": "envelope contains no admitted references"}]
                    else:
                        outcome, diagnostics = "admitted", []
                except (ValueError, TypeError):
                    outcome, diagnostics = "rejected", [{"code": "invalid-envelope", "message": "expiry is invalid"}]
    accepted = [item["record_id"] for item in envelope["record_refs"]] if outcome == "admitted" else []
    receipt_body = {"envelope_ref": envelope_id, "outcome": outcome, "accepted_record_ids": accepted, "diagnostics": diagnostics, "authority_boundary": AUTHORITY_BOUNDARY}
    return receipt_with_digest("artifact-memory/admission-receipt/v1", "admission-receipt://", receipt_body)
