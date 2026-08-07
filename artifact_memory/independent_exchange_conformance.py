"""Issue #23 reference-sender to independent-receiver conformance proof."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, receipt_with_digest
from .conformance_helpers import SyntheticReplayLedger
from .exchange import AUTHORITY_BOUNDARY, admit_v2, make_envelope_v2
from .independent_reader import admit_bundle_v2
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, validate


def _revision(record: dict[str, Any]) -> dict[str, str]:
    return {
        "record_id": record["record_id"],
        "revision_digest": "sha-256:"
        + hashlib.sha256(canonical_bytes(record)).hexdigest(),
    }


def _run_case(
    envelope: dict[str, Any],
    *,
    audience_ref: str,
    evaluation_time: str,
    expected_outcome: str,
    supported_required_extensions: set[tuple[str, str]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    reference_receipt = admit_v2(
        envelope,
        SyntheticReplayLedger(),
        expected_audience_ref=audience_ref,
        now=evaluation_time,
        supported_required_extensions=supported_required_extensions,
    )
    independent_receipt = admit_bundle_v2(
        canonical_bytes(envelope),
        expected_audience_ref=audience_ref,
        now=evaluation_time,
        supported_required_extensions=supported_required_extensions,
    )
    receipt_schema = load_schema("core", "admission-receipt.v2.schema.json")
    validate(reference_receipt, receipt_schema)
    validate(independent_receipt, receipt_schema)
    if reference_receipt != independent_receipt:
        raise ValidationFailure(
            "receipt-incompatible",
            "reference and independent receivers emitted different admission receipts",
        )
    if reference_receipt["outcome"] != expected_outcome:
        raise ValidationFailure(
            "outcome-incompatible",
            "independent exchange case did not produce the expected outcome",
        )
    return (
        reference_receipt,
        independent_receipt,
        {
            "expected_outcome": expected_outcome,
            "observed_outcome": reference_receipt["outcome"],
            "reference_receipt_ref": reference_receipt["receipt_id"],
            "independent_receipt_ref": independent_receipt["receipt_id"],
            "receipts_compatible": True,
        },
    )


def run_independent_exchange_conformance(fixture: Path) -> dict[str, Any]:
    vectors = load_json(fixture / "vectors.json")
    validate(
        vectors,
        load_schema("core", "independent-exchange-vectors.v1.schema.json"),
    )
    record = vectors["record"]
    validate(record, load_schema("core", "knowledge-record.v2.schema.json"))
    audience_ref = vectors["audience_ref"]
    common = {
        "audience_ref": audience_ref,
        "expires_at": vectors["expires_at"],
        "record_refs": [_revision(record)],
        "artifact_refs": [vectors["artifact_ref"]],
        "record_bundle": [record],
    }

    optional = vectors["optional_extension"]
    optional_envelope = make_envelope_v2(
        correlation_id="independent-optional",
        extensions={optional["identifier"]: optional["declaration"]},
        **common,
    )
    optional_reference, _, optional_case = _run_case(
        optional_envelope,
        audience_ref=audience_ref,
        evaluation_time=vectors["evaluation_time"],
        expected_outcome="admitted",
    )
    if optional_reference["extensions"] != {
        optional["identifier"]: optional["declaration"]
    }:
        raise ValidationFailure(
            "optional-extension-not-preserved",
            "independent exchange did not preserve the optional extension",
        )

    required = vectors["required_extension"]
    required_envelope = make_envelope_v2(
        correlation_id="independent-required",
        extensions={required["identifier"]: required["declaration"]},
        **common,
    )
    required_reference, _, required_case = _run_case(
        required_envelope,
        audience_ref=audience_ref,
        evaluation_time=vectors["evaluation_time"],
        expected_outcome="quarantined",
    )
    if required_reference["diagnostics"][0]["code"] != "required-extension-unsupported":
        raise ValidationFailure(
            "required-extension-not-rejected",
            "independent exchange returned the wrong required-extension diagnostic",
        )

    support = {(required["identifier"], required["declaration"]["version"])}
    supported_reference, _, supported_case = _run_case(
        required_envelope,
        audience_ref=audience_ref,
        evaluation_time=vectors["evaluation_time"],
        expected_outcome="admitted",
        supported_required_extensions=support,
    )
    if supported_reference["extensions"] != {
        required["identifier"]: required["declaration"]
    }:
        raise ValidationFailure(
            "required-extension-not-preserved",
            "explicitly supported extension did not round-trip",
        )

    duplicate_envelope = make_envelope_v2(
        correlation_id="independent-duplicate-declaration",
        audience_ref=audience_ref,
        expires_at=vectors["expires_at"],
        record_refs=[_revision(record), _revision(record)],
        artifact_refs=[vectors["artifact_ref"]],
        record_bundle=[record],
    )
    _, _, duplicate_case = _run_case(
        duplicate_envelope,
        audience_ref=audience_ref,
        evaluation_time=vectors["evaluation_time"],
        expected_outcome="admitted",
    )

    legacy_record = {
        **record,
        "schema_id": "artifact-memory/knowledge-record/v1",
        "record_id": "record://synthetic/independent-exchange-legacy",
        "extensions": {
            "legacy-opaque-key": {"opaque": ["preserved", "without-interpretation"]}
        },
    }
    validate(legacy_record, load_schema("core", "knowledge-record.v1.schema.json"))
    legacy_envelope = make_envelope_v2(
        correlation_id="independent-legacy-extension",
        audience_ref=audience_ref,
        expires_at=vectors["expires_at"],
        record_refs=[_revision(legacy_record)],
        artifact_refs=[vectors["artifact_ref"]],
        record_bundle=[legacy_record],
    )
    _, _, legacy_case = _run_case(
        legacy_envelope,
        audience_ref=audience_ref,
        evaluation_time=vectors["evaluation_time"],
        expected_outcome="admitted",
    )

    legacy_declaration_record = {
        **legacy_record,
        "record_id": "record://synthetic/independent-exchange-legacy-declaration",
        "extensions": {
            "https://synthetic.example/extensions/legacy-required": {
                "version": "v1",
                "required": True,
                "value": {"behavior": "explicit-support-required"},
            }
        },
    }
    legacy_declaration_envelope = make_envelope_v2(
        correlation_id="independent-legacy-declaration",
        audience_ref=audience_ref,
        expires_at=vectors["expires_at"],
        record_refs=[_revision(legacy_declaration_record)],
        artifact_refs=[vectors["artifact_ref"]],
        record_bundle=[legacy_declaration_record],
    )
    _, _, legacy_declaration_case = _run_case(
        legacy_declaration_envelope,
        audience_ref=audience_ref,
        evaluation_time=vectors["evaluation_time"],
        expected_outcome="quarantined",
    )

    legacy_malformed_record = {
        **legacy_record,
        "record_id": "record://synthetic/independent-exchange-legacy-malformed",
        "extensions": {
            "https://synthetic.example/extensions/legacy-required": {
                "required": True,
                "legacy": "missing-v2-declaration-fields",
            }
        },
    }
    legacy_malformed_envelope = make_envelope_v2(
        correlation_id="independent-legacy-malformed",
        audience_ref=audience_ref,
        expires_at=vectors["expires_at"],
        record_refs=[_revision(legacy_malformed_record)],
        artifact_refs=[vectors["artifact_ref"]],
        record_bundle=[legacy_malformed_record],
    )
    _, _, legacy_malformed_case = _run_case(
        legacy_malformed_envelope,
        audience_ref=audience_ref,
        evaluation_time=vectors["evaluation_time"],
        expected_outcome="admitted",
    )

    mixed_optional_declaration = {
        "version": "v1",
        "required": False,
        "value": {"opaque": "preserve-unchanged"},
    }
    mixed_required_declaration = {
        "version": "v1",
        "required": True,
        "value": {"behavior": "explicit-support-required"},
    }
    mixed_legacy_value = {
        "required": True,
        "legacy": "missing-v2-declaration-fields",
    }
    mixed_record = {
        **legacy_record,
        "record_id": "record://synthetic/independent-exchange-mixed",
        "extensions": {
            "https://synthetic.example/extensions/mixed-optional": mixed_optional_declaration,
            "https://synthetic.example/extensions/legacy-required": mixed_required_declaration,
            "https://synthetic.example/extensions/legacy-opaque": mixed_legacy_value,
        },
    }
    validate(mixed_record, load_schema("core", "knowledge-record.v1.schema.json"))
    mixed_envelope = make_envelope_v2(
        correlation_id="independent-mixed-required-and-legacy",
        audience_ref=audience_ref,
        expires_at=vectors["expires_at"],
        record_refs=[_revision(mixed_record)],
        artifact_refs=[vectors["artifact_ref"]],
        record_bundle=[mixed_record],
    )
    mixed_support = {
        (
            "https://synthetic.example/extensions/legacy-required",
            "v1",
        )
    }
    mixed_reference, _, mixed_case = _run_case(
        mixed_envelope,
        audience_ref=audience_ref,
        evaluation_time=vectors["evaluation_time"],
        expected_outcome="admitted",
        supported_required_extensions=mixed_support,
    )
    if mixed_reference["outcome"] != "admitted":
        raise ValidationFailure(
            "mixed-extensions-not-admitted",
            "a bundled record mixing a supported complete required declaration, "
            "an unknown optional declaration, and an incomplete legacy opaque "
            "value must be admitted",
        )
    if any(
        record_id != mixed_record["record_id"]
        for record_id in mixed_reference["accepted_record_ids"]
    ) or mixed_record["record_id"] not in mixed_reference["accepted_record_ids"]:
        raise ValidationFailure(
            "mixed-extensions-record-not-accepted",
            "the mixed-extensions record must be the sole accepted record",
        )

    body = {
        "outcome": "complete",
        "synthetic": True,
        "sender_implementation": "artifact-memory-reference-sender-v2",
        "reference_receiver_implementation": "artifact-memory-reference-admission-v2",
        "independent_receiver_implementation": "stdlib-only-independent-reader-v2",
        "cases": {
            "unknown_optional": optional_case,
            "unknown_required": required_case,
            "explicitly_supported_required": supported_case,
            "identical_manifest_declaration": duplicate_case,
            "legacy_opaque_record_extension": legacy_case,
            "legacy_required_declaration": legacy_declaration_case,
            "legacy_malformed_required_declaration": legacy_malformed_case,
            "mixed_required_and_legacy_extensions": mixed_case,
        },
        "artifact_retrieval": "not-attempted/separately-authorized",
        "authority_boundary": AUTHORITY_BOUNDARY,
        "claims": [
            "a reference-sender v2 bundle validates under a materially separate stdlib-only receiver",
            "reference and independent receivers emit identical schema-valid admission receipts for the checked cases",
            "one unknown optional extension is preserved unchanged",
            "one unknown required extension fails closed and is admitted only after explicit support",
            "identical manifest declarations are deduplicated without changing admission",
            "a v1 record's opaque extension is preserved without v2 interpretation",
            "a complete required declaration fails closed at the v2 admission boundary when unsupported",
            "an incomplete legacy value that merely contains a required key remains opaque and is admitted",
            "a bundled record mixing a supported complete required declaration, an unknown optional declaration, and an incomplete legacy opaque value is admitted as the sole accepted record, proving extensions are classified per declaration rather than gated by the presence of any single required declaration",
            "artifact retrieval remains unattempted and separately authorized",
        ],
        "limitations": [
            "the fixture is synthetic and does not establish cross-party authenticity or trust",
            "the independent receiver proves the complete embedded-bundle profile, not durable replay or external artifact resolution",
            "compatible informational receipts grant no execution, disclosure, routing, spending, credential, deployment, merge, or mutation authority",
        ],
    }
    receipt = receipt_with_digest(
        "artifact-memory/independent-exchange-conformance-receipt/v1",
        "independent-exchange-conformance-receipt://",
        body,
    )
    validate(
        receipt,
        load_schema(
            "core", "independent-exchange-conformance-receipt.v1.schema.json"
        ),
    )
    return receipt


def render_independent_exchange_conformance(receipt: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| `{name}` | `{case['observed_outcome']}` | `{str(case['receipts_compatible']).lower()}` |"
        for name, case in receipt["cases"].items()
    )
    return (
        "# Independent exchange conformance receipt\n\n"
        f"- Outcome: `{receipt['outcome']}`\n"
        f"- Receipt: `{receipt['receipt_id']}`\n"
        f"- Sender: `{receipt['sender_implementation']}`\n"
        f"- Independent receiver: `{receipt['independent_receiver_implementation']}`\n"
        "- Artifact retrieval: `not-attempted/separately-authorized`\n\n"
        "| Case | Outcome | Compatible receipts |\n"
        "| --- | --- | --- |\n"
        f"{rows}\n\n"
        f"Authority boundary: {receipt['authority_boundary']}.\n"
    )
