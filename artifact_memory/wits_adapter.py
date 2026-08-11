"""Independent, reference-only Artifact Memory ↔ WITS process boundary."""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from typing import Any, Iterable, Mapping

from .canonical import canonical_bytes, receipt_with_digest
from .extensions import ExtensionFailure, preserve_extensions
from .projection import _knowledge_schema
from .schema_resources import load_schema
from .validator import ValidationFailure, validate


AUTHORITY_BOUNDARY = "informational projection only; no HACP task, route, continuation, or execution authority"
WITS_REPOSITORY = "joefeser/what-is-the-spec"
WITS_CONTRACT_COMMIT = "d675ba6d632dc03826f27940014d4cd672f7d910"
WITS_LICENSE = "BSL-1.1"
WITS_CHANGE_DATE = "2030-01-01"
WITS_CHANGE_LICENSE = "Apache-2.0"
# ``owner-meaning`` is a frozen v1/v2 wire identifier. Decision 0020 defines it
# as human-originated meaning admitted by WITS; it does not assign ownership of
# meaning to WITS. A successor requires a separately negotiated contract.
SUPPORTED_PROJECTION_KINDS = {"owner-meaning", "decision", "readiness", "ambiguity"}
FORBIDDEN_AUTHORITY_KEYS = {
    "approval", "authority", "continuation_payload", "create_task", "destination",
    "execute", "human_approval", "requested_actions", "route_task", "task_packet",
}
SHA256 = re.compile(r"^sha-256:[0-9a-f]{64}$")
WITS_PROJECTION_REF = re.compile(r"^wits-projection://[A-Za-z0-9._~/-]+$")
WITS_SCHEMA_REF = re.compile(r"^wits-contract://[A-Za-z0-9._~/-]+$")
DIAGNOSTIC_MESSAGES = {
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
    "required-extension-unsupported": "a required provider extension is unsupported",
    "unsupported-request": "the projection request does not satisfy the supported contract",
    "wits-projection-rejected": "WITS did not admit the projection",
    "provider-response-invalid": "the provider response is invalid or is not bound to this request",
}


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
    try:
        expected = dict(expected_revisions) if expected_revisions is not None else {
            item["record_id"]: item["revision_digest"] for item in refs
        }
    except (TypeError, ValueError) as error:
        raise ValueError("unsupported-request") from error
    if set(expected) != {item["record_id"] for item in refs}:
        raise ValueError("mixed-revision-context")
    try:
        evidence_refs = sorted(set(external_evidence_refs))
        request = {
            "schema_id": "artifact-memory/wits-projection-request/v1",
            "source_record_refs": refs,
            "expected_revisions": dict(sorted(expected.items())),
            "external_evidence_refs": evidence_refs,
            "projection_kind": projection_kind,
            "provider_contract": contract_anchor(),
            "authority_boundary": AUTHORITY_BOUNDARY,
        }
        validate(request, load_schema("adapters", "wits-projection-request.v1.schema.json"))
    except (TypeError, ValidationFailure) as error:
        raise ValueError("unsupported-request") from error
    return request


def _receipt(outcome: str, source_refs: list[dict[str, str]], request_digest: str, code: str | None = None) -> dict[str, Any]:
    diagnostics = [] if code is None else [{"code": code, "message": DIAGNOSTIC_MESSAGES[code]}]
    body = {
        "outcome": outcome,
        "source_record_refs": source_refs,
        "request_digest": request_digest,
        "authority_boundary": AUTHORITY_BOUNDARY,
        "diagnostics": diagnostics,
    }
    return receipt_with_digest("artifact-memory/wits-admission-receipt/v2", "wits-admission-receipt://", body)


