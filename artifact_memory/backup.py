"""Encrypted allowlisted backup, Git bundle, and isolated restore receipts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any


AUTHORITY_BOUNDARY = "backup and restore do not grant execution, disclosure, or mutation authority"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest_bytes(data: bytes) -> str:
    return "sha-256:" + hashlib.sha256(data).hexdigest()


def _source_manifest(sources: dict[str, Path]) -> tuple[dict[str, Any], list[tuple[str, Path]]]:
    entries: list[tuple[str, Path]] = []
    for label, root in sorted(sources.items()):
        root = root.resolve()
        if not root.exists():
            raise FileNotFoundError(label)
        if root.is_file():
            entries.append((f"{label}/{root.name}", root))
        else:
            for path in sorted(root.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    entries.append((f"{label}/{path.relative_to(root).as_posix()}", path))
    manifest_entries = [{"path": name, "digest": _digest_bytes(path.read_bytes()), "byte_size": path.stat().st_size} for name, path in entries]
    manifest = {"schema_id": "artifact-memory/backup-manifest/v1", "entries": manifest_entries}
    return manifest, entries


def _run_openssl(args: list[str], passphrase: str, input_path: Path, output_path: Path) -> None:
    command = ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "100000", "-salt", "-pass", "stdin", *args, "-in", str(input_path), "-out", str(output_path)]
    completed = subprocess.run(command, input=(passphrase + "\n").encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        raise RuntimeError("encrypted backup operation failed")


def create_backup(sources: dict[str, Path], output_dir: Path, passphrase: str, endpoint_ref: str = "endpoint://synthetic/local-backup", generation_ref: str = "generation-0001") -> dict[str, Any]:
    manifest, entries = _source_manifest(sources)
    source_digest = _digest_bytes(_canonical(manifest))
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        plain = Path(temporary) / "backup.tar"
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
            archive.addfile(info, __import__("io").BytesIO(manifest_bytes))
        encrypted = output_dir / "backup.enc"
        _run_openssl([], passphrase, plain, encrypted)
    os.chmod(encrypted, 0o600)
    backup_ref = f"backup://{endpoint_ref.rsplit('/', 1)[-1]}/{generation_ref}"
    body = {"outcome": "created", "backup_ref": backup_ref, "endpoint_ref": endpoint_ref, "generation_ref": generation_ref, "encryption": "openssl-aes-256-cbc-pbkdf2", "source_manifest_digest": source_digest, "backup_digest": _digest_bytes(encrypted.read_bytes()), "authority_boundary": AUTHORITY_BOUNDARY, "limitations": ["key recovery is external to the backup payload", "unknown replicas remain outside this receipt"]}
    return {"schema_id": "artifact-memory/backup-receipt/v1", "receipt_id": "backup-receipt://" + hashlib.sha256(_canonical(body)).hexdigest(), **body}


def restore_isolated(backup_file: Path, target_dir: Path, passphrase: str, backup_ref: str, expected_backup_digest: str | None = None) -> dict[str, Any]:
    if expected_backup_digest and _digest_bytes(backup_file.read_bytes()) != expected_backup_digest:
        body = {"outcome": "failed", "backup_ref": backup_ref, "isolated": True, "restored_manifest_digest": "sha-256:" + "0" * 64, "authority_boundary": AUTHORITY_BOUNDARY, "limitations": ["backup ciphertext digest did not match the receipt"]}
        return {"schema_id": "artifact-memory/restore-receipt/v1", "receipt_id": "restore-receipt://" + hashlib.sha256(_canonical(body)).hexdigest(), **body}
    if target_dir.exists() and any(target_dir.iterdir()):
        return {"schema_id": "artifact-memory/restore-receipt/v1", "receipt_id": "restore-receipt://" + "0" * 64, "outcome": "rejected", "backup_ref": backup_ref, "isolated": True, "restored_manifest_digest": "sha-256:" + "0" * 64, "authority_boundary": AUTHORITY_BOUNDARY, "limitations": ["target is not an empty isolated location"]}
    target_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        plain = Path(temporary) / "backup.tar"
        _run_openssl(["-d"], passphrase, backup_file, plain)
        with tarfile.open(plain, "r") as archive:
            members = archive.getmembers()
            for member in members:
                member_path = PurePosixPath(member.name)
                if member_path.is_absolute() or ".." in member_path.parts or member.issym() or member.islnk():
                    raise RuntimeError("unsafe backup member")
                archive.extract(member, target_dir)
    manifest = json.loads((target_dir / "backup-manifest.json").read_text(encoding="utf-8"))
    for entry in manifest.get("entries", []):
        restored_path = target_dir / entry["path"]
        if not restored_path.is_file() or _digest_bytes(restored_path.read_bytes()) != entry["digest"] or restored_path.stat().st_size != entry["byte_size"]:
            body = {"outcome": "failed", "backup_ref": backup_ref, "isolated": True, "restored_manifest_digest": "sha-256:" + "0" * 64, "authority_boundary": AUTHORITY_BOUNDARY, "limitations": ["restored content did not match the source manifest"]}
            return {"schema_id": "artifact-memory/restore-receipt/v1", "receipt_id": "restore-receipt://" + hashlib.sha256(_canonical(body)).hexdigest(), **body}
    manifest_digest = _digest_bytes(_canonical(manifest))
    body = {"outcome": "restored", "backup_ref": backup_ref, "isolated": True, "restored_manifest_digest": manifest_digest, "authority_boundary": AUTHORITY_BOUNDARY, "limitations": ["restore does not activate or authorize restored content"]}
    return {"schema_id": "artifact-memory/restore-receipt/v1", "receipt_id": "restore-receipt://" + hashlib.sha256(_canonical(body)).hexdigest(), **body}


def create_git_bundle(repo: Path, output_file: Path, source_ref: str) -> dict[str, Any]:
    result = subprocess.run(["git", "-C", str(repo), "bundle", "create", str(output_file), "--all"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        return {"schema_id": "artifact-memory/git-bundle-receipt/v1", "receipt_id": "git-bundle-receipt://" + "0" * 64, "outcome": "failed", "bundle_digest": "sha-256:" + "0" * 64, "source_ref": source_ref, "authority_boundary": AUTHORITY_BOUNDARY}
    bundle_digest = _digest_bytes(output_file.read_bytes())
    body = {"outcome": "created", "bundle_digest": bundle_digest, "source_ref": source_ref, "authority_boundary": AUTHORITY_BOUNDARY}
    return {"schema_id": "artifact-memory/git-bundle-receipt/v1", "receipt_id": "git-bundle-receipt://" + hashlib.sha256(_canonical(body)).hexdigest(), **body}
