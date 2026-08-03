"""Checked synthetic proof for private-vault intake behavior."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any

from .canonical import receipt_with_digest
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, validate
from .vault import INTAKE_AUTHORITY_BOUNDARY, intake_bytes


def run_vault_intake_conformance(fixture: Path) -> dict[str, Any]:
    vector = load_json(fixture / "vector.json")
    try:
        validate(vector, load_schema("core", "vault-intake-vector.v1.schema.json"))
    except ValidationFailure as exc:
        raise ValidationFailure("vector-invalid", "vault intake vector is malformed", exc.path) from exc
    payload_path = fixture / vector["payload"]
    if payload_path.is_symlink() or not payload_path.is_file():
        raise ValidationFailure("vector-invalid", "vault intake payload must be a regular fixture file")
    payload = payload_path.read_bytes()
    arguments = vector["intake"]
    with tempfile.TemporaryDirectory() as temporary:
        vault = Path(temporary) / "vault"
        registered = intake_bytes(vault, payload, **arguments)
        duplicate = intake_bytes(vault, payload, **arguments)
        quarantine_vault = Path(temporary) / "quarantine-vault"
        quarantined = intake_bytes(
            quarantine_vault,
            payload,
            **arguments,
            expected_digest="sha-256:" + "0" * 64,
        )
        quarantine_files = [path for path in (quarantine_vault / "quarantine").rglob("*") if path.is_file()]
        if (
            (quarantine_vault / "objects").exists()
            or (quarantine_vault / "records").exists()
            or len(quarantine_files) != 1
            or quarantined["registration_outcome"] != "not-attempted"
            or quarantined["canonical_records"] != "not-created"
        ):
            raise RuntimeError("vault intake quarantine was not isolated")
    if (registered["outcome"], duplicate["outcome"], quarantined["outcome"]) != ("registered", "duplicate", "quarantined"):
        raise RuntimeError("vault intake vector did not produce the required outcomes")
    body = {
        "synthetic": True,
        "content_ref": registered["content_ref"],
        "artifact_ref": registered["artifact_ref"],
        "artifact_version_ref": registered["artifact_version_ref"],
        "stages": [
            {"name": "hash-register-verify", "outcome": registered["outcome"]},
            {"name": "canonical-artifact-version-records", "outcome": registered["canonical_records"]},
            {"name": "duplicate-replay", "outcome": duplicate["outcome"]},
            {"name": "digest-mismatch-quarantine", "outcome": quarantined["outcome"]},
        ],
        "payload_digest": "sha-256:" + hashlib.sha256(payload).hexdigest(),
        "authority_boundary": INTAKE_AUTHORITY_BOUNDARY,
        "limitations": [
            "fixture uses newly authored synthetic bytes and a temporary vault",
            "interrupted-write cleanup is proved by the runtime regression test",
            "receipt discloses no local path or private vault material",
        ],
    }
    result = receipt_with_digest("artifact-memory/vault-intake-conformance-receipt/v1", "vault-intake-conformance-receipt://", body)
    validate(result, load_schema("core", "vault-intake-conformance-receipt.v1.schema.json"))
    return result


def render_vault_intake_receipt(receipt: dict[str, Any]) -> str:
    stages = "".join(f"- {item['name']}: `{item['outcome']}`\n" for item in receipt["stages"])
    return (
        "# Vault intake conformance receipt\n\n"
        f"- Content: `{receipt['content_ref']}`\n"
        f"- Artifact: `{receipt['artifact_ref']}`\n"
        f"- Version: `{receipt['artifact_version_ref']}`\n"
        f"- Receipt: `{receipt['receipt_id']}`\n\n"
        "## Stages\n\n" + stages + "\n"
        f"Authority boundary: {receipt['authority_boundary']}.\n"
    )
