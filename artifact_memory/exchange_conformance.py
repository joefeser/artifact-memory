"""Checked issue #22 exchange admission and replay conformance matrix."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, receipt_with_digest
from .exchange import AUTHORITY_BOUNDARY, admit_v2, make_envelope_v2
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, validate


OUTCOMES = (
    "admitted",
    "duplicate",
    "partially-resolved",
    "quarantined",
    "rejected",
    "unsupported",
)


def _revision(record: dict[str, Any]) -> dict[str, str]:
    return {
        "record_id": record["record_id"],
        "revision_digest": "sha-256:" + hashlib.sha256(canonical_bytes(record)).hexdigest(),
    }


def _case(receipt: dict[str, Any], expected: str) -> dict[str, Any]:
    validate(receipt, load_schema("core", "admission-receipt.v2.schema.json"))
    if receipt["outcome"] != expected:
        raise ValidationFailure(
            "vector-mismatch",
            "exchange admission outcome did not match its declared vector",
        )
    return {
        "expected_outcome": expected,
        "observed_outcome": receipt["outcome"],
        "passed": True,
    }


def run_exchange_conformance(fixture: Path) -> dict[str, Any]:
    vectors = load_json(fixture / "vectors.json")
    validate(
        vectors,
        load_schema("core", "exchange-conformance-vectors.v1.schema.json"),
    )
    records = vectors["records"]
    if len(records) != 2:
        raise ValidationFailure("invalid-vector", "exchange fixture requires two records")
    for record in records:
        validate(record, load_schema("core", "knowledge-record.v2.schema.json"))
    first, second = records
    first_ref, second_ref = _revision(first), _revision(second)
    common = {
        "audience_ref": vectors["audience_ref"],
        "expires_at": vectors["expires_at"],
    }

    admitted_envelope = make_envelope_v2(
        common["audience_ref"],
        "exchange-admitted",
        common["expires_at"],
        [first_ref],
        [vectors["artifact_ref"]],
        record_bundle=[first],
    )
    admitted = admit_v2(
        admitted_envelope,
        now=vectors["evaluation_time"],
    )

    expired_envelope = make_envelope_v2(
        common["audience_ref"],
        "exchange-rejected",
        "2020-01-01T00:00:00Z",
        [],
        [vectors["artifact_ref"]],
    )
    rejected = admit_v2(expired_envelope, now=vectors["evaluation_time"])

    contradictory_envelope = make_envelope_v2(
        common["audience_ref"],
        "exchange-quarantined",
        common["expires_at"],
        [first_ref, {**first_ref, "revision_digest": "sha-256:" + "f" * 64}],
        [],
        record_bundle=[first],
    )
    quarantined = admit_v2(
        contradictory_envelope,
        now=vectors["evaluation_time"],
    )

    partial_envelope = make_envelope_v2(
        common["audience_ref"],
        "exchange-partially-resolved",
        common["expires_at"],
        [first_ref, second_ref],
        [vectors["artifact_ref"]],
        record_bundle=[first],
    )
    partially_resolved = admit_v2(
        partial_envelope,
        now=vectors["evaluation_time"],
    )

    unsupported = admit_v2(admitted_envelope, supported_schema=False)

    ledger: set[str] = set()
    admit_v2(admitted_envelope, ledger, now=vectors["evaluation_time"])
    duplicate = admit_v2(admitted_envelope, ledger, now=vectors["evaluation_time"])
    repeated_duplicate = admit_v2(
        admitted_envelope,
        ledger,
        now=vectors["evaluation_time"],
    )
    if duplicate != repeated_duplicate:
        raise ValidationFailure(
            "replay-not-idempotent",
            "repeated exchange replay did not return the same duplicate receipt",
        )

    protected_envelope = make_envelope_v2(
        common["audience_ref"],
        "exchange-protected-material",
        common["expires_at"],
        [],
        [vectors["artifact_ref"]],
        extensions={"authorization": "Bearer synthetic-placeholder"},
    )
    protected_receipt = admit_v2(
        protected_envelope,
        now=vectors["evaluation_time"],
    )
    if (
        protected_receipt["outcome"] != "rejected"
        or protected_receipt["diagnostics"][0]["code"]
        != "bearer-material-prohibited"
        or "Bearer" in canonical_bytes(protected_receipt).decode("utf-8")
    ):
        raise ValidationFailure(
            "bearer-boundary-failed",
            "bearer material was not rejected without echo",
        )

    receipts = {
        "admitted": admitted,
        "duplicate": duplicate,
        "partially-resolved": partially_resolved,
        "quarantined": quarantined,
        "rejected": rejected,
        "unsupported": unsupported,
    }
    cases = {outcome: _case(receipts[outcome], outcome) for outcome in OUTCOMES}
    body = {
        "outcome": "complete",
        "synthetic": True,
        "declared_outcomes": list(OUTCOMES),
        "cases": cases,
        "replay_idempotent": True,
        "contradictory_input_quarantined": True,
        "bearer_material_rejected_without_echo": True,
        "artifact_retrieval": "not-attempted/separately-authorized",
        "authority_boundary": AUTHORITY_BOUNDARY,
        "claims": [
            "the v2 bundle manifest binds record revisions and artifact references",
            "all six admission outcomes are independently replayed",
            "repeated replay returns one deterministic duplicate receipt",
            "contradictory declarations quarantine without granting authority",
            "bearer material is rejected and never echoed into receipts",
        ],
        "limitations": [
            "synthetic exchange does not establish cross-party authenticity or execution authority",
            "artifact bytes are not retrieved by this fixture",
        ],
    }
    receipt = receipt_with_digest(
        "artifact-memory/exchange-conformance-receipt/v1",
        "exchange-conformance-receipt://",
        body,
    )
    validate(
        receipt,
        load_schema("core", "exchange-conformance-receipt.v1.schema.json"),
    )
    return receipt


def render_exchange_conformance_receipt(receipt: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| `{case_id}` | `{case['observed_outcome']}` | pass |"
        for case_id, case in receipt["cases"].items()
    )
    return (
        "# Exchange admission conformance receipt\n\n"
        f"- Outcome: `{receipt['outcome']}`\n"
        f"- Receipt: `{receipt['receipt_id']}`\n"
        "- Replay idempotent: `true`\n"
        "- Contradictory input quarantined: `true`\n"
        "- Bearer material rejected without echo: `true`\n"
        "- Artifact retrieval: `not-attempted/separately-authorized`\n\n"
        "| Case | Observed outcome | Result |\n"
        "| --- | --- | --- |\n"
        f"{rows}\n\n"
        f"Authority boundary: {receipt['authority_boundary']}.\n"
    )
