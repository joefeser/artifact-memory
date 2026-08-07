"""Replay the minimum v0 adapter-manifest success and failure seam."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .adapter_manifest import AUTHORITY_BOUNDARY, validate_manifest
from .canonical import receipt_with_digest
from .extensions import preserve_extensions
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, validate


def run_adapter_manifest_conformance(fixture: Path) -> dict[str, Any]:
    reference_manifest = load_json(fixture / "independent-reference-manifest.json")
    denied_manifest = load_json(fixture / "unauthorized-reference-manifest.json")
    tracemap_manifest = load_json(fixture / "tracemap-read-manifest.json")
    extension_manifests = {
        "optional-preserved": load_json(fixture / "optional-extension-manifest.json"),
        "malformed-rejected": load_json(fixture / "malformed-extension-manifest.json"),
        "unsupported-required-rejected": load_json(fixture / "unsupported-required-extension-manifest.json"),
        "invalid-identifier-rejected": load_json(fixture / "invalid-extension-identifier-manifest.json"),
    }
    manifest_schema = load_schema("adapters", "adapter-manifest.v1.schema.json")
    validate(reference_manifest, manifest_schema)
    validate(tracemap_manifest, manifest_schema)
    denied_without_authority = dict(denied_manifest)
    denied_without_authority["record_contents_authorize_execution"] = False
    if denied_without_authority != reference_manifest:
        raise ValidationFailure("vector-mismatch", "denied manifest must differ from the reference only by its authority claim")
    tracemap_capabilities = tracemap_manifest["capabilities"]
    if (
        tracemap_capabilities["filesystem"] != "read"
        or tracemap_capabilities["network"] != "none"
        or tracemap_capabilities["credentials"] != "none"
        or tracemap_capabilities["mutation"] != "none"
        or tracemap_capabilities["read_capabilities"] != ["trace-map-local-output"]
    ):
        raise ValidationFailure("vector-mismatch", "TraceMap manifest does not declare the bounded local-read capability")

    success_receipt = validate_manifest(reference_manifest)
    failure_receipt = validate_manifest(denied_manifest)
    receipt_schema = load_schema("adapters", "adapter-receipt.v1.schema.json")
    validate(success_receipt, receipt_schema)
    validate(failure_receipt, receipt_schema)
    if success_receipt["outcome"] != "succeeded" or success_receipt["diagnostics"]:
        raise ValidationFailure("vector-mismatch", "reference adapter did not emit a clean success receipt")
    if failure_receipt["outcome"] != "failed" or failure_receipt["diagnostics"][0]["code"] != "authority-boundary":
        raise ValidationFailure("vector-mismatch", "authority-bearing manifest did not emit the expected failure receipt")

    extension_receipts = {
        case_id: validate_manifest(manifest)
        for case_id, manifest in extension_manifests.items()
    }
    optional = extension_manifests["optional-preserved"]
    preserved = preserve_extensions(
        {"extensions": {}},
        {"schema_id": "artifact-memory/extension-bundle/v1", "extensions": optional["extensions"]},
    )
    if preserved["extensions"] != optional["extensions"]:
        raise ValidationFailure("vector-mismatch", "unknown optional extension was not preserved exactly")
    expected_extension_results = {
        "optional-preserved": ("succeeded", None),
        "malformed-rejected": ("failed", "manifest-invalid"),
        "unsupported-required-rejected": ("failed", "extension-invalid"),
        "invalid-identifier-rejected": ("failed", "manifest-invalid"),
    }
    extension_cases = []
    for case_id, result in extension_receipts.items():
        expected_outcome, expected_code = expected_extension_results[case_id]
        observed_code = result["diagnostics"][0]["code"] if result["diagnostics"] else None
        if result["outcome"] != expected_outcome or observed_code != expected_code:
            raise ValidationFailure("vector-mismatch", f"extension case produced an unexpected result: {case_id}")
        extension_cases.append({
            "case_id": case_id,
            "outcome": result["outcome"],
            "diagnostic_code": observed_code,
            "preserved": case_id == "optional-preserved" and bool(preserved["extensions"]),
        })

    body = {
        "synthetic": True,
        "reference_adapter_id": reference_manifest["adapter_id"],
        "provider_read_adapter_id": tracemap_manifest["adapter_id"],
        "success_receipt": success_receipt,
        "failure_receipt": failure_receipt,
        "extension_cases": extension_cases,
        "authority_boundary": AUTHORITY_BOUNDARY,
        "claims": [
            "one synthetic reference adapter manifest validates and emits a deterministic success receipt",
            "one manifest that claims record-derived execution authority fails closed with a path-aware receipt",
            "the TraceMap fixture declares local provider-output read access without network, credential, or mutation authority",
            "unknown optional adapter extensions are preserved while malformed, non-global, and unsupported required declarations fail closed",
        ],
        "limitations": [
            "v0 does not provide plugin discovery, dynamic remote loading, a marketplace, or a generalized isolation runtime",
            "manifest validation does not execute, authorize, install, or load adapter code",
        ],
    }
    result = receipt_with_digest(
        "artifact-memory/adapter-manifest-conformance-receipt/v2",
        "adapter-manifest-conformance-receipt://",
        body,
    )
    validate(result, load_schema("adapters", "adapter-manifest-conformance-receipt.v2.schema.json"))
    return result


def render_adapter_manifest_conformance_receipt(receipt: dict[str, Any]) -> str:
    success = receipt["success_receipt"]
    failure = receipt["failure_receipt"]
    extension_summary = ", ".join(
        f"{case['case_id']}={case['outcome']}"
        for case in receipt["extension_cases"]
    )
    return (
        "# Adapter manifest conformance receipt\n\n"
        f"- Reference adapter: `{receipt['reference_adapter_id']}`\n"
        f"- Provider-read adapter: `{receipt['provider_read_adapter_id']}` (local read only)\n"
        f"- Success outcome: `{success['outcome']}` (`{success['receipt_id']}`)\n"
        f"- Failure outcome: `{failure['outcome']}` / `{failure['diagnostics'][0]['code']}` (`{failure['receipt_id']}`)\n"
        f"- Extension cases: {extension_summary}\n"
        f"- Conformance receipt: `{receipt['receipt_id']}`\n\n"
        f"Authority boundary: {receipt['authority_boundary']}.\n"
    )
