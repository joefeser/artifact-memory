"""Bounded Artifact Memory knowledge exchange with explicit admission truth."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any


AUTHORITY_BOUNDARY = "knowledge exchange grants no execution, disclosure, routing, spending, credential, deployment, merge, or mutation authority"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def make_envelope(audience_ref: str, correlation_id: str, expires_at: str, record_refs: list[dict[str, str]], artifact_refs: list[str], sensitivity: str = "public", record_bundle: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    body = {"schema_id": "artifact-memory/exchange-envelope/v1", "audience_ref": audience_ref, "correlation_id": correlation_id, "expires_at": expires_at, "record_refs": sorted(record_refs, key=lambda item: item["record_id"]), "artifact_refs": sorted(artifact_refs), "handling": {"sensitivity": sensitivity, "disclosure": "informational-only"}, "authority_boundary": AUTHORITY_BOUNDARY}
    if record_bundle is not None:
        body["record_bundle"] = sorted(record_bundle, key=lambda item: item.get("record_id", ""))
    return {**body, "envelope_id": "exchange://" + hashlib.sha256(_canonical(body)).hexdigest()}


def admit(envelope: dict[str, Any], seen_envelope_ids: set[str] | None = None, supported_schema: bool = True, now: str | None = None) -> dict[str, Any]:
    seen_envelope_ids = seen_envelope_ids or set()
    envelope_id = envelope.get("envelope_id", "")
    if not supported_schema:
        outcome, diagnostics = "unsupported", [{"code": "schema-unsupported", "message": "exchange schema is unsupported"}]
    elif envelope_id in seen_envelope_ids:
        outcome, diagnostics = "duplicate", [{"code": "replay", "message": "envelope was already admitted or rejected"}]
    else:
        try:
            expiry = datetime.fromisoformat(str(envelope["expires_at"]).replace("Z", "+00:00"))
            current = datetime.fromisoformat((now or envelope["expires_at"]).replace("Z", "+00:00"))
            if expiry <= current:
                outcome, diagnostics = "rejected", [{"code": "expired", "message": "exchange envelope is expired"}]
            elif not envelope.get("record_refs") and not envelope.get("artifact_refs"):
                outcome, diagnostics = "quarantined", [{"code": "empty-bundle", "message": "envelope contains no admitted references"}]
            else:
                outcome, diagnostics = "admitted", []
        except (KeyError, ValueError):
            outcome, diagnostics = "rejected", [{"code": "invalid-envelope", "message": "expiry or required envelope field is invalid"}]
    accepted = [item["record_id"] for item in envelope.get("record_refs", [])] if outcome == "admitted" else []
    receipt_body = {"envelope_ref": envelope_id, "outcome": outcome, "accepted_record_ids": accepted, "diagnostics": diagnostics, "authority_boundary": AUTHORITY_BOUNDARY}
    return {"schema_id": "artifact-memory/admission-receipt/v1", "receipt_id": "admission-receipt://" + hashlib.sha256(_canonical(receipt_body)).hexdigest(), **receipt_body}
