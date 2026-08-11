"""Fail-closed release-asset subject selection for keyless attestations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from .release import (
    validate_release_candidate_verification_receipt,
    validate_release_manifest,
)
from .validator import ValidationFailure, load_json_bytes


TAG = re.compile(r"^v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
PREPARATION_ASSETS = {
    "release-candidate-preparation-receipt.json",
    "release-candidate-preparation-receipt.md",
    "release-manifest.json",
}
VERIFICATION_ASSET = "release-candidate-verification-receipt.json"
AUTHORITY_BOUNDARY = (
    "keyless attestation records workflow identity and subject digests; it grants no "
    "signing, publication, deployment, execution, or other authority"
)


class ReleaseAttestationFailure(ValueError):
    """Typed failure raised before any attestation subject list is emitted."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _protocol_sha256(data: bytes) -> str:
    return "sha-256:" + hashlib.sha256(data).hexdigest()


def _directory(path: Path, label: str) -> Path:
    try:
        mode = path.lstat().st_mode
    except OSError as error:
        raise ReleaseAttestationFailure(
            "release-attestation-directory-unavailable",
            f"{label} directory is unavailable",
        ) from error
    if path.is_symlink() or not stat.S_ISDIR(mode):
        raise ReleaseAttestationFailure(
            "release-attestation-directory-unsafe",
            f"{label} must be a real directory",
        )
    return path.resolve()


def _file_names(directory: Path, label: str) -> set[str]:
    names: set[str] = set()
    try:
        entries = list(os.scandir(directory))
    except OSError as error:
        raise ReleaseAttestationFailure(
            "release-attestation-directory-unavailable",
            f"{label} directory could not be read",
        ) from error
    for entry in entries:
        if not entry.is_file(follow_symlinks=False):
            raise ReleaseAttestationFailure(
                "release-attestation-entry-unsafe",
                f"{label} contains a non-regular entry",
            )
        names.add(entry.name)
    return names


def _read_stable(path: Path, label: str) -> bytes:
    try:
        before = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise ReleaseAttestationFailure(
                "release-attestation-entry-unsafe",
                f"{label} must be a regular file",
            )
        data = path.read_bytes()
        after = path.stat(follow_symlinks=False)
    except ReleaseAttestationFailure:
        raise
    except OSError as error:
        raise ReleaseAttestationFailure(
            "release-attestation-entry-unavailable",
            f"{label} could not be read",
        ) from error
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if identity_before != identity_after or len(data) != after.st_size:
        raise ReleaseAttestationFailure(
            "release-attestation-entry-changed",
            f"{label} changed while it was being read",
        )
    return data


