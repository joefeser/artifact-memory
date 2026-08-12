"""Fail-closed release-asset subject selection for keyless attestations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any, BinaryIO

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
STREAM_CHUNK_SIZE = 1024 * 1024


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


def _open_regular_file(path: Path, label: str) -> tuple[BinaryIO, os.stat_result]:
    """Open a regular file without a pathname-check/read race."""
    descriptor = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise OSError("not one stable regular file")
        stream = os.fdopen(descriptor, "rb")
        descriptor = -1
        return stream, opened
    except OSError as error:
        raise ReleaseAttestationFailure(
            "release-attestation-entry-unavailable",
            f"{label} could not be opened as one stable regular file",
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _ensure_unchanged(
    path: Path,
    stream: BinaryIO,
    before: os.stat_result,
    byte_size: int,
    label: str,
) -> None:
    try:
        after = os.fstat(stream.fileno())
        named = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise ReleaseAttestationFailure(
            "release-attestation-entry-unavailable",
            f"{label} could not be rechecked",
        ) from error
    if (
        _identity(before) != _identity(after)
        or _identity(after) != _identity(named)
        or byte_size != after.st_size
    ):
        raise ReleaseAttestationFailure(
            "release-attestation-entry-changed",
            f"{label} changed while it was being read",
        )


def _read_stable(path: Path, label: str) -> bytes:
    try:
        stream, before = _open_regular_file(path, label)
        with stream:
            data = stream.read()
            _ensure_unchanged(path, stream, before, len(data), label)
        return data
    except ReleaseAttestationFailure:
        raise
    except OSError as error:
        raise ReleaseAttestationFailure(
            "release-attestation-entry-unavailable",
            f"{label} could not be read",
        ) from error


def _stream_equal_subject(
    reproduced_path: Path,
    published_path: Path,
    *,
    label: str,
    mismatch_code: str = "release-attestation-replay-mismatch",
    mismatch_message: str = (
        "a published release asset differs from deterministic reproduction"
    ),
) -> dict[str, Any]:
    """Compare two stable regular files while retaining only subject metadata."""
    try:
        reproduced_stream, reproduced_before = _open_regular_file(
            reproduced_path, label
        )
        try:
            published_stream, published_before = _open_regular_file(
                published_path, label
            )
        except Exception:
            reproduced_stream.close()
            raise
        digest = hashlib.sha256()
        byte_size = 0
        with reproduced_stream, published_stream:
            while True:
                reproduced_chunk = reproduced_stream.read(STREAM_CHUNK_SIZE)
                published_chunk = published_stream.read(STREAM_CHUNK_SIZE)
                if reproduced_chunk != published_chunk:
                    raise ReleaseAttestationFailure(
                        mismatch_code,
                        mismatch_message,
                    )
                if not published_chunk:
                    break
                digest.update(published_chunk)
                byte_size += len(published_chunk)
            _ensure_unchanged(
                reproduced_path,
                reproduced_stream,
                reproduced_before,
                byte_size,
                label,
            )
            _ensure_unchanged(
                published_path,
                published_stream,
                published_before,
                byte_size,
                label,
            )
    except ReleaseAttestationFailure:
        raise
    except OSError as error:
        raise ReleaseAttestationFailure(
            "release-attestation-entry-unavailable",
            f"{label} could not be read",
        ) from error
    return {
        "sha256": "sha256:" + digest.hexdigest(),
        "byte_size": byte_size,
    }


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
    reserved_names = PREPARATION_ASSETS | {VERIFICATION_ASSET}
    reserved_casefolds = {name.casefold() for name in reserved_names}
    if len(reserved_casefolds) != len(reserved_names) or any(
        name.casefold() in reserved_casefolds for name in manifest_artifacts
    ):
        raise ReleaseAttestationFailure(
            "release-attestation-manifest-invalid",
            "release manifest artifact names collide with workflow evidence names case-insensitively",
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

    subjects_by_name: dict[str, dict[str, Any]] = {}
    for name in sorted(expected_reproduced):
        subject = _stream_equal_subject(
            reproduced / name,
            published / name,
            label="release replay asset",
        )
        if name == "release-manifest.json" and subject["sha256"] != _sha256(
            manifest_bytes
        ):
            raise ReleaseAttestationFailure(
                "release-attestation-entry-changed",
                "reproduced manifest changed after validation",
            )
        subjects_by_name[name] = {"name": name, **subject}

    generated_bytes = _read_stable(
        generated_receipt_path,
        "generated release verification receipt",
    )
    verification_subject = _stream_equal_subject(
        generated_receipt_path,
        published / VERIFICATION_ASSET,
        label="release verification receipt",
        mismatch_code="release-attestation-verification-receipt-mismatch",
        mismatch_message=(
            "published release verification receipt differs from exact replay"
        ),
    )
    if verification_subject["sha256"] != _sha256(generated_bytes):
        raise ReleaseAttestationFailure(
            "release-attestation-entry-changed",
            "generated verification receipt changed after validation",
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
        != subjects_by_name[checksum_name]["sha256"].replace("sha256:", "sha-256:", 1)
    ):
        raise ReleaseAttestationFailure(
            "release-attestation-verification-binding-mismatch",
            "verification receipt is not bound to the reproduced release asset set",
        )
    subjects_by_name[VERIFICATION_ASSET] = {
        "name": VERIFICATION_ASSET,
        **verification_subject,
    }
    if (
        _file_names(reproduced, "reproduced") != expected_reproduced
        or _file_names(published, "published") != expected_published
    ):
        raise ReleaseAttestationFailure(
            "release-attestation-asset-set-changed",
            "release asset set changed during verification",
        )

    subjects = [subjects_by_name[name] for name in sorted(subjects_by_name)]
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


def render_receipt(report: dict[str, Any]) -> str:
    """Render the deterministic human-readable attestation verification receipt."""
    if report.get("outcome") != "pass" or not isinstance(report.get("subjects"), list):
        raise ReleaseAttestationFailure(
            "release-attestation-report-invalid",
            "only a passing verified subject report can be rendered",
        )
    lines = [
        "# Release Attestation Verification Receipt",
        "",
        f"- Outcome: {report['outcome']}",
        f"- Release: `{report['release_id']}`",
        f"- Tag: `{report['tag']}`",
        f"- Source commit: `{report['source_commit']}`",
        f"- Verified subjects: {report['subject_count']}",
        "",
        "## Subject Set",
        "",
    ]
    for subject in report["subjects"]:
        lines.append(
            f"- `{subject['name']}` — `{subject['sha256']}` ({subject['byte_size']} bytes)"
        )
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            f"- {report['authority_boundary']}.",
            "- This receipt records deterministic replay and exact subject digests; it does not by itself prove publication or that a keyless attestation was issued.",
            "",
        ]
    )
    return "\n".join(lines)


def write_receipt(report: dict[str, Any], output: Path) -> None:
    """Write the human-readable receipt without overwriting evidence."""
    receipt = render_receipt(report)
    try:
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(receipt)
    except OSError as error:
        raise ReleaseAttestationFailure(
            "release-attestation-receipt-write-failed",
            "attestation verification receipt could not be created exclusively",
        ) from error
