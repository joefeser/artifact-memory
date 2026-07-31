"""Stdlib-only informational context reader used by the #20 conformance proof."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


AUTHORITY_BOUNDARY = "informational-only; no execution, routing, disclosure, or mutation authority"
SHA256 = re.compile(r"^sha-256:[0-9a-f]{64}$")
UTC_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


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


def _digest(value: bytes) -> str:
    return "sha-256:" + hashlib.sha256(value).hexdigest()


def recall_context(pack_json: bytes) -> dict[str, Any]:
    """Recall summaries and references without exposing any action capability."""
    try:
        pack = json.loads(pack_json, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, ContextReaderFailure) as exc:
        raise ContextReaderFailure("invalid context JSON") from exc
    if not isinstance(pack, dict):
        raise ContextReaderFailure("context pack must be an object")
    required = {"schema_id", "pack_id", "authority_boundary", "records", "artifact_refs", "external_evidence", "selection_receipt"}
    if set(pack) != required or pack.get("schema_id") != "artifact-memory/context-pack/v1" or pack.get("authority_boundary") != AUTHORITY_BOUNDARY:
        raise ContextReaderFailure("unsupported context contract")
    pack_id = pack.get("pack_id")
    body = {key: value for key, value in pack.items() if key != "pack_id"}
    if pack_id != "context-pack://" + hashlib.sha256(_canonical(body)).hexdigest():
        raise ContextReaderFailure("context pack identity mismatch")

    records = pack.get("records")
    artifact_refs = pack.get("artifact_refs")
    evidence = pack.get("external_evidence")
    selection = pack.get("selection_receipt")
    if not isinstance(records, list) or not isinstance(artifact_refs, list) or not isinstance(evidence, list) or not isinstance(selection, dict):
        raise ContextReaderFailure("context collection shape is invalid")
    recalled: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict) or set(record) != {"record_id", "revision_digest", "summary", "labels", "sensitivity", "freshness"}:
            raise ContextReaderFailure("context record shape is invalid")
        if (
            not isinstance(record["record_id"], str)
            or not isinstance(record["summary"], str)
            or not record["summary"]
            or SHA256.fullmatch(record.get("revision_digest", "")) is None
            or not isinstance(record["labels"], list)
            or any(not isinstance(label, str) for label in record["labels"])
            or record["labels"] != sorted(record["labels"])
            or record["sensitivity"] not in {"public", "private", "restricted"}
        ):
            raise ContextReaderFailure("context record identity is invalid")
        freshness = record.get("freshness")
        if (
            not isinstance(freshness, dict)
            or set(freshness) != {"status", "assessed_at", "basis"}
            or freshness.get("status") != "current"
            or not isinstance(freshness.get("assessed_at"), str)
            or UTC_INSTANT.fullmatch(freshness["assessed_at"]) is None
            or not isinstance(freshness.get("basis"), str)
            or not freshness["basis"]
        ):
            raise ContextReaderFailure("non-current context record rejected")
        recalled.append({"record_id": record["record_id"], "revision_digest": record["revision_digest"], "summary": record["summary"]})
    record_ids = [item["record_id"] for item in recalled]
    if record_ids != sorted(record_ids) or selection.get("selected_record_ids") != record_ids:
        raise ContextReaderFailure("context record ordering or receipt binding is invalid")
    if artifact_refs != sorted(artifact_refs) or any(not isinstance(item, str) or not item.startswith("artifact://") for item in artifact_refs):
        raise ContextReaderFailure("artifact references are invalid")
    selection_fields = {
        "policy_id", "source_record_set_digest", "selected_record_ids", "selected_external_evidence",
        "exclusion_counts", "max_bytes", "selected_at", "freshness_policy", "redaction_policy",
        "artifact_policy", "disclosure",
    }
    if (
        set(selection) != selection_fields
        or not isinstance(selection.get("policy_id"), str)
        or not selection["policy_id"]
        or SHA256.fullmatch(selection.get("source_record_set_digest", "")) is None
        or selection.get("freshness_policy") != "current-only/operator-asserted"
        or selection.get("redaction_policy") != "whole-record-exclusion/count-only-receipt"
        or selection.get("artifact_policy") != "references-only/separately-authorized-retrieval"
        or selection.get("disclosure") != "informational-only"
        or not isinstance(selection.get("selected_at"), str)
        or UTC_INSTANT.fullmatch(selection["selected_at"]) is None
    ):
        raise ContextReaderFailure("selection receipt is invalid")
    exclusions = selection.get("exclusion_counts")
    if (
        not isinstance(exclusions, dict)
        or set(exclusions) != {"not-authorized", "sensitivity", "freshness"}
        or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in exclusions.values())
    ):
        raise ContextReaderFailure("selection exclusion counts are invalid")
    evidence_keys = []
    for item in evidence:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("provider_id"), str)
            or not item["provider_id"]
            or not isinstance(item.get("provider_record_id"), str)
            or not item["provider_record_id"]
            or not isinstance(item.get("provider_schema_id"), str)
            or not item["provider_schema_id"]
            or not isinstance(item.get("binding_ref"), str)
            or not item["binding_ref"]
            or SHA256.fullmatch(item.get("adapter_receipt_digest", "")) is None
        ):
            raise ContextReaderFailure("external evidence reference is invalid")
        evidence_keys.append((item["provider_id"], item["provider_record_id"]))
    selected_evidence = [
        {"provider_id": provider_id, "provider_record_id": provider_record_id}
        for provider_id, provider_record_id in evidence_keys
    ]
    if evidence_keys != sorted(evidence_keys) or selection.get("selected_external_evidence") != selected_evidence:
        raise ContextReaderFailure("external evidence ordering or receipt binding is invalid")
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
