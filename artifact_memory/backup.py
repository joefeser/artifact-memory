"""Encrypted allowlisted backup, Git bundle, and isolated restore receipts."""

from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from .canonical import CHUNK_SIZE, canonical_bytes, receipt_with_digest, sha256_path
from .validator import ValidationFailure, load_json_bytes


AUTHORITY_BOUNDARY = "backup and restore do not grant execution, disclosure, or mutation authority"
ZERO_DIGEST = "sha-256:" + "0" * 64
DIGEST_PATTERN = re.compile(r"^sha-256:[0-9a-f]{64}$")


_canonical = canonical_bytes


def _digest_bytes(data: bytes) -> str:
    return "sha-256:" + hashlib.sha256(data).hexdigest()


class BackupFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _source_entries(sources: dict[str, Path]) -> list[tuple[str, Path]]:
    entries: list[tuple[str, Path]] = []
    for label, root in sorted(sources.items()):
        label_path = PurePosixPath(label)
        if not label or label_path.is_absolute() or len(label_path.parts) != 1 or label in {".", ".."}:
            raise BackupFailure("source-label-invalid")
        root = root.resolve()
        if not root.exists():
            raise FileNotFoundError(label)
        if root.is_file():
            entries.append((f"{label}/{root.name}", root))
        else:
            for path in sorted(root.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    entries.append((f"{label}/{path.relative_to(root).as_posix()}", path))
    return entries


def _safe_archive_relative_path(value: Any) -> PurePosixPath:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or re.match(r"^[A-Za-z]:", value)
    ):
        raise BackupFailure("unsafe-backup-member")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() in {"", "."}:
        raise BackupFailure("unsafe-backup-member")
    return path


def _snapshot_sources(sources: dict[str, Path], snapshot_root: Path) -> tuple[dict[str, Any], list[tuple[str, Path]]]:
    snapshots: list[tuple[str, Path]] = []
    manifest_entries: list[dict[str, Any]] = []
    for name, source in _source_entries(sources):
        target = snapshot_root / PurePosixPath(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        byte_size = 0
        try:
            with source.open("rb") as input_stream, target.open("xb") as output_stream:
                while chunk := input_stream.read(CHUNK_SIZE):
                    output_stream.write(chunk)
                    digest.update(chunk)
                    byte_size += len(chunk)
        except OSError as exc:
            raise BackupFailure("source-unreadable") from exc
        snapshots.append((name, target))
        manifest_entries.append({"path": name, "digest": "sha-256:" + digest.hexdigest(), "byte_size": byte_size})
    manifest = {"schema_id": "artifact-memory/backup-manifest/v1", "entries": manifest_entries}
    return manifest, snapshots


def _run_openssl(args: list[str], passphrase: str, input_path: Path, output_path: Path) -> None:
    command = ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "100000", "-salt", "-pass", "stdin", *args, "-in", str(input_path), "-out", str(output_path)]
    try:
        completed = subprocess.run(command, input=(passphrase + "\n").encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except FileNotFoundError as exc:
        raise BackupFailure("openssl-unavailable") from exc
    if completed.returncode != 0:
        raise BackupFailure("openssl-failed")


def _backup_ref(endpoint_ref: str, generation_ref: str) -> str:
    return f"backup://{endpoint_ref.rsplit('/', 1)[-1]}/{generation_ref}"


def _backup_receipt(
    outcome: str,
    backup_ref: str,
    endpoint_ref: str,
    generation_ref: str,
    source_manifest_digest: str,
    backup_digest: str,
    limitations: list[str],
) -> dict[str, Any]:
    body = {
        "outcome": outcome,
        "backup_ref": backup_ref,
        "endpoint_ref": endpoint_ref,
        "generation_ref": generation_ref,
        "encryption": "openssl-aes-256-cbc-pbkdf2",
        "source_manifest_digest": source_manifest_digest,
        "backup_digest": backup_digest,
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": limitations,
    }
    return receipt_with_digest("artifact-memory/backup-receipt/v1", "backup-receipt://", body)


def _restore_receipt(outcome: str, backup_ref: str, manifest_digest: str, limitations: list[str]) -> dict[str, Any]:
    body = {
        "outcome": outcome,
        "backup_ref": backup_ref,
        "isolated": True,
        "restored_manifest_digest": manifest_digest,
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": limitations,
    }
    return receipt_with_digest("artifact-memory/restore-receipt/v1", "restore-receipt://", body)


def create_backup(sources: dict[str, Path], output_dir: Path, passphrase: str, endpoint_ref: str = "endpoint://synthetic/local-backup", generation_ref: str = "generation-0001") -> dict[str, Any]:
    backup_ref = _backup_ref(endpoint_ref, generation_ref)
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=output_dir) as temporary:
            temporary_root = Path(temporary)
            manifest, entries = _snapshot_sources(sources, temporary_root / "snapshot")
            source_digest = _digest_bytes(_canonical(manifest))
            plain = temporary_root / "backup.tar"
            with tarfile.open(plain, "w") as archive:
                for name, path in entries:
                    info = archive.gettarinfo(str(path), arcname=name)
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    with path.open("rb") as stream:
                        archive.addfile(info, stream)
                manifest_bytes = _canonical(manifest)
                info = tarfile.TarInfo("backup-manifest.json")
                info.size = len(manifest_bytes)
                info.mtime = 0
                archive.addfile(info, io.BytesIO(manifest_bytes))
            encrypted_staging = temporary_root / "backup.enc"
            _run_openssl([], passphrase, plain, encrypted_staging)
            backup_digest = sha256_path(encrypted_staging)
            encrypted = output_dir / "backup.enc"
            os.replace(encrypted_staging, encrypted)
        os.chmod(encrypted, 0o600)
    except (BackupFailure, OSError, tarfile.TarError) as exc:
        code = exc.code if isinstance(exc, BackupFailure) else "backup-failed"
        return _backup_receipt("failed", backup_ref, endpoint_ref, generation_ref, ZERO_DIGEST, ZERO_DIGEST, [code])
    return _backup_receipt(
        "created",
        backup_ref,
        endpoint_ref,
        generation_ref,
        source_digest,
        backup_digest,
        ["key recovery is external to the backup payload", "unknown replicas remain outside this receipt"],
    )


