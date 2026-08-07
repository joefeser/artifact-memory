"""Adapter manifest validation and machine-readable receipts."""

from __future__ import annotations

import re
from typing import Any

from .canonical import receipt_with_digest
from .extensions import ExtensionFailure, preserve_extensions
from .schema_resources import load_schema
from .validator import ValidationFailure, validate

AUTHORITY_BOUNDARY = "record contents do not authorize adapter execution"
ADAPTER_ID = re.compile(r"^adapter://[A-Za-z0-9._~-]+/[A-Za-z0-9._~-]+$")


def receipt(manifest: Any, outcome: str, diagnostics: list[dict[str, str]] | None = None) -> dict[str, Any]:
    if outcome == "failed" and not diagnostics:
        raise ValueError("failed adapter receipts require diagnostics")
    claimed_ref = manifest.get("adapter_id") if isinstance(manifest, dict) else None
    adapter_ref = claimed_ref if isinstance(claimed_ref, str) and ADAPTER_ID.fullmatch(claimed_ref) else "adapter://unknown/unknown"
    body = {"adapter_ref": adapter_ref, "outcome": outcome, "authority_boundary": AUTHORITY_BOUNDARY, "diagnostics": diagnostics or []}
    result = receipt_with_digest("artifact-memory/adapter-receipt/v1", "adapter-receipt://", body)
    try:
        validate(result, load_schema("adapters", "adapter-receipt.v1.schema.json"))
    except ValidationFailure as exc:
        raise ValueError("adapter receipt does not satisfy its contract") from exc
    return result


def validate_manifest(
    manifest: Any,
    supported_required: tuple[tuple[str, str], ...] = (),
) -> dict[str, Any]:
    """Validate a manifest without interpreting or executing the adapter."""
    manifest_schema = load_schema("adapters", "adapter-manifest.v1.schema.json")
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
        validate(manifest, manifest_schema)
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
    try:
        preserve_extensions(
            {"extensions": {}},
            {
                "schema_id": "artifact-memory/extension-bundle/v1",
                "extensions": manifest.get("extensions", {}),
            },
            supported_required,
        )
    except ExtensionFailure as exc:
        return receipt(
            manifest,
            "failed",
            [{
                "code": "extension-invalid",
                "detail_code": exc.code,
                "message": exc.message,
                "path": exc.path,
            }],
        )
    return receipt(manifest, "succeeded")
