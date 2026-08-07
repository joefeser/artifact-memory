"""Immutable content-addressed registration in a local private vault."""

from __future__ import annotations

import errno
import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .artifact_lineage import ARTIFACT_AUTHORITY_BOUNDARY, VERSION_AUTHORITY_BOUNDARY, validate_artifact, validate_artifact_version
from .canonical import canonical_bytes, receipt_with_digest, sha256_path
from .content import verify_content
from .schema_resources import load_schema
from .validator import ValidationFailure, validate

AUTHORITY_BOUNDARY = "registration does not grant execution, disclosure, or mutation authority"
INTAKE_AUTHORITY_BOUNDARY = "intake and registration grant no execution, disclosure, mutation, authenticity, trust, or authorization"
SHA256_DIGEST = re.compile(r"^sha-256:[0-9a-f]{64}$")
ARTIFACT_ID = re.compile(r"^artifact://[A-Za-z0-9._~-]+/[A-Za-z0-9._~-]+$")
PORTABLE_SOURCE_REF = re.compile(r"^[a-z][a-z0-9+.-]*://[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)*$")
LOCATION_SOURCE_SCHEMES = {"file", "ftp", "ftps", "http", "https", "nfs", "sftp", "smb", "ssh"}
HARDLINK_UNAVAILABLE = {
    errno.EACCES,
    errno.EPERM,
    errno.ENOSYS,
    getattr(errno, "ENOTSUP", errno.EOPNOTSUPP),
    errno.EOPNOTSUPP,
}


