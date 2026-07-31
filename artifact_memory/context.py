"""Deterministic, reference-only informational context pack export."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any, Iterable, Mapping

from .projection import _canonical, _knowledge_schema
from .schema_resources import load_schema
from .validator import ValidationFailure, validate


AUTHORITY_BOUNDARY = "informational-only; no execution, routing, disclosure, or mutation authority"
SENSITIVITY_RANK = {"public": 0, "private": 1, "restricted": 2}
UTC_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class ContextFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _digest(value: bytes) -> str:
    return "sha-256:" + hashlib.sha256(value).hexdigest()


def _normalize_freshness(value: Any, record_id: str, selected_at: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"status", "assessed_at", "basis"}:
        raise ContextFailure("freshness-invalid", f"freshness assertion is invalid for {record_id}")
    if value.get("status") != "current":
        raise ContextFailure("freshness-not-current", f"record is not current under the selection policy: {record_id}")
    assessed_at = value.get("assessed_at")
    basis = value.get("basis")
    if not isinstance(assessed_at, str) or UTC_INSTANT.fullmatch(assessed_at) is None or assessed_at > selected_at:
        raise ContextFailure("freshness-invalid", f"freshness assessment is invalid for {record_id}")
    if not isinstance(basis, str) or not basis:
        raise ContextFailure("freshness-invalid", f"freshness basis is invalid for {record_id}")
    return {"status": "current", "assessed_at": assessed_at, "basis": basis}


def _normalize_external_evidence(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ContextFailure("external-evidence-invalid", "external evidence must be an object")
    required = (
        "provider_id",
        "provider_schema_id",
        "provider_record_id",
        "binding_ref",
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
        "binding_ref": item["binding_ref"],
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


def export_context(
    records: Iterable[dict[str, Any]],
    external_evidence: Iterable[dict[str, Any]] = (),
    allowed_sensitivity: str = "public",
    max_bytes: int = 32_768,
    *,
    authorized_record_ids: Iterable[str],
    authorized_evidence: Iterable[tuple[str, str]] = (),
    freshness_by_record: Mapping[str, dict[str, str]],
    selected_at: str,
    policy_id: str = "artifact-memory/context-selection/v1",
) -> dict[str, Any]:
    """Export only explicitly authorized, current records and evidence references."""
    if allowed_sensitivity not in SENSITIVITY_RANK:
        raise ContextFailure("sensitivity-policy-unsupported", "sensitivity policy is unsupported")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ContextFailure("size-limit-invalid", "context pack byte bound must be a positive integer")
    if not isinstance(selected_at, str) or UTC_INSTANT.fullmatch(selected_at) is None:
        raise ContextFailure("selection-time-invalid", "selection time must be a whole-second UTC instant")
    try:
        datetime.fromisoformat(selected_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContextFailure("selection-time-invalid", "selection time is not a valid UTC instant") from exc
    if not isinstance(policy_id, str) or not policy_id:
        raise ContextFailure("selection-policy-invalid", "selection policy identity is required")

    record_list = list(records)
    for record in record_list:
        validate(record, _knowledge_schema())
    ordered = sorted(record_list, key=lambda record: record["record_id"])
    record_ids = [record["record_id"] for record in ordered]
    if len(record_ids) != len(set(record_ids)):
        raise ContextFailure("duplicate-record", "context input contains duplicate record identities")
    authorized_records = set(authorized_record_ids)
    if any(not isinstance(record_id, str) for record_id in authorized_records):
        raise ContextFailure("selection-policy-invalid", "authorized record identities must be strings")
    unknown_authorizations = authorized_records - set(record_ids)
    if unknown_authorizations:
        raise ContextFailure("authorized-record-unavailable", "an authorized record was not supplied")

    source_lines = b"".join(_canonical(record) + b"\n" for record in ordered)
    selected: list[dict[str, Any]] = []
    selected_evidence_bindings: set[str] = set()
    exclusions = {"not-authorized": 0, "sensitivity": 0, "freshness": 0}
    artifact_refs: set[str] = set()
    for record in ordered:
        record_id = record["record_id"]
        if record_id not in authorized_records:
            exclusions["not-authorized"] += 1
            continue
        sensitivity = record.get("sensitivity", "private")
        if SENSITIVITY_RANK[sensitivity] > SENSITIVITY_RANK[allowed_sensitivity]:
            exclusions["sensitivity"] += 1
            continue
        freshness_value = freshness_by_record.get(record_id)
        if freshness_value is None or (isinstance(freshness_value, dict) and freshness_value.get("status") != "current"):
            exclusions["freshness"] += 1
            continue
        if not isinstance(freshness_value, dict):
            raise ContextFailure("freshness-invalid", f"freshness assertion is invalid for {record_id}")
        freshness = _normalize_freshness(freshness_value, record_id, selected_at)
        selected.append(
            {
                "record_id": record_id,
                "revision_digest": _digest(_canonical(record)),
                "summary": record["meaning"]["summary"],
                "labels": sorted(record["meaning"].get("labels", [])),
                "sensitivity": sensitivity,
                "freshness": freshness,
            }
        )
        artifact_refs.update(record.get("artifact_refs", []))
        selected_evidence_bindings.update(
            relationship["target_ref"]
            for relationship in record.get("relationships", [])
            if relationship["type"] == "supported-by-external-evidence"
        )

    authorized_evidence_keys = set(authorized_evidence)
    if any(
        not isinstance(key, tuple)
        or len(key) != 2
        or not all(isinstance(value, str) and value for value in key)
        for key in authorized_evidence_keys
    ):
        raise ContextFailure("selection-policy-invalid", "authorized external evidence keys must be provider and record identity pairs")
    evidence = [_normalize_external_evidence(item) for item in external_evidence]
    evidence.sort(key=lambda item: (item["provider_id"], item["provider_record_id"]))
    evidence_keys = [(item["provider_id"], item["provider_record_id"]) for item in evidence]
    if len(evidence_keys) != len(set(evidence_keys)):
        raise ContextFailure("duplicate-external-evidence", "context input contains duplicate provider and record identity pairs")
    if authorized_evidence_keys - set(evidence_keys):
        raise ContextFailure("authorized-evidence-unavailable", "authorized external evidence was not supplied")
    selected_evidence = [
        item
        for item in evidence
        if (item["provider_id"], item["provider_record_id"]) in authorized_evidence_keys
    ]
    if any(item["binding_ref"] not in selected_evidence_bindings for item in selected_evidence):
        raise ContextFailure("external-evidence-unbound", "authorized external evidence is not bound by a selected record")

    selection = {
        "policy_id": policy_id,
        "source_record_set_digest": _digest(source_lines),
        "selected_record_ids": [item["record_id"] for item in selected],
        "selected_external_evidence": [
            {"provider_id": item["provider_id"], "provider_record_id": item["provider_record_id"]}
            for item in selected_evidence
        ],
        "exclusion_counts": exclusions,
        "max_bytes": max_bytes,
        "selected_at": selected_at,
        "freshness_policy": "current-only/operator-asserted",
        "redaction_policy": "whole-record-exclusion/count-only-receipt",
        "artifact_policy": "references-only/separately-authorized-retrieval",
        "disclosure": "informational-only",
    }
    body = {
        "schema_id": "artifact-memory/context-pack/v1",
        "authority_boundary": AUTHORITY_BOUNDARY,
        "records": selected,
        "artifact_refs": sorted(artifact_refs),
        "external_evidence": selected_evidence,
        "selection_receipt": selection,
    }
    result = {**body, "pack_id": "context-pack://" + hashlib.sha256(_canonical(body)).hexdigest()}
    try:
        validate(result, load_schema("core", "context-pack.v1.schema.json"))
    except ValidationFailure as exc:
        raise ContextFailure("context-pack-invalid", "context pack input did not satisfy the export contract") from exc
    if len(_canonical(result)) > max_bytes:
        raise ContextFailure("size-limit-exceeded", "context pack exceeds the declared bound")
    return result
