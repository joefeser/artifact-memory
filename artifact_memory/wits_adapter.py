"""Independent, reference-only Artifact Memory ↔ WITS process boundary."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable, Mapping

from .canonical import canonical_bytes, receipt_with_digest
from .projection import _knowledge_schema
from .validator import ValidationFailure, validate


AUTHORITY_BOUNDARY = "informational projection only; no HACP task, route, continuation, or execution authority"
WITS_REPOSITORY = "joefeser/what-is-the-spec"
WITS_CONTRACT_COMMIT = "d675ba6d632dc03826f27940014d4cd672f7d910"
WITS_LICENSE = "BSL-1.1"
WITS_CHANGE_DATE = "2030-01-01"
WITS_CHANGE_LICENSE = "Apache-2.0"
SUPPORTED_PROJECTION_KINDS = {"owner-meaning", "decision", "readiness", "ambiguity"}
FORBIDDEN_AUTHORITY_KEYS = {
    "approval", "authority", "continuation_payload", "create_task", "destination",
    "execute", "human_approval", "requested_actions", "route_task", "task_packet",
}
SHA256 = re.compile(r"^sha-256:[0-9a-f]{64}$")


def _digest(value: Any) -> str:
    return "sha-256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def _contains_authority(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(FORBIDDEN_AUTHORITY_KEYS & set(value)) or any(_contains_authority(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_authority(item) for item in value)
    return False


def contract_anchor() -> dict[str, Any]:
    """Return the supported WITS contract identity without copying WITS schemas."""
    return {
        "repository": WITS_REPOSITORY,
        "commit": WITS_CONTRACT_COMMIT,
        "license": WITS_LICENSE,
        "change_date": WITS_CHANGE_DATE,
        "change_license": WITS_CHANGE_LICENSE,
        "contract_refs": [
            "docs/coordination-memory/schema/memory-card.md",
            "docs/coordination-memory/templates/fresh-context-packet.md",
            "docs/hacp/rfcs/0001-task-packet.md",
            "docs/hacp/dispatch/route-task.schema.json",
        ],
    }


def _source_refs(records: Iterable[dict[str, Any]]) -> tuple[list[dict[str, str]], str | None]:
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for record in records:
        try:
            validate(record, _knowledge_schema(record))
        except ValidationFailure:
            return [], "unsupported-record-schema"
        record_id = record["record_id"]
        if record_id in seen:
            return [], "mixed-revision-context"
        seen.add(record_id)
        refs.append({"record_id": record_id, "revision_digest": _digest(record)})
    refs.sort(key=lambda item: item["record_id"])
    return refs, None if refs else "unsupported-record-schema"


def build_projection_request(
    records: Iterable[dict[str, Any]],
    projection_kind: str,
    *,
    expected_revisions: Mapping[str, str] | None = None,
    external_evidence_refs: Iterable[str] = (),
) -> dict[str, Any]:
    refs, failure = _source_refs(records)
    if failure:
        raise ValueError(failure)
    expected = expected_revisions if expected_revisions is not None else {item["record_id"]: item["revision_digest"] for item in refs}
    return {
        "schema_id": "artifact-memory/wits-projection-request/v1",
        "source_record_refs": refs,
        "expected_revisions": dict(sorted(expected.items())),
        "external_evidence_refs": sorted(set(external_evidence_refs)),
        "projection_kind": projection_kind,
        "provider_contract": contract_anchor(),
        "authority_boundary": AUTHORITY_BOUNDARY,
    }


def _receipt(outcome: str, source_refs: list[dict[str, str]], request_digest: str, code: str | None = None) -> dict[str, Any]:
    diagnostics = [] if code is None else [{"code": code, "message": {
        "unsupported-record-schema": "source record schema is unsupported",
        "not-authorized": "explicit local authorization is required outside portable records",
        "authority-boundary": "knowledge projection cannot carry task, route, continuation, or execution authority",
        "mixed-revision-context": "the request does not bind one exact revision for every source record",
        "stale-source-revision": "a source record revision differs from the requested revision",
        "superseded-record": "a source record is superseded",
        "conflicting-records": "the source set has an unresolved conflict",
        "sensitivity-mapping-unavailable": "the provider sensitivity mapping is unavailable",
        "disclosure-denied": "the requested disclosure is not authorized",
        "evidence-reference-unavailable": "a referenced evidence binding is unavailable",
        "projection-unsupported": "the projection kind or provider contract is unsupported",
        "wits-projection-rejected": "WITS did not admit the projection",
        "provider-response-invalid": "the provider response is invalid or is not bound to this request",
    }[code]}]
    body = {
        "outcome": outcome,
        "source_record_refs": source_refs,
        "request_digest": request_digest,
        "authority_boundary": AUTHORITY_BOUNDARY,
        "diagnostics": diagnostics,
    }
    return receipt_with_digest("artifact-memory/wits-admission-receipt/v2", "wits-admission-receipt://", body)


def bind_projection_v2(
    records: list[dict[str, Any]],
    projection_kind: str,
    provider_response: dict[str, Any],
    authorized: bool,
    external_evidence_refs: list[str] | None = None,
    expected_revisions: dict[str, str] | None = None,
    *,
    sensitivity_mapping_available: bool = True,
    disclosure_allowed: bool = True,
    unavailable_evidence_refs: Iterable[str] = (),
    conflict_detected: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Bind one opaque WITS projection; never invoke WITS or create HACP work."""
    source_refs, source_failure = _source_refs(records)
    effective_revisions = expected_revisions if expected_revisions is not None else {item["record_id"]: item["revision_digest"] for item in source_refs}
    request = {
        "schema_id": "artifact-memory/wits-projection-request/v1",
        "source_record_refs": source_refs,
        "expected_revisions": dict(sorted(effective_revisions.items())),
        "external_evidence_refs": sorted(set(external_evidence_refs or [])),
        "projection_kind": projection_kind,
        "provider_contract": contract_anchor(),
        "authority_boundary": AUTHORITY_BOUNDARY,
    }
    request_digest = _digest(request)
    failure: tuple[str, str] | None = None
    if source_failure:
        failure = ("unsupported", source_failure)
    elif not authorized:
        failure = ("rejected", "not-authorized")
    elif not isinstance(provider_response, dict):
        failure = ("unsupported", "provider-response-invalid")
    elif _contains_authority(provider_response) or projection_kind in {"create-task", "route", "execute"}:
        failure = ("authority-bearing-request-rejected", "authority-boundary")
    elif set(request["expected_revisions"]) != {item["record_id"] for item in source_refs}:
        failure = ("mixed-revision-context", "mixed-revision-context")
    elif any(request["expected_revisions"][item["record_id"]] != item["revision_digest"] for item in source_refs):
        failure = ("stale", "stale-source-revision")
    elif any(record.get("lifecycle") == "superseded" for record in records):
        failure = ("superseded", "superseded-record")
    elif conflict_detected:
        failure = ("conflict", "conflicting-records")
    elif not sensitivity_mapping_available:
        failure = ("sensitivity-mapping-unavailable", "sensitivity-mapping-unavailable")
    elif not disclosure_allowed:
        failure = ("disclosure-denied", "disclosure-denied")
    elif set(unavailable_evidence_refs) & set(request["external_evidence_refs"]):
        failure = ("evidence-reference-unavailable", "evidence-reference-unavailable")
    elif projection_kind not in SUPPORTED_PROJECTION_KINDS:
        failure = ("unsupported", "projection-unsupported")
    elif provider_response.get("admission") != "admitted":
        failure = ("rejected", "wits-projection-rejected")
    else:
        required = {"admission", "request_digest", "projection_ref", "projection_schema_ref", "projection_digest"}
        if (
            set(provider_response) != required
            or provider_response.get("request_digest") != request_digest
            or any(not isinstance(provider_response.get(key), str) or not provider_response[key] for key in required - {"admission"})
            or SHA256.fullmatch(provider_response.get("projection_digest", "")) is None
        ):
            failure = ("unsupported", "provider-response-invalid")
    if failure:
        return None, _receipt(failure[0], source_refs, request_digest, failure[1])

    body = {
        "source_record_refs": source_refs,
        "external_evidence_refs": request["external_evidence_refs"],
        "projection_kind": projection_kind,
        "wits_projection_ref": provider_response["projection_ref"],
        "wits_projection_schema_ref": provider_response["projection_schema_ref"],
        "projection_digest": provider_response["projection_digest"],
        "request_digest": request_digest,
        "provider_contract": contract_anchor(),
        "authority_boundary": AUTHORITY_BOUNDARY,
    }
    projection = {
        "schema_id": "artifact-memory/wits-projection/v2",
        "projection_id": "wits-binding://" + hashlib.sha256(canonical_bytes(body)).hexdigest(),
        **body,
    }
    return projection, _receipt("admitted", source_refs, request_digest)