def restore_isolated(
    backup_file: Path,
    target_dir: Path,
    passphrase: str,
    backup_ref: str,
    expected_backup_digest: str,
    expected_source_manifest_digest: str,
) -> dict[str, Any]:
    try:
        if (
            not isinstance(expected_backup_digest, str)
            or DIGEST_PATTERN.fullmatch(expected_backup_digest) is None
            or not isinstance(expected_source_manifest_digest, str)
            or DIGEST_PATTERN.fullmatch(expected_source_manifest_digest) is None
        ):
            return _restore_receipt("failed", backup_ref, ZERO_DIGEST, ["expected backup binding is invalid"])
        if sha256_path(backup_file) != expected_backup_digest:
            return _restore_receipt("failed", backup_ref, ZERO_DIGEST, ["backup ciphertext digest did not match the receipt"])
        if target_dir.exists() and (not target_dir.is_dir() or any(target_dir.iterdir())):
            return _restore_receipt("rejected", backup_ref, ZERO_DIGEST, ["target is not an empty isolated location"])
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=target_dir.parent) as temporary:
            temporary_root = Path(temporary)
            plain = temporary_root / "backup.tar"
            staging = temporary_root / "restore"
            staging.mkdir()
            _run_openssl(["-d"], passphrase, backup_file, plain)
            with tarfile.open(plain, "r") as archive:
                seen: set[str] = set()
                staging_root = staging.resolve()
                for member in archive.getmembers():
                    member_path = _safe_archive_relative_path(member.name)
                    normalized_member = member_path.as_posix()
                    if (
                        normalized_member in seen
                        or not (member.isdir() or member.isreg())
                    ):
                        raise BackupFailure("unsafe-backup-member")
                    seen.add(normalized_member)
                    destination = staging / member_path
                    if not destination.resolve().is_relative_to(staging_root):
                        raise BackupFailure("unsafe-backup-member")
                    if member.isdir():
                        destination.mkdir(parents=True, exist_ok=True)
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    source = archive.extractfile(member)
                    if source is None:
                        raise BackupFailure("backup-member-unreadable")
                    try:
                        with source, destination.open("xb") as output_stream:
                            shutil.copyfileobj(source, output_stream, CHUNK_SIZE)
                    except FileExistsError as exc:
                        raise BackupFailure("unsafe-backup-member") from exc
            manifest_path = staging / "backup-manifest.json"
            manifest_bytes = manifest_path.read_bytes()
            try:
                manifest = load_json_bytes(manifest_bytes)
            except ValidationFailure as exc:
                raise BackupFailure("backup-manifest-invalid") from exc
            if not isinstance(manifest, dict) or manifest.get("schema_id") != "artifact-memory/backup-manifest/v1" or not isinstance(manifest.get("entries"), list):
                raise BackupFailure("backup-manifest-invalid")
            expected_paths: set[str] = set()
            for entry in manifest["entries"]:
                if not isinstance(entry, dict):
                    raise BackupFailure("backup-manifest-invalid")
                try:
                    entry_path = _safe_archive_relative_path(entry.get("path"))
                except BackupFailure as exc:
                    raise BackupFailure("backup-manifest-invalid") from exc
                digest = entry.get("digest")
                byte_size = entry.get("byte_size")
                if (
                    not isinstance(digest, str)
                    or not isinstance(byte_size, int)
                    or isinstance(byte_size, bool)
                    or byte_size < 0
                ):
                    raise BackupFailure("backup-manifest-invalid")
                normalized = entry_path.as_posix()
                if normalized in expected_paths:
                    raise BackupFailure("backup-manifest-invalid")
                expected_paths.add(normalized)
                restored_path = staging / entry_path
                if not restored_path.resolve().is_relative_to(staging_root):
                    raise BackupFailure("backup-manifest-invalid")
                if not restored_path.is_file() or sha256_path(restored_path) != digest or restored_path.stat().st_size != byte_size:
                    raise BackupFailure("restored-content-mismatch")
            actual_paths = {
                path.relative_to(staging).as_posix()
                for path in staging.rglob("*")
                if path.is_file() and path != manifest_path
            }
            if actual_paths != expected_paths:
                raise BackupFailure("backup-manifest-invalid")
            canonical_manifest = _canonical(manifest)
            if manifest_bytes != canonical_manifest:
                raise BackupFailure("backup-manifest-noncanonical")
            manifest_digest = _digest_bytes(canonical_manifest)
            if manifest_digest != expected_source_manifest_digest:
                raise BackupFailure("backup-manifest-digest-mismatch")
            if target_dir.exists():
                target_dir.rmdir()
            os.replace(staging, target_dir)
    except (BackupFailure, OSError, ValueError, KeyError, TypeError, tarfile.TarError) as exc:
        code = exc.code if isinstance(exc, BackupFailure) else "restore-failed"
        return _restore_receipt("failed", backup_ref, ZERO_DIGEST, [code])
    return _restore_receipt("restored", backup_ref, manifest_digest, ["restore does not activate or authorize restored content"])


def create_git_bundle(repo: Path, output_file: Path, source_ref: str) -> dict[str, Any]:
    result = subprocess.run(["git", "-C", str(repo), "bundle", "create", str(output_file), "--all"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        body = {"outcome": "failed", "bundle_digest": ZERO_DIGEST, "source_ref": source_ref, "authority_boundary": AUTHORITY_BOUNDARY}
        return receipt_with_digest("artifact-memory/git-bundle-receipt/v1", "git-bundle-receipt://", body)
    bundle_digest = sha256_path(output_file)
    body = {"outcome": "created", "bundle_digest": bundle_digest, "source_ref": source_ref, "authority_boundary": AUTHORITY_BOUNDARY}
    return receipt_with_digest("artifact-memory/git-bundle-receipt/v1", "git-bundle-receipt://", body)