def _load_object(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = load_json_bytes(data)
    except ValidationFailure as error:
        raise ReleaseAttestationFailure(
            "release-attestation-json-invalid",
            f"{label} is not valid strict JSON",
        ) from error
    if not isinstance(value, dict):
        raise ReleaseAttestationFailure(
            "release-attestation-json-invalid",
            f"{label} must be a JSON object",
        )
    return value


def verify_release_attestation_subjects(
    reproduced_directory: Path,
    published_directory: Path,
    generated_verification_receipt: Path,
    *,
    tag: str,
) -> dict[str, Any]:
    """Return exact attestation subjects after deterministic release replay."""
    if not isinstance(tag, str) or TAG.fullmatch(tag) is None:
        raise ReleaseAttestationFailure(
            "release-attestation-tag-invalid",
            "release tag must be a canonical vMAJOR.MINOR.PATCH identifier",
        )
    reproduced = _directory(reproduced_directory, "reproduced")
    published = _directory(published_directory, "published")
    if (
        reproduced == published
        or reproduced in published.parents
        or published in reproduced.parents
    ):
        raise ReleaseAttestationFailure(
            "release-attestation-directory-overlap",
            "reproduced and published directories must be distinct",
        )
    try:
        generated_receipt_path = generated_verification_receipt.resolve(strict=True)
    except OSError as error:
        raise ReleaseAttestationFailure(
            "release-attestation-entry-unavailable",
            "generated release verification receipt is unavailable",
        ) from error
    if reproduced in generated_receipt_path.parents or published in generated_receipt_path.parents:
        raise ReleaseAttestationFailure(
            "release-attestation-directory-overlap",
            "generated verification evidence must be outside both asset directories",
        )

    manifest_bytes = _read_stable(reproduced / "release-manifest.json", "reproduced manifest")
    manifest = _load_object(manifest_bytes, "reproduced manifest")
    try:
        validate_release_manifest(manifest)
    except ValidationFailure as error:
        raise ReleaseAttestationFailure(
            "release-attestation-manifest-invalid",
            "reproduced release manifest is invalid",
        ) from error
    if manifest.get("status") != "release-candidate" or manifest.get("signature", {}).get("tag") != tag:
        raise ReleaseAttestationFailure(
            "release-attestation-release-identity-mismatch",
            "release manifest must be the candidate for the requested tag",
        )

    manifest_artifacts = {item["name"] for item in manifest["artifacts"]}
    if len(manifest_artifacts) != len(manifest["artifacts"]):
        raise ReleaseAttestationFailure(
            "release-attestation-manifest-invalid",
            "release manifest artifact names must be unique",
        )
    if manifest_artifacts & (PREPARATION_ASSETS | {VERIFICATION_ASSET}):
        raise ReleaseAttestationFailure(
            "release-attestation-manifest-invalid",
            "release manifest artifact names collide with workflow evidence names",
        )
    expected_reproduced = PREPARATION_ASSETS | manifest_artifacts
    expected_published = expected_reproduced | {VERIFICATION_ASSET}
    if _file_names(reproduced, "reproduced") != expected_reproduced:
        raise ReleaseAttestationFailure(
            "release-attestation-reproduced-set-mismatch",
            "reproduced release asset set is incomplete or contains unexpected files",
        )
    if _file_names(published, "published") != expected_published:
        raise ReleaseAttestationFailure(
            "release-attestation-published-set-mismatch",
            "published release asset set is incomplete or contains unexpected files",
        )

    published_bytes: dict[str, bytes] = {}
    for name in sorted(expected_reproduced):
        reproduced_bytes = (
            manifest_bytes
            if name == "release-manifest.json"
            else _read_stable(reproduced / name, "reproduced release asset")
        )
        candidate_bytes = _read_stable(published / name, "published release asset")
        if reproduced_bytes != candidate_bytes:
            raise ReleaseAttestationFailure(
                "release-attestation-replay-mismatch",
                "a published release asset differs from deterministic reproduction",
            )
        published_bytes[name] = candidate_bytes

    generated_bytes = _read_stable(
        generated_receipt_path,
        "generated release verification receipt",
    )
    published_verification = _read_stable(
        published / VERIFICATION_ASSET,
        "published release verification receipt",
    )
    if generated_bytes != published_verification:
        raise ReleaseAttestationFailure(
            "release-attestation-verification-receipt-mismatch",
            "published release verification receipt differs from exact replay",
        )
    verification = _load_object(generated_bytes, "generated release verification receipt")
    try:
        validate_release_candidate_verification_receipt(verification)
    except ValidationFailure as error:
        raise ReleaseAttestationFailure(
            "release-attestation-verification-receipt-invalid",
            "generated release verification receipt is invalid",
        ) from error
    manifest_digest = _protocol_sha256(manifest_bytes)
    checksum_name = manifest["checksum_manifest"]["artifact_name"]
    if (
        verification.get("outcome") != "pass"
        or verification.get("tag") != tag
        or verification.get("release_id") != manifest["release_id"]
        or verification.get("manifest_sha256") != manifest_digest
        or verification.get("verified_asset_count") != len(manifest["artifacts"])
        or verification.get("checksum_manifest_sha256")
        != _protocol_sha256(published_bytes[checksum_name])
    ):
        raise ReleaseAttestationFailure(
            "release-attestation-verification-binding-mismatch",
            "verification receipt is not bound to the reproduced release asset set",
        )
    published_bytes[VERIFICATION_ASSET] = published_verification
    if (
        _file_names(reproduced, "reproduced") != expected_reproduced
        or _file_names(published, "published") != expected_published
    ):
        raise ReleaseAttestationFailure(
            "release-attestation-asset-set-changed",
            "release asset set changed during verification",
        )

    subjects = [
        {
            "name": name,
            "sha256": _sha256(published_bytes[name]),
            "byte_size": len(published_bytes[name]),
        }
        for name in sorted(published_bytes)
    ]
    return {
        "outcome": "pass",
        "tag": tag,
        "release_id": manifest["release_id"],
        "source_commit": manifest["source"]["commit"],
        "subject_count": len(subjects),
        "subjects": subjects,
        "authority_boundary": AUTHORITY_BOUNDARY,
    }


def write_subject_checksums(report: dict[str, Any], output: Path) -> None:
    """Write an actions/attest checksum input without overwriting evidence."""
    if report.get("outcome") != "pass" or not isinstance(report.get("subjects"), list):
        raise ReleaseAttestationFailure(
            "release-attestation-report-invalid",
            "only a passing verified subject report can be rendered",
        )
    lines = []
    for subject in report["subjects"]:
        name = subject.get("name")
        digest = subject.get("sha256")
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or not isinstance(digest, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
        ):
            raise ReleaseAttestationFailure(
                "release-attestation-report-invalid",
                "subject report contains an invalid name or digest",
            )
        lines.append(f"{digest.removeprefix('sha256:')}  {name}\n")
    try:
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.writelines(lines)
    except OSError as error:
        raise ReleaseAttestationFailure(
            "release-attestation-checksums-write-failed",
            "attestation subject checksum file could not be created exclusively",
        ) from error


def render_report(report: dict[str, Any]) -> str:
    """Render the bounded verification report for workflow logs."""
    return json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n"
