"""Deterministic synthetic conformance runner for the v0 authenticity decision."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .authenticity import AUTHORITY_BOUNDARY, evaluate
from .canonical import canonical_bytes, receipt_with_digest, sha256_bytes
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, validate


EXPECTED_FIELDS = {"outcome", "integrity_state", "authenticity_state", "transport_state"}


def run_authenticity_conformance(vector_path: Path) -> dict[str, Any]:
    """Run the public synthetic vectors and return a digest-bound receipt."""
    vectors = load_json(vector_path)
    if not isinstance(vectors, list) or not vectors:
        raise ValidationFailure("invalid-vector-set", "authenticity vector set must be a non-empty array")
    seen_cases: set[str] = set()
    case_results: list[dict[str, str]] = []
    for vector in vectors:
        if not isinstance(vector, dict) or set(vector) != {"case", "input", "expected"}:
            raise ValidationFailure("invalid-vector", "authenticity vector fields are invalid")
        case = vector["case"]
        inputs = vector["input"]
        expected = vector["expected"]
        if not isinstance(case, str) or not case or case in seen_cases:
            raise ValidationFailure("invalid-vector", "authenticity vector identity is invalid or duplicated")
        if not isinstance(inputs, dict) or not isinstance(expected, dict) or set(expected) != EXPECTED_FIELDS:
            raise ValidationFailure("invalid-vector", "authenticity vector input or expectation is invalid")
        seen_cases.add(case)
        assessment = evaluate(**inputs)
        for field in sorted(EXPECTED_FIELDS):
            if assessment[field] != expected[field]:
                raise ValidationFailure("vector-mismatch", f"authenticity vector expectation failed: {case}.{field}")
        case_results.append(
            {
                "case": case,
                "assessment_receipt_id": assessment["receipt_id"],
                "outcome": assessment["outcome"],
                "integrity_state": assessment["integrity_state"],
                "authenticity_state": assessment["authenticity_state"],
                "transport_state": assessment["transport_state"],
            }
        )
    body = {
        "outcome": "complete",
        "assessment_schema_id": "artifact-memory/authenticity-receipt/v2",
        "vector_set_digest": sha256_bytes(canonical_bytes(vectors)),
        "case_results": case_results,
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": [
            "synthetic unsigned and unsupported-signature evidence only",
            "record-signature key, expiry, revocation, and delegation behavior is not implemented in v0",
        ],
    }
    receipt = receipt_with_digest(
        "artifact-memory/authenticity-conformance-receipt/v1",
        "authenticity-conformance-receipt://synthetic/",
        body,
    )
    validate(receipt, load_schema("core", "authenticity-conformance-receipt.v1.schema.json"))
    return receipt


def render_authenticity_receipt(receipt: dict[str, Any]) -> str:
    """Render a stable human-readable receipt for repository evidence."""
    lines = [
        "# Synthetic v0 authenticity conformance receipt",
        "",
        f"- Outcome: `{receipt['outcome']}`",
        f"- Receipt: `{receipt['receipt_id']}`",
        f"- Vector set: `{receipt['vector_set_digest']}`",
        f"- Assessment schema: `{receipt['assessment_schema_id']}`",
        f"- Authority: `{receipt['authority_boundary']}`",
        "",
        "| Case | Outcome | Integrity | Authenticity | Transport |",
        "| --- | --- | --- | --- | --- |",
    ]
    for result in receipt["case_results"]:
        lines.append(
            f"| `{result['case']}` | `{result['outcome']}` | `{result['integrity_state']}` | "
            f"`{result['authenticity_state']}` | `{result['transport_state']}` |"
        )
    lines.extend(["", "This receipt uses only newly authored synthetic data and contains no signing keys or credentials.", ""])
    return "\n".join(lines)
