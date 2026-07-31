"""V0 integrity, provenance, authenticity, transport, authority, and trust assessment."""

from __future__ import annotations

from typing import Any

from .canonical import receipt_with_digest
from .schema_resources import load_schema
from .validator import validate


UNSIGNED_STATE = "integrity-verified / issuer-unverified"
AUTHORITY_BOUNDARY = "assessment grants no execution, disclosure, authorization, or trust"
REQUIREMENTS = {"integrity-only", "authenticity-optional", "authenticity-required"}


def evaluate(
    subject_ref: str,
    integrity_verified: bool | None,
    provenance_present: bool,
    authenticity_required: bool = False,
    signed_input: bool = False,
    *,
    requirement: str | None = None,
    issuer_ref: str | None = None,
    audience_ref: str | None = None,
    transport_authenticated: bool | None = None,
    evaluated_at: str,
) -> dict[str, Any]:
    """Assess a subject without treating transport or provenance as authenticity."""
    if integrity_verified is not None and type(integrity_verified) is not bool:
        raise ValueError("integrity_verified must be true, false, or null")
    if type(provenance_present) is not bool:
        raise ValueError("provenance_present must be boolean")
    if type(authenticity_required) is not bool or type(signed_input) is not bool:
        raise ValueError("authenticity and signed-input flags must be boolean")
    if transport_authenticated is not None and type(transport_authenticated) is not bool:
        raise ValueError("transport_authenticated must be true, false, or null")

    selected_requirement = requirement or (
        "authenticity-required" if authenticity_required else "authenticity-optional"
    )
    if selected_requirement not in REQUIREMENTS:
        raise ValueError("unsupported authenticity requirement")
    if authenticity_required and selected_requirement != "authenticity-required":
        raise ValueError("authenticity_required conflicts with requirement")

    if integrity_verified is True:
        integrity_state = UNSIGNED_STATE
    elif integrity_verified is False:
        integrity_state = "integrity-failed"
    else:
        integrity_state = "integrity-unverified"

    if selected_requirement == "authenticity-required":
        authenticity_state = "authenticity-required-unmet"
    elif signed_input:
        authenticity_state = "signed-input-unsupported"
    else:
        authenticity_state = "issuer-unverified"

    if integrity_verified is not True:
        outcome = "rejected"
    elif selected_requirement == "authenticity-required":
        outcome = "rejected"
    elif signed_input:
        outcome = "unsupported"
    else:
        outcome = "accepted"

    transport_state = {
        None: "not-evaluated",
        True: "channel-authenticated / subject-issuer-unverified",
        False: "channel-unverified",
    }[transport_authenticated]
    body: dict[str, Any] = {
        "subject_ref": subject_ref,
        "subject_identity_state": "reference-declared / not-authenticated",
        "integrity_state": integrity_state,
        "provenance_state": "provenance-present" if provenance_present else "provenance-absent",
        "assertion_mode": "signed-input-unsupported" if signed_input else "self-asserted-unsigned",
        "issuer_identity_state": "self-asserted / unverified" if issuer_ref else "not-asserted",
        "audience_state": "self-asserted / unverified" if audience_ref else "not-asserted",
        "transport_state": transport_state,
        "authenticity_state": authenticity_state,
        "authorization_state": "not-granted",
        "trust_state": "not-established",
        "requirement": selected_requirement,
        "evaluated_at": evaluated_at,
        "outcome": outcome,
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": [
            "provenance does not establish authenticity",
            "transport authentication does not authenticate the record issuer or claim",
            "cryptographic record-signature verification is unsupported in v0",
            "authorization and trust are separate receiving-policy decisions",
        ],
    }
    if issuer_ref is not None:
        body["issuer_ref"] = issuer_ref
    if audience_ref is not None:
        body["audience_ref"] = audience_ref
    result = receipt_with_digest(
        "artifact-memory/authenticity-receipt/v2",
        "authenticity-receipt://",
        body,
    )
    validate(result, load_schema("core", "authenticity-receipt.v2.schema.json"))
    return result
