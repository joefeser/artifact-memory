"""Deterministic, reference-only informational context pack export."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable

from .validator import validate
from .projection import _canonical, _knowledge_schema


AUTHORITY_BOUNDARY = "informational-only; no execution, routing, disclosure, or mutation authority"
SENSITIVITY_RANK = {"public": 0, "private": 1, "restricted": 2}


class ContextFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


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
        evidence.append(
            {
                "provider_id": item["provider_id"],
                "provider_schema_id": item["provider_schema_id"],
                "provider_record_id": item["provider_record_id"],
                "evidence_packet_ref": item["evidence_packet_ref"],
                "adapter_receipt_digest": item["adapter_receipt_digest"],
                "integrity_state": item["integrity_state"],
                "rule_id": item["rule_id"],
                "evidence_tier": item["evidence_tier"],
                "coverage": item["coverage"],
                "limitations": sorted(item["limitations"]),
            }
        )
    evidence.sort(key=lambda item: (item["provider_id"], item["provider_record_id"]))
    selection = {"selector_id": "artifact-memory/reference-cli/v0", "source_record_set_digest": source_digest, "selected_record_ids": [item["record_id"] for item in selected], "redacted_record_ids": redacted, "max_bytes": max_bytes, "freshness": freshness, "disclosure": "informational-only"}
    body = {"schema_id": "artifact-memory/context-pack/v1", "authority_boundary": AUTHORITY_BOUNDARY, "records": selected, "artifact_refs": sorted(artifact_refs), "external_evidence": evidence, "selection_receipt": selection}
    pack_id = "context-pack://" + hashlib.sha256(_canonical(body)).hexdigest()
    result = {**body, "pack_id": pack_id}
    if len(_canonical(result)) > max_bytes:
        raise ContextFailure("size-limit-exceeded", "context pack exceeds the declared bound")
    return result