class ImmutableWriteFailure(Exception):
    """Typed publication failure that can preserve cleanup state."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _object_path(vault_root: Path, digest_hex: str, area: str = "objects") -> Path:
    return vault_root / area / "sha256" / digest_hex[:2] / digest_hex[2:]


def _existing_matches(path: Path, data: bytes) -> bool:
    if path.is_symlink() or not path.is_file() or path.stat().st_size != len(data):
        return False
    return sha256_path(path) == "sha-256:" + hashlib.sha256(data).hexdigest()


def _write_immutable(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if not _existing_matches(path, data):
            raise ValueError("immutable-record-collision")
        return "duplicate"
    fd, temporary = tempfile.mkstemp(prefix=".partial-", dir=path.parent)
    result: str | None = None
    primary_error: Exception | None = None
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if not _existing_matches(path, data):
                raise ValueError("immutable-record-collision")
            result = "duplicate"
        except OSError as exc:
            if exc.errno not in HARDLINK_UNAVAILABLE:
                raise
            raise ImmutableWriteFailure("object-write-hardlink-unsupported") from exc
        else:
            result = "created"
    except Exception as exc:
        primary_error = exc
    try:
        if os.path.exists(temporary):
            os.unlink(temporary)
    except OSError as exc:
        raise ImmutableWriteFailure("object-write-cleanup-failed") from (primary_error or exc)
    if primary_error is not None:
        raise primary_error
    if result is None:
        raise ImmutableWriteFailure("object-write-failed")
    return result


def register_bytes(vault_root: Path, data: bytes, media_type: str = "application/octet-stream") -> dict[str, Any]:
    digest_hex = hashlib.sha256(data).hexdigest()
    digest = "sha-256:" + digest_hex
    target = _object_path(vault_root, digest_hex)
    target.parent.mkdir(parents=True, exist_ok=True)
    outcome = "duplicate" if target.exists() else "registered"
    diagnostics: list[str] = []
    if outcome == "duplicate":
        try:
            existing_matches = not target.is_symlink() and target.is_file() and target.stat().st_size == len(data) and sha256_path(target) == digest
        except OSError:
            existing_matches = False
        if not existing_matches:
            outcome = "failed"
            diagnostics.append("existing-object-integrity-failed")
    if outcome == "registered":
        try:
            if _write_immutable(target, data) == "duplicate":
                outcome = "duplicate"
        except ImmutableWriteFailure as exc:
            outcome = "failed"
            diagnostics.append(exc.code)
        except (OSError, ValueError):
            outcome = "failed"
            diagnostics.append("object-write-failed")
    content_ref = f"content://vault/{digest_hex}"
    artifact_version_ref = f"artifact-version://vault/{digest_hex}/1"
    body = {
        "outcome": outcome,
        "content_ref": content_ref,
        "artifact_version_ref": artifact_version_ref,
        "byte_size": len(data),
        "digest": digest,
        "media_type": media_type,
        "diagnostics": diagnostics,
        "authority_boundary": AUTHORITY_BOUNDARY,
    }
    return receipt_with_digest(
        "artifact-memory/content-registration-receipt/v1",
        "registration-receipt://",
        body,
    )


def intake_bytes(
    vault_root: Path,
    data: bytes,
    *,
    artifact_id: str,
    artifact_kind: str,
    title: str,
    created_at: str,
    source_ref: str,
    media_type: str = "application/octet-stream",
    expected_digest: str | None = None,
) -> dict[str, Any]:
    """Intake exact bytes without deriving durable identity from a local path."""
    digest_hex = hashlib.sha256(data).hexdigest()
    digest = "sha-256:" + digest_hex
    content_ref = f"content://sha-256/{digest_hex}"
    safe_artifact_ref = artifact_id if isinstance(artifact_id, str) and ARTIFACT_ID.fullmatch(artifact_id) else "artifact://unknown/unknown"
    version_ref = safe_artifact_ref.replace("artifact://", "artifact-version://", 1) + "/1"

    def intake_receipt(outcome: str, registration: str, verification: str, records: str, diagnostics: list[str]) -> dict[str, Any]:
        body = {
            "outcome": outcome,
            "content_ref": content_ref,
            "artifact_ref": safe_artifact_ref,
            "artifact_version_ref": version_ref,
            "digest": digest,
            "byte_size": len(data),
            "registration_outcome": registration,
            "verification_outcome": verification,
            "canonical_records": records,
            "authority_boundary": INTAKE_AUTHORITY_BOUNDARY,
            "diagnostics": diagnostics,
        }
        result = receipt_with_digest("artifact-memory/vault-intake-receipt/v1", "vault-intake-receipt://", body)
        validate(result, load_schema("core", "vault-intake-receipt.v1.schema.json"))
        return result

    if expected_digest is not None and (
        not isinstance(expected_digest, str) or not SHA256_DIGEST.fullmatch(expected_digest)
    ):
        return intake_receipt("failed", "not-attempted", "not-checked", "not-created", ["expected-digest-invalid"])
    if expected_digest is not None and expected_digest != digest:
        try:
            state = _write_immutable(_object_path(vault_root, digest_hex, "quarantine"), data)
        except (ImmutableWriteFailure, OSError, ValueError):
            return intake_receipt("failed", "not-attempted", "not-checked", "not-created", ["quarantine-write-failed"])
        return intake_receipt("quarantined", "not-attempted", "not-checked", "not-created", [f"digest-mismatch-{state}"])

    content_object = {
        "schema_id": "artifact-memory/content-object/v2",
        "content_id": content_ref,
        "digest": digest,
        "byte_size": len(data),
        "media_type": media_type,
    }
    artifact = {
        "schema_id": "artifact-memory/artifact/v1",
        "artifact_id": artifact_id,
        "artifact_kind": artifact_kind,
        "title": title,
        "created_at": created_at,
        "authority_boundary": ARTIFACT_AUTHORITY_BOUNDARY,
    }
    version = {
        "schema_id": "artifact-memory/artifact-version/v2",
        "artifact_id": artifact_id,
        "version_id": version_ref,
        "revision": 1,
        "role": "original",
        "content_refs": [content_ref],
        "lifecycle": "accepted",
        "created_at": created_at,
        "provenance": [{"kind": "import", "source_ref": source_ref}],
        "relationships": [],
        "authority_boundary": VERSION_AUTHORITY_BOUNDARY,
    }
    try:
        if (
            not isinstance(source_ref, str)
            or PORTABLE_SOURCE_REF.fullmatch(source_ref) is None
            or source_ref.partition("://")[0] in LOCATION_SOURCE_SCHEMES
        ):
            raise ValidationFailure("invalid-logical-reference", "source_ref is not portable", "$.source_ref")
        validate(content_object, load_schema("core", "content-object.v2.schema.json"))
        validate_artifact(artifact)
        validate_artifact_version(version)
    except ValidationFailure:
        return intake_receipt("failed", "not-attempted", "not-checked", "not-created", ["intake-metadata-invalid"])

    registration = register_bytes(vault_root, data, media_type)
    if registration["outcome"] not in {"registered", "duplicate"}:
        return intake_receipt("failed", registration["outcome"], "not-checked", "not-created", registration["diagnostics"])
    verification = verify_content(_object_path(vault_root, digest_hex), content_object)
    if verification["outcome"] != "verified":
        return intake_receipt("failed", registration["outcome"], verification["outcome"], "not-created", ["post-registration-verification-failed"])
    try:
        artifact_name = hashlib.sha256(artifact_id.encode()).hexdigest() + ".json"
        version_name = hashlib.sha256(version_ref.encode()).hexdigest() + ".json"
        states = {
            _write_immutable(vault_root / "records" / "artifacts" / artifact_name, canonical_bytes(artifact)),
            _write_immutable(vault_root / "records" / "versions" / version_name, canonical_bytes(version)),
        }
    except (ImmutableWriteFailure, OSError, ValueError):
        return intake_receipt("failed", registration["outcome"], "verified", "failed", ["canonical-record-write-failed"])
    if states == {"duplicate"}:
        records_state = "duplicate"
    elif states == {"created"}:
        records_state = "created"
    else:
        return intake_receipt(
            "failed",
            registration["outcome"],
            "verified",
            "failed",
            ["canonical-record-state-mixed-replay-required"],
        )
    outcome = "duplicate" if registration["outcome"] == "duplicate" and records_state == "duplicate" else "registered"
    return intake_receipt(outcome, registration["outcome"], "verified", records_state, [])
