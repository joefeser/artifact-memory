"""Provider-free filesystem scan, verification, and content/tree diff."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator

from .canonical import canonical_bytes, receipt_with_digest, sha256_stream
from .schema_resources import load_schema
from .validator import ValidationFailure, validate

POLICY_REF = "scan-policy://reference-cli/v0"


@dataclass(frozen=True)
class ScanLimits:
    """Optional caller-owned bounds for a single scan."""

    max_entries: int | None = None
    max_bytes: int | None = None
    cancellation_check: Callable[[], bool] | None = None


_canonical = canonical_bytes


class _ObservationFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _tree_digest(entries: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for entry in entries:
        if entry["kind"] == "directory":
            lines.append(f"directory\t{entry['path']}\n")
        else:
            lines.append(f"file\t{entry['path']}\t{entry['content_digest']}\t{entry['byte_size']}\n")
    digest = hashlib.sha256("".join(lines).encode("utf-8"))
    return "sha-256:" + digest.hexdigest()


def _manifest_id(payload: dict[str, Any]) -> str:
    return "manifest://" + hashlib.sha256(_canonical(payload)).hexdigest()


def _same_file_observation(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        left.st_size,
        left.st_mtime_ns,
        left.st_ctime_ns,
    ) == (
        right.st_dev,
        right.st_ino,
        right.st_size,
        right.st_mtime_ns,
        right.st_ctime_ns,
    )


def _is_link_or_reparse(metadata: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(metadata.st_mode) or bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag)


def _reject_linked_path(root: Path, path: Path) -> None:
    current = root
    parts = path.relative_to(root).parts
    for part in (None, *parts):
        if part is not None:
            current = current / part
        try:
            metadata = os.lstat(current)
        except OSError as exc:
            raise _ObservationFailure("unreadable", "entry path could not be observed") from exc
        if _is_link_or_reparse(metadata):
            raise _ObservationFailure("unsupported", "entry path contains a link or reparse point")


def _hash_regular_file(path: Path, root: Path) -> tuple[int, str]:
    try:
        _reject_linked_path(root, path)
        before = path.stat(follow_symlinks=False)
        if _is_link_or_reparse(before) or not stat.S_ISREG(before.st_mode):
            raise _ObservationFailure("unsupported", "entry changed to a non-regular file")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise _ObservationFailure("unsupported", "entry changed to a non-regular file")
            if not _same_file_observation(before, opened):
                raise _ObservationFailure("unstable", "file changed while it was being admitted")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                digest = sha256_stream(stream)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        _reject_linked_path(root, path)
        current = path.stat(follow_symlinks=False)
    except _ObservationFailure:
        raise
    except OSError as exc:
        raise _ObservationFailure("unreadable", "file could not be read") from exc
    if not _same_file_observation(opened, after) or not _same_file_observation(after, current):
        raise _ObservationFailure("unstable", "file changed while it was being admitted")
    return after.st_size, digest


def _normalized_relative_path(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root).as_posix()
        relative.encode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise _ObservationFailure("unsupported", "entry path is not a portable UTF-8 relative path") from exc
    if (
        relative in {"", "."}
        or "\\" in relative
        or PurePosixPath(relative).is_absolute()
        or PurePosixPath(relative).as_posix() != relative
        or any(part in {"", ".", ".."} for part in relative.split("/"))
    ):
        raise _ObservationFailure("unsupported", "entry path is not normalized for the v0 profile")
    return relative


def validate_manifest_identity(manifest: dict[str, Any], path: str = "$") -> None:
    """Validate schema, normalized entry invariants, and digest-bound identity."""
    validate(manifest, load_schema("core", "manifest.v1.schema.json"), path)
    entries = manifest["entries"]
    entry_paths = [entry["path"] for entry in entries]
    if entry_paths != sorted(entry_paths) or len(entry_paths) != len(set(entry_paths)):
        raise ValidationFailure("manifest-entry-order-invalid", "manifest paths must be unique and sorted", f"{path}.entries")
    directory_paths: set[str] = set()
    for index, entry in enumerate(entries):
        entry_path = entry["path"]
        entry_pointer = f"{path}.entries[{index}]"
        try:
            normalized = PurePosixPath(entry_path)
            entry_path.encode("utf-8")
        except UnicodeError as exc:
            raise ValidationFailure("manifest-path-invalid", "manifest path must be UTF-8", f"{entry_pointer}.path") from exc
        if (
            entry_path in {"", "."}
            or "\\" in entry_path
            or normalized.is_absolute()
            or normalized.as_posix() != entry_path
            or any(part in {"", ".", ".."} for part in entry_path.split("/"))
        ):
            raise ValidationFailure("manifest-path-invalid", "manifest path is not normalized", f"{entry_pointer}.path")
        if entry["kind"] == "file":
            if "byte_size" not in entry or "content_digest" not in entry:
                raise ValidationFailure("manifest-entry-invalid", "file entry requires byte size and content digest", entry_pointer)
        elif "byte_size" in entry or "content_digest" in entry:
            raise ValidationFailure("manifest-entry-invalid", "directory entry cannot carry file content fields", entry_pointer)
        parent = normalized.parent
        while parent != PurePosixPath("."):
            if parent.as_posix() not in directory_paths:
                raise ValidationFailure("manifest-parent-missing", "manifest entry parent directory is missing", f"{entry_pointer}.path")
            parent = parent.parent
        if entry["kind"] == "directory":
            directory_paths.add(entry_path)
    identity_payload = {key: value for key, value in manifest.items() if key not in {"manifest_id", "tree_digest"}}
    if manifest["tree_digest"] != _tree_digest(entries) or manifest["manifest_id"] != _manifest_id(identity_payload):
        raise ValidationFailure("manifest-identity-invalid", "manifest identity does not match its canonical body", path)


def _walk(root: Path, limits: ScanLimits | None = None) -> Iterator[tuple[Path, str]]:
    pending = [root]
    enumerated = 0
    while pending:
        current = pending.pop()
        try:
            before = os.lstat(current)
            if _is_link_or_reparse(before) or not stat.S_ISDIR(before.st_mode):
                yield current, "unsupported"
                continue
            entries: list[tuple[str, Path, str]] = []
            with os.scandir(current) as directory:
                for item in directory:
                    if limits and limits.cancellation_check and limits.cancellation_check():
                        yield current, "cancelled"
                        return
                    if limits and limits.max_entries is not None and enumerated + len(entries) >= limits.max_entries:
                        yield current, "resource-limit"
                        return
                    metadata = item.stat(follow_symlinks=False)
                    if _is_link_or_reparse(metadata):
                        kind = "unsupported"
                    elif stat.S_ISDIR(metadata.st_mode):
                        kind = "directory"
                    elif stat.S_ISREG(metadata.st_mode):
                        kind = "file"
                    else:
                        kind = "unsupported"
                    entries.append((item.name, Path(item.path), kind))
            after = os.lstat(current)
            if not _same_file_observation(before, after):
                yield current, "unstable"
                continue
        except OSError:
            yield current, "unreadable"
            continue
        for _, path, kind in sorted(entries, key=lambda entry: entry[0]):
            enumerated += 1
            yield path, kind
            if kind == "directory":
                pending.append(path)


def scan_path(root: Path, limits: ScanLimits | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Scan one root into a deterministic manifest and policy-bound receipt."""
    root = Path(os.path.abspath(root))
    entries: list[dict[str, Any]] = []
    diagnostics: list[dict[str, str]] = []
    casefold_paths: dict[str, str] = {}
    total_bytes = 0
    cancelled = False
    root_failed = False
    for path, kind in _walk(root, limits):
        if kind == "cancelled":
            diagnostics.append({"code": "cancelled", "message": "scan cancelled by caller"})
            cancelled = True
            break
        if kind == "resource-limit":
            diagnostics.append({"code": "resource-limit", "message": "scan entry limit reached"})
            break
        if kind not in {"directory", "file"}:
            diagnostics.append({"code": kind, "message": "entry could not be admitted by the v0 profile"})
            if path == root:
                root_failed = True
            continue
        try:
            relative = _normalized_relative_path(path, root)
        except _ObservationFailure as exc:
            diagnostics.append({"code": exc.code, "message": exc.message})
            continue
        if kind == "directory":
            entry = {"path": relative, "kind": "directory"}
        elif kind == "file":
            try:
                byte_size, content_digest = _hash_regular_file(path, root)
                if limits and limits.max_bytes is not None and total_bytes + byte_size > limits.max_bytes:
                    diagnostics.append({"code": "resource-limit", "message": "scan byte limit reached"})
                    break
                entry = {"path": relative, "kind": "file", "byte_size": byte_size, "content_digest": content_digest}
                total_bytes += byte_size
            except _ObservationFailure as exc:
                diagnostics.append({"code": exc.code, "message": exc.message})
                continue
        folded = relative.casefold()
        if folded in casefold_paths and casefold_paths[folded] != relative:
            diagnostics.append({"code": "collision", "message": "case-folded path collision detected"})
        casefold_paths[folded] = relative
        entries.append(entry)
    entries.sort(key=lambda entry: entry["path"])
    outcome = "cancelled" if cancelled else ("failed" if root_failed else ("complete" if not diagnostics else "partial"))
    payload = {"schema_id": "artifact-memory/manifest/v1", "policy_ref": POLICY_REF, "comparison_profile": "v0-case-sensitive-unicode-codepoint", "completeness": outcome, "entries": entries}
    manifest_ref = _manifest_id(payload)
    manifest = {**payload, "manifest_id": manifest_ref, "tree_digest": _tree_digest(entries)}
    receipt = receipt_with_digest(
        "artifact-memory/scan-receipt/v1",
        "scan-receipt://reference-cli/",
        {
            "policy_ref": POLICY_REF,
            "manifest_ref": manifest_ref,
            "outcome": outcome,
            "accounted_entry_count": len(entries),
            "diagnostics": diagnostics,
        },
    )
    validate_manifest_identity(manifest)
    validate(receipt, load_schema("core", "scan-receipt.v1.schema.json"))
    return manifest, receipt