def bind_projection(
    records: list[dict[str, Any]],
    projection_kind: str,
    provider_response: dict[str, Any],
    authorized: bool,
    external_evidence_refs: list[str] | None = None,
    expected_revisions: dict[str, str] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Compatibility helper for the accepted minimum v1 projection contract."""
    source_refs = [
        {"record_id": record["record_id"], "revision_digest": _digest(record)}
        for record in sorted(records, key=lambda item: item["record_id"])
    ]
    source_ids = [item["record_id"] for item in source_refs]
    if not authorized:
        outcome, diagnostics = "rejected", [{"code": "not-authorized", "message": "explicit local authorization is required outside portable records"}]
    elif _contains_authority(provider_response) or projection_kind in {"create-task", "route", "execute"}:
        outcome, diagnostics = "authority-bearing-request-rejected", [{"code": "authority-boundary", "message": "projection channel cannot carry task or execution authority"}]
    elif expected_revisions and any(expected_revisions.get(item["record_id"]) not in (None, item["revision_digest"]) for item in source_refs):
        outcome, diagnostics = "stale", [{"code": "stale-source-revision", "message": "source record revision does not match the requested revision"}]
    elif projection_kind not in SUPPORTED_PROJECTION_KINDS:
        outcome, diagnostics = "unsupported", [{"code": "projection-unsupported", "message": "projection kind is unsupported"}]
    elif provider_response.get("admission") != "admitted":
        outcome, diagnostics = "rejected", [{"code": "wits-projection-rejected", "message": "provider projection was not admitted"}]
    else:
        outcome, diagnostics = "admitted", []
    receipt_body = {"outcome": outcome, "source_record_ids": source_ids, "authority_boundary": AUTHORITY_BOUNDARY, "diagnostics": diagnostics}
    receipt = receipt_with_digest("artifact-memory/wits-admission-receipt/v1", "wits-admission-receipt://", receipt_body)
    if outcome != "admitted":
        return None, receipt
    projection = {
        "schema_id": "artifact-memory/wits-projection/v1",
        "projection_id": "wits-binding://" + _digest({"source_record_refs": source_refs, "projection": provider_response}).removeprefix("sha-256:"),
        "source_record_refs": source_refs,
        "external_evidence_refs": sorted(external_evidence_refs or []),
        "projection_kind": projection_kind,
        "wits_projection_ref": provider_response["projection_ref"],
        "wits_projection_schema_ref": provider_response["projection_schema_ref"],
        "projection_digest": provider_response["projection_digest"],
        "authority_boundary": AUTHORITY_BOUNDARY,
    }
    return projection, receipt
