"""Independently implemented Artifact Memory ↔ WITS projection boundary."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .canonical import receipt_with_digest
from .projection import _canonical
from .validator import validate


AUTHORITY_BOUNDARY = "informational projection only; no HACP task, route, continuation, or execution authority"
FORBIDDEN_AUTHORITY_KEYS = {"task_packet", "route_task", "destination", "execute", "authority", "continuation_payload", "create_task"}


def _digest(value: Any) -> str:
    return "sha-256:" + hashlib.sha256(_canonical(value)).hexdigest()


def bind_projection(records: list[dict[str, Any]], projection_kind: str, provider_response: dict[str, Any], authorized: bool, external_evidence_refs: list[str] | None = None, expected_revisions: dict[str, str] | None = None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    source_refs = [{"record_id": record["record_id"], "revision_digest": _digest(record)} for record in sorted(records, key=lambda item: item["record_id"])]
    source_ids = [item["record_id"] for item in source_refs]
    if not authorized:
        outcome, diagnostics = "rejected", [{"code": "not-authorized", "message": "explicit local authorization is required outside portable records"}]
    elif any(key in provider_response for key in FORBIDDEN_AUTHORITY_KEYS) or projection_kind in {"create-task", "route", "execute"}:
        outcome, diagnostics = "authority-bearing-request-rejected", [{"code": "authority-boundary", "message": "projection channel cannot carry task or execution authority"}]
    elif expected_revisions and any(expected_revisions.get(item["record_id"]) not in (None, item["revision_digest"]) for item in source_refs):
        outcome, diagnostics = "stale", [{"code": "stale-source-revision", "message": "source record revision does not match the requested revision"}]
    elif projection_kind not in {"owner-meaning", "decision", "readiness", "ambiguity"}:
        outcome, diagnostics = "unsupported", [{"code": "projection-unsupported", "message": "projection kind is unsupported"}]
    elif provider_response.get("admission") != "admitted":
        outcome, diagnostics = "rejected", [{"code": "wits-projection-rejected", "message": "provider projection was not admitted"}]
    else:
        outcome, diagnostics = "admitted", []
    receipt_body = {"outcome": outcome, "source_record_ids": source_ids, "authority_boundary": AUTHORITY_BOUNDARY, "diagnostics": diagnostics}
    receipt = receipt_with_digest("artifact-memory/wits-admission-receipt/v1", "wits-admission-receipt://", receipt_body)
    if outcome != "admitted":
        return None, receipt
    projection = {"schema_id": "artifact-memory/wits-projection/v1", "projection_id": "wits-binding://" + _digest({"source_record_refs": source_refs, "projection": provider_response}).removeprefix("sha-256:"), "source_record_refs": source_refs, "external_evidence_refs": sorted(external_evidence_refs or []), "projection_kind": projection_kind, "wits_projection_ref": provider_response["projection_ref"], "wits_projection_schema_ref": provider_response["projection_schema_ref"], "projection_digest": provider_response["projection_digest"], "authority_boundary": AUTHORITY_BOUNDARY}
    return projection, receipt
