"""Adapter manifest validation and machine-readable receipts."""

from __future__ import annotations

import hashlib
from typing import Any

from .canonical import canonical_bytes

AUTHORITY_BOUNDARY = "record contents do not authorize adapter execution"


_canonical = canonical_bytes


def receipt(manifest: dict[str, Any], outcome: str, diagnostics: list[dict[str, str]] | None = None) -> dict[str, Any]:
    adapter_ref = manifest.get("adapter_id", "adapter://unknown/unknown")
    body = {"adapter_ref": adapter_ref, "outcome": outcome, "authority_boundary": AUTHORITY_BOUNDARY, "diagnostics": diagnostics or []}
    return {"schema_id": "artifact-memory/adapter-receipt/v1", "receipt_id": "adapter-receipt://" + hashlib.sha256(_canonical(body)).hexdigest(), **body}


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    required = ("schema_id", "adapter_id", "adapter_version", "supported_contract_versions", "capabilities", "input_schema_refs", "output_schema_refs", "determinism", "record_contents_authorize_execution")
    if any(key not in manifest for key in required):
        return receipt(manifest, "failed", [{"code": "manifest-invalid", "message": "required adapter manifest field is missing"}])
    if manifest["record_contents_authorize_execution"] is not False:
        return receipt(manifest, "failed", [{"code": "authority-boundary", "message": "adapter manifest must not grant execution authority"}])
    return receipt(manifest, "succeeded")
