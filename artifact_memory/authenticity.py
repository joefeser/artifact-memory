"""v0 distinction between integrity, provenance, authenticity, authority, and trust."""

from __future__ import annotations

from typing import Any


UNSIGNED_STATE = "integrity-verified / issuer-unverified"


def evaluate(subject_ref: str, integrity_verified: bool, provenance_present: bool, authenticity_required: bool = False, signed_input: bool = False) -> dict[str, Any]:
    """Classify evidence; v0 does not verify cryptographic signatures."""
    if not integrity_verified:
        integrity_state = "integrity-failed"
    elif not signed_input:
        integrity_state = UNSIGNED_STATE
    else:
        integrity_state = "integrity-verified / issuer-unverified"
    if signed_input:
        authenticity_state = "authenticity-required-unmet" if authenticity_required else "signed-input-unsupported"
        outcome = "rejected" if authenticity_required else "unsupported"
    else:
        authenticity_state = "authenticity-required-unmet" if authenticity_required else "issuer-unverified"
        outcome = "rejected" if authenticity_required or not integrity_verified else "accepted"
    return {"schema_id": "artifact-memory/authenticity-receipt/v1", "subject_ref": subject_ref, "integrity_state": integrity_state, "provenance_state": "provenance-present" if provenance_present else "provenance-absent", "authenticity_state": authenticity_state, "authorization_state": "not-granted", "trust_state": "not-established", "requirement": "authenticity-required" if authenticity_required else "authenticity-optional", "outcome": outcome, "limitations": ["provenance does not establish authenticity", "authorization and trust are separate decisions"]}
