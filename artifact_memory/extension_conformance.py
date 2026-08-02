"""Replay the minimum v0 optional/required extension conformance seam."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .canonical import receipt_with_digest
from .extensions import ExtensionFailure, extension_digest, preserve_extensions, validate_extension_bundle
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, validate


AUTHORITY_BOUNDARY = "extension data grants no execution, disclosure, mutation, credential, deployment, spending, or approval authority"


def _one_declaration(bundle: dict[str, Any], required: bool) -> tuple[str, dict[str, Any]]:
    validate_extension_bundle(bundle)
    extensions = bundle["extensions"]
    if len(extensions) != 1:
        raise ValidationFailure("invalid-vector", "extension conformance bundle must contain exactly one declaration")
    identifier, declaration = next(iter(extensions.items()))
    if declaration["required"] is not required:
        raise ValidationFailure("invalid-vector", "extension required flag does not match its conformance role")
    return identifier, declaration


def run_extension_conformance(fixture: Path) -> dict[str, Any]:
    optional_bundle = load_json(fixture / "optional-extension.json")
    required_bundle = load_json(fixture / "required-extension.json")
    optional_id, optional = _one_declaration(optional_bundle, False)
    required_id, required = _one_declaration(required_bundle, True)

    core = {
        "schema_id": "artifact-memory/knowledge-record/v2",
        "record_id": "record://synthetic/extension-conformance",
        "digest": "sha-256:" + "0" * 64,
        "sensitivity": "public",
        "authority_boundary": AUTHORITY_BOUNDARY,
    }
    preserved = preserve_extensions(core, optional_bundle)
    core_unchanged = all(preserved.get(key) == value for key, value in core.items())
    optional_unchanged = preserved["extensions"].get(optional_id) == optional
    if not core_unchanged or not optional_unchanged:
        raise ValidationFailure("vector-mismatch", "optional extension did not round-trip opaquely")

    try:
        preserve_extensions(core, required_bundle)
    except ExtensionFailure as exc:
        required_code = exc.code
    else:
        raise ValidationFailure("vector-mismatch", "unknown required extension did not fail closed")
    if required_code != "required-extension-unsupported":
        raise ValidationFailure("vector-mismatch", "unknown required extension returned the wrong diagnostic")
    supported = preserve_extensions(core, required_bundle, supported_required={(required_id, required["version"])})
    if supported["extensions"].get(required_id) != required:
        raise ValidationFailure("vector-mismatch", "declared support did not preserve the required extension")

    body = {
        "outcome": "complete",
        "synthetic": True,
        "optional_extension": {
            "identifier": optional_id,
            "version": optional["version"],
            "bundle_digest": extension_digest(optional_bundle),
            "round_trip_preserved": True,
        },
        "required_extension": {
            "identifier": required_id,
            "version": required["version"],
            "bundle_digest": extension_digest(required_bundle),
            "unknown_outcome": "rejected",
            "diagnostic_code": required_code,
            "declared_support_outcome": "accepted",
        },
        "core_fields_unchanged": True,
        "authority_boundary": AUTHORITY_BOUNDARY,
        "claims": [
            "one unknown optional extension round-trips unchanged without interpretation",
            "one unknown required extension fails closed and succeeds only when support is explicitly declared",
            "extension namespace containment preserves core identity, sensitivity, schema, digest, and authority fields",
        ],
        "limitations": [
            "v0 defines no registry, discovery service, marketplace, inheritance system, or executable plugin loading",
        ],
    }
    receipt = receipt_with_digest("artifact-memory/extension-conformance-receipt/v1", "extension-conformance-receipt://", body)
    validate(receipt, load_schema("core", "extension-conformance-receipt.v1.schema.json"))
    return receipt


def render_extension_conformance_receipt(receipt: dict[str, Any]) -> str:
    optional = receipt["optional_extension"]
    required = receipt["required_extension"]
    return (
        "# Minimum extension conformance receipt\n\n"
        f"- Outcome: `{receipt['outcome']}`\n"
        f"- Optional extension: `{optional['identifier']}` `{optional['version']}` (preserved)\n"
        f"- Required extension: `{required['identifier']}` `{required['version']}` (unknown rejected; declared support accepted)\n"
        f"- Core fields unchanged: `{str(receipt['core_fields_unchanged']).lower()}`\n"
        f"- Receipt: `{receipt['receipt_id']}`\n\n"
        f"Authority boundary: {receipt['authority_boundary']}.\n"
    )
