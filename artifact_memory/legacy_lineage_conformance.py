"""Replay the synthetic WhereAreMyFiles read-only observation fixture."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, receipt_with_digest, sha256_bytes
from .lineage import SOURCE_REF, observe_legacy_file
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, validate


def run_legacy_lineage_conformance(vector_path: Path) -> dict[str, Any]:
    vectors = load_json(vector_path)
    if vectors.get("synthetic") is not True or vectors.get("source_ref") != SOURCE_REF:
        raise ValidationFailure("invalid-vector", "legacy lineage vectors require synthetic provenance and the attributed source")
    rows = vectors.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValidationFailure("invalid-vector", "legacy lineage vectors require rows")

    observations = [observe_legacy_file(row, SOURCE_REF) for row in rows]
    states = [item["historical_fields"]["legacy_hash"]["state"] for item in observations]
    body = {
        "outcome": "pass",
        "synthetic": True,
        "source_ref": SOURCE_REF,
        "source_commit": vectors["source_commit"],
        "observation_count": len(observations),
        "hash_states": states,
        "artifact_identities_established": 0,
        "content_identities_established": 0,
        "source_mutations": 0,
        "vector_set_digest": sha256_bytes(canonical_bytes(vectors)),
        "claims": [
            "complete synthetic rows emit read-only historical observations",
            "SHA-1 and NONE establish no artifact or content identity",
            "the historical source remains separately attributed",
        ],
        "limitations": [
            "synthetic replay does not prove a complete historical filesystem scan",
            "historical observations establish no present existence, custody, authenticity, trust, disclosure permission, or authority",
        ],
    }
    receipt = receipt_with_digest(
        "artifact-memory/legacy-lineage-conformance-receipt/v1",
        "legacy-lineage-conformance-receipt://",
        body,
    )
    validate(receipt, load_schema("core", "legacy-lineage-conformance-receipt.v1.schema.json"))
    return receipt


def render_legacy_lineage_receipt(receipt: dict[str, Any]) -> str:
    return (
        "# Legacy lineage conformance receipt\n\n"
        f"- Outcome: `{receipt['outcome']}`\n"
        f"- Receipt: `{receipt['receipt_id']}`\n"
        f"- Historical source commit: `{receipt['source_commit']}`\n"
        f"- Observations: {receipt['observation_count']}\n"
        f"- Hash states: `{', '.join(receipt['hash_states'])}`\n"
        "- Artifact identities established: 0\n"
        "- Content identities established: 0\n"
        "- Source mutations: 0\n\n"
        "The synthetic replay proves only the bounded read-only observation contract. It does not prove historical scan completeness, present custody, authenticity, trust, disclosure permission, or authority.\n"
    )
