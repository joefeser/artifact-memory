"""Bounded Artifact Memory knowledge exchange with explicit admission truth."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from .canonical import canonical_bytes, receipt_with_digest
from .schema_resources import load_schema
from .validator import ValidationFailure, validate

AUTHORITY_BOUNDARY = "knowledge exchange grants no execution, disclosure, routing, spending, credential, deployment, merge, or mutation authority"


_canonical = canonical_bytes
_PROTECTED_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "bearer_token",
        "credential",
        "credentials",
        "password",
        "refresh_token",
        "secret",
    }
)


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


def _contains_bearer_material(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            key.casefold() in _PROTECTED_KEYS
            or _contains_bearer_material(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_bearer_material(item) for item in value)
    return isinstance(value, str) and (
        value.casefold().startswith("bearer ")
        or re.fullmatch(r"(?:gh[opusr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})", value)
        is not None
    )


def _bundle_manifest(
    record_refs: list[dict[str, str]],
    artifact_refs: list[str],
) -> dict[str, Any]:
    body = {
        "records": sorted(record_refs, key=lambda item: (item["record_id"], item["revision_digest"])),
        "artifact_refs": sorted(artifact_refs),
    }
    return {
        "bundle_id": "exchange-bundle://" + hashlib.sha256(_canonical(body)).hexdigest(),
        **body,
    }


def make_envelope_v2(
    audience_ref: str,
    correlation_id: str,
    expires_at: str,
    record_refs: list[dict[str, str]],
    artifact_refs: list[str],
    *,
    sensitivity: str = "public",
    record_bundle: list[dict[str, Any]] | None = None,
    extensions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a v2 envelope with an identity-bound explicit bundle manifest."""
    body: dict[str, Any] = {
        "schema_id": "artifact-memory/exchange-envelope/v2",
        "audience_ref": audience_ref,
        "correlation_id": correlation_id,
        "expires_at": expires_at,
        "bundle_manifest": _bundle_manifest(record_refs, artifact_refs),
        "handling": {
            "sensitivity": sensitivity,
            "disclosure": "informational-only",
            "artifact_retrieval": "separately-authorized",
        },
        "authority_boundary": AUTHORITY_BOUNDARY,
    }
    if record_bundle is not None:
        body["record_bundle"] = sorted(
            record_bundle,
            key=lambda item: item.get("record_id", "") if isinstance(item, dict) else "",
        )
    if extensions is not None:
        body["extensions"] = extensions
    return {
        **body,
        "envelope_id": "exchange://" + hashlib.sha256(_canonical(body)).hexdigest(),
    }