def _optional_provider_extensions(provider_response: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    extensions = provider_response.get("extensions", {})
    bundle = {
        "schema_id": "artifact-memory/extension-bundle/v1",
        "extensions": extensions,
    }
    try:
        validate(bundle, load_schema("core", "extension-bundle.v1.schema.json"))
        preserved = preserve_extensions({}, bundle)
    except ValidationFailure:
        return None, "provider-response-invalid"
    except ExtensionFailure as error:
        if error.code == "required-extension-unsupported":
            return None, "required-extension-unsupported"
        return None, "provider-response-invalid"
    return deepcopy(preserved["extensions"]), None


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
    if source_failure:
        request = {"schema_id": "artifact-memory/wits-projection-request/v1", "source_record_refs": source_refs,
                   "construction_failure": source_failure}
    else:
        try:
            request = build_projection_request(
                records, projection_kind, expected_revisions=expected_revisions,
                external_evidence_refs=external_evidence_refs or (),
            )
        except ValueError as error:
            code = str(error)
            outcome = "mixed-revision-context" if code == "mixed-revision-context" else "unsupported"
            failed_request = {
                "schema_id": "artifact-memory/wits-projection-request/v1",
                "source_record_refs": source_refs,
                "construction_failure": code,
            }
            return None, _receipt(outcome, source_refs, _digest(failed_request),
                                  code if code in DIAGNOSTIC_MESSAGES else "unsupported-request")
    request_digest = _digest(request)
    failure: tuple[str, str] | None = None
    provider_extensions: dict[str, Any] = {}
    if source_failure:
        outcome = "mixed-revision-context" if source_failure == "mixed-revision-context" else "unsupported"
        failure = (outcome, source_failure)
    elif not authorized:
        failure = ("rejected", "not-authorized")
    elif not isinstance(provider_response, dict):
        failure = ("unsupported", "provider-response-invalid")
    elif _contains_authority(provider_response) or projection_kind in {"create-task", "route", "execute"}:
        failure = ("authority-bearing-request-rejected", "authority-boundary")
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
    else:
        required = {"admission", "request_digest", "projection_ref", "projection_schema_ref", "projection_digest"}
        allowed = required | {"extensions"}
        admission = provider_response.get("admission")
        response_digest = provider_response.get("request_digest")
        if admission not in {"admitted", "rejected"} or response_digest != request_digest:
            failure = ("unsupported", "provider-response-invalid")
        elif admission == "rejected":
            if set(provider_response) != {"admission", "request_digest"}:
                failure = ("unsupported", "provider-response-invalid")
            else:
                failure = ("rejected", "wits-projection-rejected")
        elif (
            not required.issubset(provider_response)
            or not set(provider_response).issubset(allowed)
            or any(not isinstance(provider_response.get(key), str) or not provider_response[key] for key in required)
            or SHA256.fullmatch(provider_response.get("projection_digest", "")) is None
            or WITS_PROJECTION_REF.fullmatch(provider_response.get("projection_ref", "")) is None
            or WITS_SCHEMA_REF.fullmatch(provider_response.get("projection_schema_ref", "")) is None
        ):
            failure = ("unsupported", "provider-response-invalid")
        else:
            provider_extensions, extension_failure = _optional_provider_extensions(provider_response)
            if extension_failure:
                failure = ("unsupported", extension_failure)
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
        **({"extensions": provider_extensions} if provider_extensions else {}),
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
    elif not isinstance(provider_response, dict):
        outcome, diagnostics = "unsupported", [{"code": "provider-response-invalid", "message": "provider response must be an object"}]
    elif _contains_authority(provider_response) or projection_kind in {"create-task", "route", "execute"}:
        outcome, diagnostics = "authority-bearing-request-rejected", [{"code": "authority-boundary", "message": "projection channel cannot carry task or execution authority"}]
    elif expected_revisions and any(expected_revisions.get(item["record_id"]) not in (None, item["revision_digest"]) for item in source_refs):
        outcome, diagnostics = "stale", [{"code": "stale-source-revision", "message": "source record revision does not match the requested revision"}]
    elif projection_kind not in SUPPORTED_PROJECTION_KINDS:
        outcome, diagnostics = "unsupported", [{"code": "projection-unsupported", "message": "projection kind is unsupported"}]
    elif any(
        not isinstance(provider_response.get(field), str) or not provider_response[field]
        for field in ("projection_ref", "projection_schema_ref")
    ) or not isinstance(provider_response.get("projection_digest"), str) or SHA256.fullmatch(
        provider_response.get("projection_digest", "")
    ) is None:
        outcome, diagnostics = "unsupported", [{"code": "provider-response-invalid", "message": "provider response projection references and digest are invalid"}]
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
