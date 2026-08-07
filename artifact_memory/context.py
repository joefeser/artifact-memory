"""Deterministic, reference-only informational context pack export."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any, Iterable, Mapping

from .extensions import ExtensionFailure, preserve_extensions
from .knowledge import knowledge_schema
from .projection import _canonical
from .schema_resources import load_schema
from .validator import ValidationFailure, validate


AUTHORITY_BOUNDARY = "informational-only; no execution, routing, disclosure, or mutation authority"
SENSITIVITY_RANK = {"public": 0, "private": 1, "restricted": 2}
UTC_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256 = re.compile(r"^sha-256:[0-9a-f]{64}$")


class ContextFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _digest(value: bytes) -> str:
    return "sha-256:" + hashlib.sha256(value).hexdigest()


def _parse_utc(value: Any, code: str, message: str) -> datetime:
    if not isinstance(value, str) or UTC_INSTANT.fullmatch(value) is None:
        raise ContextFailure(code, message)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContextFailure(code, message) from exc


def build_selection_policy(
    record_ids: Iterable[str],
    *,
    selected_at: str,
    freshness_basis: str,
    authorized_evidence: Iterable[tuple[str, str]] = (),
    stale_record_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Build shared deterministic selection arguments for CLI and fixtures."""
    records = list(record_ids)
    stale = set(stale_record_ids)
    return {
        "authorized_record_ids": records,
        "authorized_evidence": list(authorized_evidence),
        "freshness_by_record": {
            record_id: {
                "status": "stale" if record_id in stale else "current",
                "assessed_at": selected_at,
                "basis": freshness_basis,
            }
            for record_id in records
        },
        "selected_at": selected_at,
    }


def _normalize_freshness(value: Any, record_id: str, selected_at: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"status", "assessed_at", "basis"}:
        raise ContextFailure("freshness-invalid", f"freshness assertion is invalid for {record_id}")
    if value.get("status") != "current":
        raise ContextFailure("freshness-not-current", f"record is not current under the selection policy: {record_id}")
    assessed_at = value.get("assessed_at")
    basis = value.get("basis")
    if _parse_utc(assessed_at, "freshness-invalid", f"freshness assessment is invalid for {record_id}") > _parse_utc(
        selected_at, "selection-time-invalid", "selection time is not a valid UTC instant"
    ):
        raise ContextFailure("freshness-invalid", f"freshness assessment is invalid for {record_id}")
    if not isinstance(basis, str) or not basis:
        raise ContextFailure("freshness-invalid", f"freshness basis is invalid for {record_id}")
    return {"status": "current", "assessed_at": assessed_at, "basis": basis}


def _normalize_external_evidence(item: Any) -> dict[str, Any]:
    required = {
        "provider_id", "provider_schema_id", "provider_record_id", "binding_ref",
        "evidence_packet_ref", "adapter_receipt_digest", "integrity_state", "coverage", "limitations",
    }
    optional = {"rule_id", "evidence_tier"}
    if not isinstance(item, dict) or required - set(item) or set(item) - required - optional:
        raise ContextFailure("external-evidence-invalid", "external evidence fields are invalid")
    string_fields = required - {"coverage", "limitations"}
    if any(not isinstance(item[key], str) or not item[key] for key in string_fields):
        raise ContextFailure("external-evidence-invalid", "external evidence identity fields must be non-empty strings")
    if SHA256.fullmatch(item["adapter_receipt_digest"]) is None:
        raise ContextFailure("external-evidence-invalid", "adapter receipt digest is invalid")
    limitations = item["limitations"]
    if not isinstance(limitations, list) or any(not isinstance(value, str) for value in limitations):
        raise ContextFailure("external-evidence-invalid", "external evidence limitations must be an array of strings")
    coverage = item["coverage"]
    if isinstance(coverage, dict):
        if set(coverage) != {"analysis_level", "build_status", "known_gaps"}:
            raise ContextFailure("external-evidence-invalid", "external evidence coverage is incomplete")
        known_gaps = coverage["known_gaps"]
        if (
            not isinstance(coverage["analysis_level"], str) or not coverage["analysis_level"]
            or not isinstance(coverage["build_status"], str) or not coverage["build_status"]
            or not isinstance(known_gaps, list)
            or any(not isinstance(value, str) for value in known_gaps)
        ):
            raise ContextFailure("external-evidence-invalid", "external evidence coverage is invalid")
        coverage_details = {
            "analysis_level": coverage["analysis_level"],
            "build_status": coverage["build_status"],
            "known_gaps": sorted(known_gaps),
        }
    elif not isinstance(coverage, str) or not coverage:
        raise ContextFailure("external-evidence-invalid", "external evidence coverage must be a non-empty string or structured object")
    normalized = {
        **{key: item[key] for key in string_fields},
        "coverage": coverage if isinstance(coverage, str) else coverage_details["analysis_level"],
        "limitations": sorted(limitations),
    }
    if isinstance(coverage, dict):
        normalized["coverage_details"] = coverage_details
    has_rule = "rule_id" in item
    has_tier = "evidence_tier" in item
    if has_rule != has_tier or (has_rule and any(not isinstance(item[key], str) or not item[key] for key in optional)):
        raise ContextFailure("external-evidence-invalid", "external evidence rule and tier must be non-empty strings together")
    if has_rule:
        normalized["rule_id"] = item["rule_id"]
        normalized["evidence_tier"] = item["evidence_tier"]
    return normalized


