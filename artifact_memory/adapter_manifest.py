"""Adapter manifest validation and machine-readable receipts."""

from __future__ import annotations

import re
from typing import Any

from .canonical import receipt_with_digest
from .schema_resources import load_schema
from .validator import ValidationFailure, validate

AUTHORITY_BOUNDARY = "record contents do not authorize adapter execution"
ADAPTER_ID = re.compile(r"^adapter://[A-Za-z0-9._~-]+/[A-Za-z0-9._~-]+$")


def receipt(manifest: Any, outcome: str, diagnostics: list[dict[str, str]] | None = None) -> dict[str, Any]:
    claimed_ref = manifest.get("adapter_id") if isinstance(manifest, dict) else None
    adapter_ref = claimed_ref if isinstance(claimed_ref, str) and ADAPTER_ID.fullmatch(claimed_ref) else "adapter://unknown/unknown"
    body = {"adapter_ref": adapter_ref, "outcome": outcome, "authority_boundary": AUTHORITY_BOUNDARY, "diagnostics": diagnostics or []}
    return receipt_with_digest("artifact-memory/adapter-receipt/v1", "adapter-receipt://", body)


def validate_manifest(manifest: Any) -> dict[str, Any]:
    """Validate a manifest without interpreting or executing the adapter."""
    if (
        isinstance(manifest, dict)
        and "record_contents_authorize_execution" in manifest
        and manifest["record_contents_authorize_execution"] is not False
    ):
        return receipt(
            manifest,
            "failed",
            [{
                "code": "authority-boundary",
                "detail_code": "constraint-failed",
                "message": "adapter manifest must not grant execution authority",
                "path": "$.record_contents_authorize_execution",
            }],
        )
    try:
        validate(manifest, load_schema("adapters", "adapter-manifest.v1.schema.json"))
    except ValidationFailure as exc:
        return receipt(
            manifest,
            "failed",
            [{
                "code": "manifest-invalid",
                "detail_code": exc.code,
                "message": "adapter manifest does not satisfy the public schema",
                "path": exc.path,
            }],
        )
    return receipt(manifest, "succeeded")
