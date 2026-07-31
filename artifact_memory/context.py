"""Deterministic, reference-only informational context pack export."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable

from .validator import ValidationFailure, validate
from .projection import _canonical, _knowledge_schema
from .schema_resources import load_schema


AUTHORITY_BOUNDARY = "informational-only; no execution, routing, disclosure, or mutation authority"
SENSITIVITY_RANK = {"public": 0, "private": 1, "restricted": 2}


class ContextFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _normalize_external_evidence(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ContextFailure("external-evidence-invalid", "external evidence must be an object")
    required = (
        "provider_id",
        "provider_schema_id",
        "provider_record_id",
        "evidence_packet_ref",
        "adapter_receipt_digest",
        "integrity_state",
        "coverage",
        "limitations",
    )
    if any(key not in item for key in required):
        raise ContextFailure("external-evidence-invalid", "external evidence is missing a required field")
    limitations = item["limitations"]
    if not isinstance(limitations, list) or any(not isinstance(value, str) for value in limitations):
        raise ContextFailure("external-evidence-invalid", "external evidence limitations must be an array of strings")
    coverage = item["coverage"]
    if isinstance(coverage, dict):
        required_coverage = ("analysis_level", "build_status", "known_gaps")
        if any(key not in coverage for key in required_coverage):
            raise ContextFailure("external-evidence-invalid", "external evidence coverage is incomplete")
        known_gaps = coverage["known_gaps"]
        if not isinstance(known_gaps, list) or any(not isinstance(value, str) for value in known_gaps):
            raise ContextFailure("external-evidence-invalid", "external evidence known gaps must be an array of strings")
        coverage_details = {
            "analysis_level": coverage["analysis_level"],
            "build_status": coverage["build_status"],
            "known_gaps": sorted(known_gaps),
        }
    elif not isinstance(coverage, str):
        raise ContextFailure("external-evidence-invalid", "external evidence coverage must be a legacy string or structured object")
    normalized = {
        "provider_id": item["provider_id"],
        "provider_schema_id": item["provider_schema_id"],
        "provider_record_id": item["provider_record_id"],
        "evidence_packet_ref": item["evidence_packet_ref"],
        "adapter_receipt_digest": item["adapter_receipt_digest"],
        "integrity_state": item["integrity_state"],
        "coverage": coverage if isinstance(coverage, str) else coverage_details["analysis_level"],
        "limitations": sorted(limitations),
    }
    if isinstance(coverage, dict):
        normalized["coverage_details"] = coverage_details
    has_rule = "rule_id" in item
    has_tier = "evidence_tier" in item
    if has_rule != has_tier:
        raise ContextFailure("external-evidence-invalid", "external evidence rule and tier must appear together")
    if has_rule:
        normalized["rule_id"] = item["rule_id"]
        normalized["evidence_tier"] = item["evidence_tier"]
    return normalized


def _digest(value: bytes) -> str:
    return "sha-256:" + hashlib.sha256(value).hexdigest()


def export_context(records: Iterable[dict[str, Any]], external_evidence: Iterable[dict[str, Any]] = (), allowed_sensitivity: str = "public", max_bytes: int = 32_768, freshness: str = "selection-time") -> dict[str, Any]:
    if allowed_sensitivity not in SENSITIVITY_RANK:
        raise ContextFailure("sensitivity-policy-unsupported", "sensitivity policy is unsupported")
    ordered = sorted(records, key=lambda record: record["record_id"])
    for record in ordered:
        validate(record, _knowledge_schema())
    source_lines = b"".join(_canonical(record) + b"\n" for record in ordered)
    source_digest = _digest(source_lines)
    selected = []
    redacted = []
    artifact_refs: set[str] = set()
    for record in ordered:
        sensitivity = record.get("sensitivity", "private")
        if SENSITIVITY_RANK[sensitivity] > SENSITIVITY_RANK[allowed_sensitivity]:
            redacted.append(record["record_id"])
            continue
        selected.append({"record_id": record["record_id"], "revision_digest": _digest(_canonical(record)), "summary": record["meaning"]["summary"], "labels": record["meaning"].get("labels", []), "sensitivity": sensitivity})
        artifact_refs.update(record.get("artifact_refs", []))
    evidence = []
    for item in external_evidence:
        evidence.append(_normalize_external_evidence(item))
    evidence.sort(key=lambda item: (item["provider_id"], item["provider_record_id"]))
    selection = {"selector_id": "artifact-memory/reference-cli/v0", "source_record_set_digest": source_digest, "selected_record_ids": [item["record_id"] for item in selected], "redacted_record_ids": redacted, "max_bytes": max_bytes, "freshness": freshness, "disclosure": "informational-only"}
    body = {"schema_id": "artifact-memory/context-pack/v1", "authority_boundary": AUTHORITY_BOUNDARY, "records": selected, "artifact_refs": sorted(artifact_refs), "external_evidence": evidence, "selection_receipt": selection}
    pack_id = "context-pack://" + hashlib.sha256(_canonical(body)).hexdigest()
    result = {**body, "pack_id": pack_id}
    try:
        validate(result, load_schema("core", "context-pack.v1.schema.json"))
    except ValidationFailure as exc:
        raise ContextFailure("external-evidence-invalid", "context pack input did not satisfy the export contract") from exc
    if len(_canonical(result)) > max_bytes:
        raise ContextFailure("size-limit-exceeded", "context pack exceeds the declared bound")
    return result