def _authorized_records(values: Iterable[Any]) -> set[str]:
    materialized = list(values)
    if any(not isinstance(value, str) for value in materialized):
        raise ContextFailure("selection-policy-invalid", "authorized record identities must be strings")
    return set(materialized)


def _authorized_evidence(values: Iterable[Any]) -> set[tuple[str, str]]:
    normalized: set[tuple[str, str]] = set()
    for value in values:
        if (
            not isinstance(value, (list, tuple))
            or len(value) != 2
            or not all(isinstance(part, str) and part for part in value)
        ):
            raise ContextFailure("selection-policy-invalid", "authorized external evidence keys must be provider and record identity pairs")
        normalized.add((value[0], value[1]))
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
    revocation_receipts: Iterable[dict[str, Any]] = (),
    supported_required_extensions: Iterable[tuple[str, str]] = (),
) -> dict[str, Any]:
    """Export only explicitly authorized, current records and evidence references."""
    if allowed_sensitivity not in SENSITIVITY_RANK:
        raise ContextFailure("sensitivity-policy-unsupported", "sensitivity policy is unsupported")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ContextFailure("size-limit-invalid", "context pack byte bound must be a positive integer")
    _parse_utc(selected_at, "selection-time-invalid", "selection time is not a valid whole-second UTC instant")
    if not isinstance(policy_id, str) or not policy_id:
        raise ContextFailure("selection-policy-invalid", "selection policy identity is required")
    supported_required_extensions = list(supported_required_extensions)
    record_list = list(records)
    for record in record_list:
        validate(record, knowledge_schema(record))
        required_extensions = {
            identifier: declaration
            for identifier, declaration in record.get("extensions", {}).items()
            if isinstance(declaration, dict) and declaration.get("required") is True
        }
        if required_extensions:
            try:
                preserve_extensions(
                    {"extensions": {}},
                    {"schema_id": "artifact-memory/extension-bundle/v1", "extensions": required_extensions},
                    supported_required_extensions,
                )
            except ExtensionFailure as exc:
                raise ContextFailure(exc.code, exc.message) from exc
    ordered = sorted(record_list, key=lambda record: record["record_id"])
    record_ids = [record["record_id"] for record in ordered]
    if len(record_ids) != len(set(record_ids)):
        raise ContextFailure("duplicate-record", "context input contains duplicate record identities")
    authorized_records = _authorized_records(authorized_record_ids)
    if authorized_records - set(record_ids):
        raise ContextFailure("authorized-record-unavailable", "an authorized record was not supplied")

    from .revocation import validated_suppressions

    suppression_bindings = validated_suppressions(ordered, revocation_receipts)
    revoked = set(suppression_bindings)
    revocation_receipt_refs = sorted(suppression_bindings.values())

    source_lines = b"".join(_canonical(record) + b"\n" for record in ordered)
    selected: list[dict[str, Any]] = []
    selected_evidence_bindings: set[str] = set()
    revoked_evidence_bindings: set[str] = set()
    exclusions = {"not-authorized": 0, "sensitivity": 0, "freshness": 0}
    if revoked:
        exclusions["revocation"] = 0
    artifact_refs: set[str] = set()
    for record in ordered:
        record_id = record["record_id"]
        if record_id not in authorized_records:
            exclusions["not-authorized"] += 1
            continue
        if record_id in revoked:
            exclusions["revocation"] += 1
            revoked_evidence_bindings.update(
                relationship["target_ref"]
                for relationship in record.get("relationships", [])
                if relationship["type"] == "supported-by-external-evidence"
            )
            continue
        sensitivity = record.get("sensitivity", "private")
        if SENSITIVITY_RANK[sensitivity] > SENSITIVITY_RANK[allowed_sensitivity]:
            exclusions["sensitivity"] += 1
            continue
        freshness_value = freshness_by_record.get(record_id)
        if freshness_value is None or (isinstance(freshness_value, dict) and freshness_value.get("status") != "current"):
            exclusions["freshness"] += 1
            continue
        freshness = _normalize_freshness(freshness_value, record_id, selected_at)
        bindings = sorted({
            relationship["target_ref"]
            for relationship in record.get("relationships", [])
            if relationship["type"] == "supported-by-external-evidence"
        })
        selected.append({
            "record_id": record_id,
            "revision_digest": _digest(_canonical(record)),
            "summary": record["meaning"]["summary"],
            "labels": sorted(record["meaning"].get("labels", [])),
            "sensitivity": sensitivity,
            "freshness": freshness,
            "external_evidence_bindings": bindings,
        })
        artifact_refs.update(record.get("artifact_refs", []))
        selected_evidence_bindings.update(bindings)

    authorized_evidence_keys = _authorized_evidence(authorized_evidence)
    evidence = [_normalize_external_evidence(item) for item in external_evidence]
    evidence.sort(key=lambda item: (item["provider_id"], item["provider_record_id"]))
    evidence_keys = [(item["provider_id"], item["provider_record_id"]) for item in evidence]
    if len(evidence_keys) != len(set(evidence_keys)):
        raise ContextFailure("duplicate-external-evidence", "context input contains duplicate provider and record identity pairs")
    if authorized_evidence_keys - set(evidence_keys):
        raise ContextFailure("authorized-evidence-unavailable", "authorized external evidence was not supplied")
    selected_evidence = [item for item in evidence if (item["provider_id"], item["provider_record_id"]) in authorized_evidence_keys]
    unbound_evidence = [item for item in selected_evidence if item["binding_ref"] not in selected_evidence_bindings]
    if any(item["binding_ref"] not in revoked_evidence_bindings for item in unbound_evidence):
        raise ContextFailure("external-evidence-unbound", "authorized external evidence is not bound by a selected record")
    selected_evidence = [item for item in selected_evidence if item["binding_ref"] in selected_evidence_bindings]

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
    if revoked:
        selection["revocation_policy"] = "validated-tombstone-suppression"
        selection["revocation_receipt_refs"] = revocation_receipt_refs
    pack_version = "v3" if revoked else "v2"
    body = {
        "schema_id": f"artifact-memory/context-pack/{pack_version}",
        "authority_boundary": AUTHORITY_BOUNDARY,
        "records": selected,
        "artifact_refs": sorted(artifact_refs),
        "external_evidence": selected_evidence,
        "selection_receipt": selection,
    }
    result = {**body, "pack_id": "context-pack://" + hashlib.sha256(_canonical(body)).hexdigest()}
    try:
        validate(result, load_schema("core", f"context-pack.{pack_version}.schema.json"))
    except ValidationFailure as exc:
        raise ContextFailure("context-pack-invalid", "context pack input did not satisfy the export contract") from exc
    if len(_canonical(result)) > max_bytes:
        raise ContextFailure("size-limit-exceeded", "context pack exceeds the declared bound")
    return result
