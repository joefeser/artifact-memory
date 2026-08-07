"""Versioned public model and deterministic rendering for custody attestation."""

from __future__ import annotations

from datetime import date
from typing import Any

from .schema_resources import load_schema
from .validator import ValidationFailure, validate


SCHEMA_ID = "artifact-memory/sanitized-custody-attestation/v1"


def validate_sanitized_custody_attestation(attestation: dict[str, Any]) -> None:
    """Validate the public shape without claiming private operational replay."""

    validate(
        attestation,
        load_schema("core", "sanitized-custody-attestation.v1.schema.json"),
    )
    try:
        date.fromisoformat(attestation["observed"])
    except (TypeError, ValueError) as exc:
        raise ValidationFailure(
            "constraint-failed",
            "observed must be a valid calendar date",
            "$.observed",
        ) from exc


def render_sanitized_custody_attestation(attestation: dict[str, Any]) -> str:
    """Render the human-readable projection of a validated attestation."""

    validate_sanitized_custody_attestation(attestation)
    return (
        "# Sanitized first off-machine custody receipt\n\n"
        f"- Attester role: `{attestation['attester_role']}`\n"
        f"- Attestation status: `{attestation['attestation_status']}`\n"
        f"- Private evidence binding: `{attestation['private_evidence_binding']}`\n"
        f"- Independent replay: `{str(attestation['independent_replay']).lower()}`\n"
        f"- Observed: `{attestation['observed']}`\n"
        f"- Endpoint: `{attestation['endpoint']}`\n"
        f"- Custody claim: `{attestation['custody_claim']}`\n"
        f"- Transport profile: {attestation['transport_profile']}\n"
        f"- Backup input: {attestation['backup_input']}\n"
        f"- Remote write: {attestation['remote_write']}\n"
        f"- Repository verification: {attestation['repository_verification']}\n"
        f"- Restore: {attestation['restore']}\n"
        f"- Restored verification: {attestation['restored_verification']}\n"
        f"- Storage boundary: {attestation['storage_boundary']}\n"
        f"- Recovery cadence: {attestation['recovery_cadence']}\n"
        f"- Private material committed: `{str(attestation['private_material_committed']).lower()}`\n\n"
        "The private evidence retains exact snapshot, manifest, backup, restore, and\n"
        "machine-local bindings, including validated private receipts where the\n"
        "published contracts apply. This sanitized receipt intentionally contains no\n"
        "network address, VM hostname, account, path, repository identifier, content\n"
        "digest, task identifier, credential, passphrase, or recovery reference. The\n"
        "published logical endpoint value is a portable identity, not a network\n"
        "hostname or address.\n\n"
        "This proof establishes one encrypted off-machine copy and one successful\n"
        "isolated restore on the same owner-controlled premises. It does not establish\n"
        "geographic off-site protection, append-only transport, global erasure, source\n"
        "authenticity, future recoverability, or execution, disclosure, routing, merge,\n"
        "or deployment authority. Recovery material remains owner-controlled and was\n"
        "not inspected by the agent.\n"
    )
