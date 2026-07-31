"""Explicit retention and deletion semantics without destructive execution."""

from __future__ import annotations

import hashlib
from typing import Any

from .canonical import canonical_bytes, receipt_with_digest

DELETION_OUTCOMES = ("requested", "attempted", "removed-observed", "verified-absent-at-endpoint", "retained-until-expiry", "not-authorized", "endpoint-unavailable", "scope-unknown", "failed", "partially-complete")


_canonical = canonical_bytes


def deletion_request(target_ref: str, scope: str, authorized: bool = False, endpoint_ref: str | None = None, generation_ref: str | None = None) -> dict[str, Any]:
    """Create a receipt; never remove bytes or mutate an endpoint."""
    outcome = "requested" if authorized else "not-authorized"
    body: dict[str, Any] = {"target_ref": target_ref, "scope": scope, "outcome": outcome, "global_erasure_claim": False}
    if endpoint_ref:
        body["endpoint_ref"] = endpoint_ref
    if generation_ref:
        body["generation_ref"] = generation_ref
    body["limitations"] = ["destructive execution is separately authorized", "absence from one endpoint does not prove global erasure"]
    return receipt_with_digest("artifact-memory/deletion-receipt/v1", "deletion-receipt://reference-cli/", body)


def tombstone(target_ref: str, reason: str, content_status: str, deletion_receipt_ref: str, superseded_by_ref: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"target_ref": target_ref, "reason": reason, "content_status": content_status, "deletion_receipt_ref": deletion_receipt_ref}
    if superseded_by_ref:
        body["superseded_by_ref"] = superseded_by_ref
    return {"schema_id": "artifact-memory/tombstone/v1", "tombstone_id": "tombstone://" + hashlib.sha256(_canonical(body)).hexdigest(), **body}


def overall_deletion_status(receipts: list[dict[str, Any]]) -> str:
    outcomes = {receipt["outcome"] for receipt in receipts}
    if "not-authorized" in outcomes:
        return "not-authorized"
    if "retained-until-expiry" in outcomes or "endpoint-unavailable" in outcomes or "scope-unknown" in outcomes:
        return "partially-complete"
    if outcomes and outcomes.issubset({"removed-observed", "verified-absent-at-endpoint"}):
        return "partially-complete" if len(receipts) > 1 else "verified-absent-at-endpoint"
    return "requested"
