"""Stdlib-only informational context reader used by the #20 conformance proof."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any


AUTHORITY_BOUNDARY = "informational-only; no execution, routing, disclosure, or mutation authority"
SHA256 = re.compile(r"^sha-256:[0-9a-f]{64}$")
UTC_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
ARTIFACT_REF = re.compile(r"^artifact://[A-Za-z0-9._~/-]+$")
RECORD_ID = re.compile(r"^record://[A-Za-z0-9._~-]+/[A-Za-z0-9._~-]+$")


class ContextReaderFailure(Exception):
    pass


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ContextReaderFailure("duplicate object key")
        value[key] = item
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _matches(pattern: re.Pattern[str], value: Any) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or UTC_INSTANT.fullmatch(value) is None:
        raise ContextReaderFailure("invalid whole-second UTC instant")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContextReaderFailure("invalid whole-second UTC instant") from exc


def _validate_selection(selection: Any) -> datetime:
    required_fields = {
        "policy_id", "source_record_set_digest", "selected_record_ids", "selected_external_evidence",
        "exclusion_counts", "max_bytes", "selected_at", "freshness_policy", "redaction_policy",
        "artifact_policy", "disclosure",
    }
    optional_fields = {"revocation_policy", "revocation_receipt_refs"}
    if (
        not isinstance(selection, dict)
        or not required_fields.issubset(selection)
        or set(selection) - required_fields - optional_fields
        or not isinstance(selection.get("policy_id"), str)
        or not selection["policy_id"]
        or not _matches(SHA256, selection.get("source_record_set_digest"))
        or selection.get("freshness_policy") != "current-only/operator-asserted"
        or selection.get("redaction_policy") != "whole-record-exclusion/count-only-receipt"
        or selection.get("artifact_policy") != "references-only/separately-authorized-retrieval"
        or selection.get("disclosure") != "informational-only"
    ):
        raise ContextReaderFailure("selection receipt is invalid")
    exclusions = selection.get("exclusion_counts")
    if (
        not isinstance(exclusions, dict)
        or not {"not-authorized", "sensitivity", "freshness"}.issubset(exclusions)
        or set(exclusions) - {"not-authorized", "sensitivity", "freshness", "revocation"}
        or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in exclusions.values())
    ):
        raise ContextReaderFailure("selection exclusion counts are invalid")
    if "revocation" in exclusions and selection.get("revocation_policy") != "validated-tombstone-suppression":
        raise ContextReaderFailure("revocation selection policy is invalid")
    if "revocation_policy" in selection and selection["revocation_policy"] != "validated-tombstone-suppression":
        raise ContextReaderFailure("revocation selection policy is invalid")
    if "revocation_receipt_refs" in selection and (
        not isinstance(selection["revocation_receipt_refs"], list)
        or any(not isinstance(value, str) or not value for value in selection["revocation_receipt_refs"])
        or selection["revocation_receipt_refs"] != sorted(set(selection["revocation_receipt_refs"]))
    ):
        raise ContextReaderFailure("revocation receipt references are invalid")
    return _parse_utc(selection.get("selected_at"))


def _validate_evidence(item: Any) -> tuple[str, str, str]:
    base = {
        "provider_id", "provider_schema_id", "provider_record_id", "binding_ref",
        "evidence_packet_ref", "adapter_receipt_digest", "integrity_state", "coverage", "limitations",
    }
    optional = {"coverage_details", "rule_id", "evidence_tier"}
    if not isinstance(item, dict) or base - set(item) or set(item) - base - optional:
        raise ContextReaderFailure("external evidence fields are invalid")
    strings = base - {"limitations"}
    if (
        any(not isinstance(item[key], str) or not item[key] for key in strings)
        or not _matches(SHA256, item["adapter_receipt_digest"])
        or not isinstance(item["limitations"], list)
        or any(not isinstance(value, str) for value in item["limitations"])
        or item["limitations"] != sorted(item["limitations"])
    ):
        raise ContextReaderFailure("external evidence value is invalid")
    has_rule = "rule_id" in item
    has_tier = "evidence_tier" in item
    if has_rule != has_tier or (has_rule and any(not isinstance(item[key], str) or not item[key] for key in ("rule_id", "evidence_tier"))):
        raise ContextReaderFailure("external evidence rule and tier are invalid")
    if "coverage_details" in item:
        details = item["coverage_details"]
        if (
            not isinstance(details, dict)
            or set(details) != {"analysis_level", "build_status", "known_gaps"}
            or details.get("analysis_level") != item["coverage"]
            or not isinstance(details.get("build_status"), str)
            or not details["build_status"]
            or not isinstance(details.get("known_gaps"), list)
            or any(not isinstance(value, str) for value in details["known_gaps"])
            or details["known_gaps"] != sorted(details["known_gaps"])
        ):
            raise ContextReaderFailure("external evidence coverage details are invalid")
    return item["provider_id"], item["provider_record_id"], item["binding_ref"]


def recall_context(pack_json: bytes) -> dict[str, Any]:
    """Recall summaries and references without exposing any action capability."""
    try:
        pack = json.loads(pack_json, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, ContextReaderFailure) as exc:
        raise ContextReaderFailure("invalid context JSON") from exc
    required = {"schema_id", "pack_id", "authority_boundary", "records", "artifact_refs", "external_evidence", "selection_receipt"}
    if (
        not isinstance(pack, dict)
        or set(pack) != required
        or pack.get("schema_id") != "artifact-memory/context-pack/v2"
        or pack.get("authority_boundary") != AUTHORITY_BOUNDARY
    ):
        raise ContextReaderFailure("unsupported context contract")
    pack_id = pack.get("pack_id")
    body_without_id = {key: value for key, value in pack.items() if key != "pack_id"}
    if pack_id != "context-pack://" + hashlib.sha256(_canonical(body_without_id)).hexdigest():
        raise ContextReaderFailure("context pack identity mismatch")

    records = pack.get("records")
    artifact_refs = pack.get("artifact_refs")
    evidence = pack.get("external_evidence")
    selection = pack.get("selection_receipt")
    if not isinstance(records, list) or not isinstance(artifact_refs, list) or not isinstance(evidence, list):
        raise ContextReaderFailure("context collection shape is invalid")
    selected_at = _validate_selection(selection)

    recalled: list[dict[str, Any]] = []
    evidence_bindings: set[str] = set()
    for record in records:
        fields = {"record_id", "revision_digest", "summary", "labels", "sensitivity", "freshness", "external_evidence_bindings"}
        if not isinstance(record, dict) or set(record) != fields:
            raise ContextReaderFailure("context record shape is invalid")
        bindings = record["external_evidence_bindings"]
        if (
            not isinstance(record["record_id"], str)
            or RECORD_ID.fullmatch(record["record_id"]) is None
            or not isinstance(record["summary"], str)
            or not record["summary"]
            or not _matches(SHA256, record.get("revision_digest"))
            or not isinstance(record["labels"], list)
            or any(not isinstance(label, str) for label in record["labels"])
            or record["labels"] != sorted(record["labels"])
            or record["sensitivity"] not in {"public", "private", "restricted"}
            or not isinstance(bindings, list)
            or any(not isinstance(binding, str) or not binding for binding in bindings)
            or bindings != sorted(set(bindings))
        ):
            raise ContextReaderFailure("context record identity is invalid")
        freshness = record.get("freshness")
        if (
            not isinstance(freshness, dict)
            or set(freshness) != {"status", "assessed_at", "basis"}
            or freshness.get("status") != "current"
            or not isinstance(freshness.get("basis"), str)
            or not freshness["basis"]
            or _parse_utc(freshness.get("assessed_at")) > selected_at
        ):
            raise ContextReaderFailure("non-current context record rejected")
        evidence_bindings.update(bindings)
        recalled.append({"record_id": record["record_id"], "revision_digest": record["revision_digest"], "summary": record["summary"]})
    record_ids = [item["record_id"] for item in recalled]
    if record_ids != sorted(set(record_ids)) or selection.get("selected_record_ids") != record_ids:
        raise ContextReaderFailure("context record ordering or receipt binding is invalid")
    if artifact_refs != sorted(set(artifact_refs)) or any(
        not isinstance(item, str) or ARTIFACT_REF.fullmatch(item) is None
        for item in artifact_refs
    ):
        raise ContextReaderFailure("artifact references are invalid")

    evidence_values = [_validate_evidence(item) for item in evidence]
    evidence_keys = [(provider_id, record_id) for provider_id, record_id, _ in evidence_values]
    if evidence_keys != sorted(set(evidence_keys)) or any(binding not in evidence_bindings for _, _, binding in evidence_values):
        raise ContextReaderFailure("external evidence ordering, uniqueness, or binding is invalid")
    selected_evidence = [
        {"provider_id": provider_id, "provider_record_id": provider_record_id}
        for provider_id, provider_record_id in evidence_keys
    ]
    if selection.get("selected_external_evidence") != selected_evidence:
        raise ContextReaderFailure("external evidence receipt binding is invalid")
    max_bytes = selection.get("max_bytes")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or len(_canonical(pack)) > max_bytes:
        raise ContextReaderFailure("context pack exceeds its declared byte bound")

    body = {
        "outcome": "recalled",
        "context_pack_id": pack_id,
        "records": recalled,
        "artifact_refs": artifact_refs,
        "external_evidence_refs": selected_evidence,
        "artifact_retrieval": "not-attempted/separately-authorized",
        "mutation_authority": "absent",
        "disclosure_authority": "absent",
        "execution_authority": "absent",
    }
    return {
        "schema_id": "artifact-memory/context-recall-receipt/v1",
        "receipt_id": "context-recall-receipt://" + hashlib.sha256(_canonical(body)).hexdigest(),
        **body,
    }
