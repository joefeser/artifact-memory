"""Explicit retention and deletion semantics without destructive execution."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from .canonical import canonical_bytes, receipt_with_digest
from .schema_resources import load_schema
from .validator import ValidationFailure, validate

DELETION_OUTCOMES = (
    "requested",
    "attempted",
    "removed-observed",
    "verified-absent-at-endpoint",
    "retained-until-expiry",
    "not-authorized",
    "endpoint-unavailable",
    "scope-unknown",
    "failed",
    "partially-complete",
)
ENDPOINT_SCOPED_OUTCOMES = {
    "attempted",
    "removed-observed",
    "verified-absent-at-endpoint",
    "retained-until-expiry",
    "endpoint-unavailable",
    "failed",
}


_canonical = canonical_bytes


def _instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValidationFailure("invalid-retention-policy", "retention time is invalid") from exc
    if parsed.utcoffset() is None:
        raise ValidationFailure("invalid-retention-policy", "retention time requires a timezone offset")
    return parsed


def retention_disposition(policy: dict[str, Any], *, now: str) -> str:
    """Evaluate policy timing and holds without authorizing or executing deletion."""
    validate(policy, load_schema("core", "retention-policy.v2.schema.json"))
    if policy["owner_hold"] or policy["legal_hold"]:
        return "retained-under-hold"
    if "expires_at" not in policy:
        return "retained-by-policy"
    return "eligible-for-separately-authorized-deletion" if _instant(now) >= _instant(policy["expires_at"]) else "retained-until-expiry"


def deletion_receipt(
    target_ref: str,
    scope: str,
    outcome: str,
    *,
    observed_at: str,
    managed_scope: bool,
    endpoint_ref: str | None = None,
    generation_ref: str | None = None,
    authority_ref: str | None = None,
    evidence_refs: list[str] | None = None,
    limitations: list[str] | None = None,
    issuer: str = "reference-cli",
) -> dict[str, Any]:
    """Describe one scoped lifecycle observation; never mutate the target."""
    if outcome not in DELETION_OUTCOMES:
        raise ValueError("unsupported deletion outcome")
    if outcome in ENDPOINT_SCOPED_OUTCOMES and endpoint_ref is None:
        raise ValueError("endpoint-scoped deletion outcome requires endpoint_ref")
    if scope == "endpoint" and endpoint_ref is None:
        raise ValueError("endpoint scope requires endpoint_ref")
    if generation_ref is not None and endpoint_ref is None:
        raise ValueError("generation_ref requires endpoint_ref")
    if scope == "managed-backup" and generation_ref is None:
        raise ValueError("managed-backup receipt requires generation_ref")
    if scope == "unknown-replica":
        if managed_scope or outcome != "scope-unknown":
            raise ValueError("unknown-replica scope requires unmanaged scope-unknown outcome")
        if endpoint_ref is not None or generation_ref is not None:
            raise ValueError("unknown-replica scope cannot name an endpoint or generation")
    if outcome in {"removed-observed", "verified-absent-at-endpoint"} and not evidence_refs:
        raise ValueError("observed or verified deletion outcome requires evidence_refs")
    body: dict[str, Any] = {
        "target_ref": target_ref,
        "scope": scope,
        "outcome": outcome,
        "observed_at": observed_at,
        "managed_scope": managed_scope,
        "global_erasure_claim": False,
        "destructive_execution_authorization": "separate-owner-or-legal-authorization-required",
        "limitations": limitations
        or [
            "absence from one endpoint does not prove global erasure",
            "unknown or unmanaged replicas are outside this receipt",
        ],
    }
    if endpoint_ref is not None:
        body["endpoint_ref"] = endpoint_ref
    if generation_ref is not None:
        body["generation_ref"] = generation_ref
    if authority_ref is not None:
        body["authority_ref"] = authority_ref
    if evidence_refs:
        body["evidence_refs"] = evidence_refs
    result = receipt_with_digest("artifact-memory/deletion-receipt/v2", f"deletion-receipt://{issuer}/", body)
    validate(result, load_schema("core", "deletion-receipt.v2.schema.json"))
    return result


def deletion_request(
    target_ref: str,
    scope: str,
    authorized: bool = False,
    endpoint_ref: str | None = None,
    generation_ref: str | None = None,
    *,
    observed_at: str,
) -> dict[str, Any]:
    """Create a request receipt; authorization still does not execute deletion."""
    return deletion_receipt(
        target_ref,
        scope,
        "requested" if authorized else "not-authorized",
        observed_at=observed_at,
        managed_scope=scope != "unknown-replica",
        endpoint_ref=endpoint_ref,
        generation_ref=generation_ref,
        authority_ref="authority://owner/deletion-request" if authorized else None,
        limitations=[
            "request recording does not execute deletion",
            "absence from one endpoint does not prove global erasure",
        ],
    )


def tombstone(
    target_ref: str,
    reason: str,
    content_status: str,
    deletion_receipt_ref: str,
    *,
    created_at: str,
    superseded_by_ref: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "target_ref": target_ref,
        "reason": reason,
        "content_status": content_status,
        "deletion_receipt_ref": deletion_receipt_ref,
        "created_at": created_at,
        "sensitive_payload_retained": False,
    }
    if superseded_by_ref:
        body["superseded_by_ref"] = superseded_by_ref
    result = {"schema_id": "artifact-memory/tombstone/v2", "tombstone_id": "tombstone://" + hashlib.sha256(_canonical(body)).hexdigest(), **body}
    validate(result, load_schema("core", "tombstone.v2.schema.json"))
    return result


def content_retrievability(observations: list[dict[str, Any]]) -> str:
    """Summarize current evidence without converting absence into erasure."""
    schema = load_schema("core", "location-observation.v1.schema.json")
    for observation in observations:
        validate(observation, schema)
    content_refs = {observation["content_ref"] for observation in observations}
    if len(content_refs) != 1:
        raise ValueError("retrievability requires observations for exactly one content_ref")

    latest_by_location: dict[tuple[str, str], tuple[datetime, str]] = {}
    for observation in observations:
        location = (observation["endpoint_ref"], observation["relative_path"])
        observed_at = datetime.fromisoformat(observation["observed_at"].replace("Z", "+00:00"))
        previous = latest_by_location.get(location)
        if previous is None or observed_at > previous[0]:
            latest_by_location[location] = (observed_at, observation["presence"])
        elif observed_at == previous[0] and observation["presence"] != previous[1]:
            raise ValueError("retrievability has conflicting latest observations for one location")

    if any(presence == "present" for _, presence in latest_by_location.values()):
        return "verified-retrievable-location-observed"
    return "zero-currently-verified-retrievable-locations"


def overall_deletion_status(receipts: list[dict[str, Any]], *, unknown_replicas: bool = True) -> str:
    if not receipts:
        return "scope-unknown"
    outcomes = {receipt["outcome"] for receipt in receipts}
    if "not-authorized" in outcomes:
        return "not-authorized"
    if outcomes & {"retained-until-expiry", "endpoint-unavailable", "scope-unknown", "failed", "partially-complete"}:
        return "partially-complete"
    if outcomes.issubset({"removed-observed", "verified-absent-at-endpoint"}):
        if unknown_replicas:
            return "partially-complete"
        return "verified-absent-at-endpoint" if outcomes == {"verified-absent-at-endpoint"} else "removed-observed"
    if "attempted" in outcomes:
        return "attempted"
    return "requested"