def _v2_receipt(
    envelope_ref: str,
    outcome: str,
    *,
    accepted_record_ids: list[str] | None = None,
    unresolved_record_ids: list[str] | None = None,
    artifact_refs: list[str] | None = None,
    diagnostics: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    body = {
        "envelope_ref": envelope_ref,
        "outcome": outcome,
        "accepted_record_ids": sorted(accepted_record_ids or []),
        "unresolved_record_ids": sorted(unresolved_record_ids or []),
        "artifact_refs": sorted(artifact_refs or []),
        "artifact_retrieval": "not-attempted/separately-authorized",
        "diagnostics": diagnostics or [],
        "authority_boundary": AUTHORITY_BOUNDARY,
    }
    receipt = receipt_with_digest(
        "artifact-memory/admission-receipt/v2",
        "admission-receipt://",
        body,
    )
    validate(receipt, load_schema("core", "admission-receipt.v2.schema.json"))
    return receipt


def _record_revision(record: dict[str, Any]) -> tuple[str, str, str]:
    record_id = record.get("record_id")
    schema_id = record.get("schema_id")
    if not isinstance(record_id, str) or not isinstance(schema_id, str):
        raise ValidationFailure("invalid-record", "bundled record identity is invalid")
    schema_name = {
        "artifact-memory/knowledge-record/v1": "knowledge-record.v1.schema.json",
        "artifact-memory/knowledge-record/v2": "knowledge-record.v2.schema.json",
    }.get(schema_id)
    if schema_name is None:
        raise ValidationFailure("unsupported-record", "bundled record schema is unsupported")
    validate(record, load_schema("core", schema_name))
    sensitivity = record.get("sensitivity", "restricted")
    if sensitivity not in {"public", "private", "restricted"}:
        raise ValidationFailure("invalid-record", "bundled record sensitivity is invalid")
    return (
        record_id,
        "sha-256:" + hashlib.sha256(_canonical(record)).hexdigest(),
        sensitivity,
    )


def admit_v2(
    envelope: dict[str, Any],
    seen_envelope_ids: set[str] | None = None,
    *,
    expected_audience_ref: str,
    supported_schema: bool = True,
    now: str | None = None,
    available_record_revisions: set[tuple[str, str]] | None = None,
    available_record_sensitivities: dict[tuple[str, str], str] | None = None,
) -> dict[str, Any]:
    """Admit one v2 envelope with deterministic replay and resolution truth."""
    envelope_ref = _safe_envelope_ref(envelope)
    if not supported_schema:
        return _v2_receipt(
            envelope_ref,
            "unsupported",
            diagnostics=[{"code": "schema-unsupported", "message": "exchange schema is unsupported"}],
        )
    try:
        validate(envelope, load_schema("core", "exchange-envelope.v2.schema.json"))
    except (ValidationFailure, KeyError, TypeError):
        return _v2_receipt(
            envelope_ref,
            "rejected",
            diagnostics=[{"code": "invalid-envelope", "message": "exchange envelope does not satisfy the v2 contract"}],
        )
    if envelope["envelope_id"] != envelope_ref:
        return _v2_receipt(
            envelope_ref,
            "rejected",
            diagnostics=[{"code": "envelope-id-mismatch", "message": "exchange envelope identity does not match its canonical body"}],
        )
    manifest = envelope["bundle_manifest"]
    manifest_body = {
        "records": manifest["records"],
        "artifact_refs": manifest["artifact_refs"],
    }
    expected_bundle_id = "exchange-bundle://" + hashlib.sha256(_canonical(manifest_body)).hexdigest()
    if manifest["bundle_id"] != expected_bundle_id:
        return _v2_receipt(
            envelope_ref,
            "rejected",
            diagnostics=[{"code": "bundle-id-mismatch", "message": "bundle manifest identity does not match its canonical body"}],
        )
    ledger = seen_envelope_ids if seen_envelope_ids is not None else set()
    if envelope_ref in ledger:
        return _v2_receipt(
            envelope_ref,
            "duplicate",
            diagnostics=[{"code": "replay", "message": "envelope was already processed"}],
        )
    if envelope["audience_ref"] != expected_audience_ref:
        ledger.add(envelope_ref)
        return _v2_receipt(
            envelope_ref,
            "rejected",
            diagnostics=[{"code": "audience-mismatch", "message": "exchange audience does not match this receiver"}],
        )
    if _contains_bearer_material(envelope):
        ledger.add(envelope_ref)
        return _v2_receipt(
            envelope_ref,
            "rejected",
            diagnostics=[{"code": "bearer-material-prohibited", "message": "exchange envelope contains prohibited bearer material"}],
        )
    try:
        expiry = datetime.fromisoformat(envelope["expires_at"].replace("Z", "+00:00"))
        current = (
            datetime.fromisoformat(now.replace("Z", "+00:00"))
            if now is not None
            else datetime.now(timezone.utc)
        )
        if expiry <= current:
            ledger.add(envelope_ref)
            return _v2_receipt(
                envelope_ref,
                "rejected",
                diagnostics=[{"code": "expired", "message": "exchange envelope is expired"}],
            )
    except (ValueError, TypeError):
        return _v2_receipt(
            envelope_ref,
            "rejected",
            diagnostics=[{"code": "invalid-expiry", "message": "exchange expiry is invalid"}],
        )

    declared: dict[str, str] = {}
    contradictory: list[str] = []
    for item in manifest["records"]:
        prior = declared.get(item["record_id"])
        if prior is not None:
            contradictory.append(item["record_id"])
        else:
            declared[item["record_id"]] = item["revision_digest"]
    bundled: dict[str, str] = {}
    handling_conflict = False
    sensitivity_rank = {"public": 0, "private": 1, "restricted": 2}
    handling_sensitivity = envelope["handling"]["sensitivity"]
    try:
        for record in envelope.get("record_bundle", []):
            record_id, revision, sensitivity = _record_revision(record)
            if record_id in bundled or record_id not in declared or declared[record_id] != revision:
                contradictory.append(record_id)
            elif sensitivity_rank[sensitivity] > sensitivity_rank[handling_sensitivity]:
                handling_conflict = True
            else:
                bundled[record_id] = revision
    except ValidationFailure:
        contradictory.append("record://invalid/bundled-record")
    if contradictory or handling_conflict:
        ledger.add(envelope_ref)
        diagnostic = (
            {"code": "contradictory-bundle", "message": "bundle declarations or bytes contradict each other"}
            if contradictory
            else {"code": "handling-sensitivity-mismatch", "message": "bundle handling is weaker than a record sensitivity"}
        )
        return _v2_receipt(
            envelope_ref,
            "quarantined",
            unresolved_record_ids=sorted(declared),
            artifact_refs=manifest["artifact_refs"],
            diagnostics=[diagnostic],
        )

    available = available_record_revisions or set()
    available_sensitivities = available_record_sensitivities or {}

    def locally_available(record_id: str, revision: str) -> bool:
        sensitivity = available_sensitivities.get((record_id, revision))
        return (
            (record_id, revision) in available
            and isinstance(sensitivity, str)
            and sensitivity in sensitivity_rank
            and sensitivity_rank[sensitivity] <= sensitivity_rank[handling_sensitivity]
        )

    accepted = sorted(
        record_id
        for record_id, revision in declared.items()
        if bundled.get(record_id) == revision
        or locally_available(record_id, revision)
    )
    unresolved = sorted(set(declared) - set(accepted))
    artifact_refs = manifest["artifact_refs"]
    if accepted and unresolved:
        outcome = "partially-resolved"
        diagnostics = [{"code": "record-unresolved", "message": "one or more declared records are unresolved"}]
    elif unresolved:
        outcome = "quarantined"
        diagnostics = [{"code": "bundle-unresolved", "message": "no declared record revision could be resolved"}]
    elif accepted or artifact_refs:
        outcome = "admitted"
        diagnostics = []
    else:
        outcome = "quarantined"
        diagnostics = [{"code": "empty-bundle", "message": "bundle contains no knowledge or artifact references"}]
    ledger.add(envelope_ref)
    return _v2_receipt(
        envelope_ref,
        outcome,
        accepted_record_ids=accepted,
        unresolved_record_ids=unresolved,
        artifact_refs=artifact_refs,
        diagnostics=diagnostics,
    )