def verify_path(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    try:
        validate_manifest_identity(manifest)
    except ValidationFailure as exc:
        return {
            "outcome": "rejected",
            "manifest_ref": manifest.get("manifest_id") if isinstance(manifest, dict) else None,
            "diagnostics": [{"code": exc.code, "path": exc.path, "message": exc.message}],
        }
    if manifest["policy_ref"] != POLICY_REF:
        return {
            "outcome": "unsupported",
            "manifest_ref": manifest["manifest_id"],
            "diagnostics": [
                {
                    "code": "scan-policy-unsupported",
                    "path": "$.policy_ref",
                    "message": "reference verifier does not implement the declared scan policy",
                }
            ],
        }
    actual, receipt = scan_path(root)
    if manifest.get("completeness") != "complete" or actual["completeness"] != "complete":
        return {
            "outcome": "incomplete",
            "manifest_ref": manifest.get("manifest_id"),
            "actual_manifest_ref": actual["manifest_id"],
            "receipt": receipt,
        }
    if actual["tree_digest"] != manifest.get("tree_digest"):
        return {"outcome": "digest-mismatch", "manifest_ref": manifest.get("manifest_id"), "actual_manifest_ref": actual["manifest_id"], "receipt": receipt}
    return {"outcome": "verified", "manifest_ref": manifest.get("manifest_id"), "actual_manifest_ref": actual["manifest_id"], "receipt": receipt}


def diff_manifests(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    validate_manifest_identity(before, "$.before")
    validate_manifest_identity(after, "$.after")
    if before["policy_ref"] != after["policy_ref"]:
        raise ValidationFailure(
            "scan-policy-mismatch",
            "diff input manifests must use the same scan policy",
            "$.after.policy_ref",
        )
    before_entries = {entry["path"]: entry for entry in before.get("entries", [])}
    after_entries = {entry["path"]: entry for entry in after.get("entries", [])}
    added = sorted(set(after_entries) - set(before_entries))
    removed = sorted(set(before_entries) - set(after_entries))
    changed = sorted(path for path in set(before_entries) & set(after_entries) if before_entries[path] != after_entries[path])
    removed_by_digest: dict[str, list[str]] = {}
    for path in removed:
        digest = before_entries[path].get("content_digest")
        if digest:
            removed_by_digest.setdefault(digest, []).append(path)
    moved_candidates = []
    for path in added:
        digest = after_entries[path].get("content_digest")
        if digest in removed_by_digest:
            for previous_path in sorted(removed_by_digest[digest]):
                moved_candidates.append({"from": previous_path, "to": path, "content_digest": digest})
    complete = before["completeness"] == "complete" and after["completeness"] == "complete"
    diagnostics = []
    if not complete:
        diagnostics.append(
            {
                "code": "input-manifest-incomplete",
                "message": "diff covers only entries accounted for by the input manifests",
            }
        )
    limitations = ["moved-candidate is content/tree evidence only and does not prove semantic continuity"]
    if not complete:
        limitations.append("partial input manifests prevent a complete filesystem change claim")
    receipt = {
        "schema_id": "artifact-memory/diff-receipt/v1",
        "outcome": "complete" if complete else "partial",
        "before_manifest_ref": before["manifest_id"],
        "before_completeness": before["completeness"],
        "after_manifest_ref": after["manifest_id"],
        "after_completeness": after["completeness"],
        "added": added,
        "removed": removed,
        "changed": changed,
        "moved_candidates": sorted(moved_candidates, key=lambda item: (item["from"], item["to"])),
        "diagnostics": diagnostics,
        "limitations": limitations,
    }
    validate(receipt, load_schema("core", "diff-receipt.v1.schema.json"))
    return receipt
