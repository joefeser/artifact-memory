"""Provider-free filesystem scan, verification, and content/tree diff."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any, Iterator


CHUNK_SIZE = 1024 * 1024
POLICY_REF = "scan-policy://reference-cli/v0"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_stream(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_SIZE):
            digest.update(chunk)
    return "sha-256:" + digest.hexdigest()


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


def _walk(root: Path) -> Iterator[tuple[Path, str]]:
    pending = [root]
    while pending:
        current = pending.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda item: item.name)
        except OSError:
            yield current, "unreadable"
            continue
        for entry in entries:
            if entry.is_symlink():
                yield Path(entry.path), "unsupported"
            elif entry.is_dir(follow_symlinks=False):
                yield Path(entry.path), "directory"
                pending.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                yield Path(entry.path), "file"
            else:
                yield Path(entry.path), "unsupported"


def scan_path(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Scan one root into a deterministic manifest and policy-bound receipt."""
    root = root.resolve()
    entries: list[dict[str, Any]] = []
    diagnostics: list[dict[str, str]] = []
    casefold_paths: dict[str, str] = {}
    for path, kind in _walk(root):
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            diagnostics.append({"code": "unsupported", "message": "entry is outside the declared root"})
            continue
        if kind == "directory":
            entry = {"path": relative, "kind": "directory"}
        elif kind == "file":
            try:
                entry = {"path": relative, "kind": "file", "byte_size": path.stat().st_size, "content_digest": _sha256_stream(path)}
            except (OSError, UnicodeError):
                diagnostics.append({"code": "unreadable", "message": "file could not be read"})
                continue
        else:
            diagnostics.append({"code": kind, "message": "entry kind is not supported by the v0 profile"})
            continue
        folded = relative.casefold()
        if folded in casefold_paths and casefold_paths[folded] != relative:
            diagnostics.append({"code": "collision", "message": "case-folded path collision detected"})
        casefold_paths[folded] = relative
        entries.append(entry)
    entries.sort(key=lambda entry: entry["path"])
    outcome = "complete" if not diagnostics else "partial"
    payload = {"schema_id": "artifact-memory/manifest/v1", "policy_ref": POLICY_REF, "comparison_profile": "v0-case-sensitive-unicode-codepoint", "completeness": outcome, "entries": entries}
    manifest_ref = _manifest_id(payload)
    manifest = {**payload, "manifest_id": manifest_ref, "tree_digest": _tree_digest(entries)}
    receipt = {"schema_id": "artifact-memory/scan-receipt/v1", "receipt_id": f"scan-receipt://reference-cli/{manifest_ref.removeprefix('manifest://')}", "policy_ref": POLICY_REF, "manifest_ref": manifest_ref, "outcome": outcome, "accounted_entry_count": len(entries), "diagnostics": diagnostics}
    return manifest, receipt


def verify_path(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    actual, receipt = scan_path(root)
    if actual["tree_digest"] != manifest.get("tree_digest"):
        return {"outcome": "digest-mismatch", "manifest_ref": manifest.get("manifest_id"), "actual_manifest_ref": actual["manifest_id"], "receipt": receipt}
    return {"outcome": "verified", "manifest_ref": manifest.get("manifest_id"), "actual_manifest_ref": actual["manifest_id"], "receipt": receipt}


def diff_manifests(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_entries = {entry["path"]: entry for entry in before.get("entries", [])}
    after_entries = {entry["path"]: entry for entry in after.get("entries", [])}
    added = sorted(set(after_entries) - set(before_entries))
    removed = sorted(set(before_entries) - set(after_entries))
    changed = sorted(path for path in set(before_entries) & set(after_entries) if before_entries[path] != after_entries[path])
    removed_by_digest = {before_entries[path].get("content_digest"): path for path in removed if before_entries[path].get("content_digest")}
    moved_candidates = []
    for path in added:
        digest = after_entries[path].get("content_digest")
        if digest in removed_by_digest:
            moved_candidates.append({"from": removed_by_digest[digest], "to": path, "content_digest": digest})
    return {"schema_id": "artifact-memory/diff-receipt/v1", "before_manifest_ref": before.get("manifest_id"), "after_manifest_ref": after.get("manifest_id"), "added": added, "removed": removed, "changed": changed, "moved_candidates": sorted(moved_candidates, key=lambda item: (item["from"], item["to"])), "limitations": ["moved-candidate is content/tree evidence only and does not prove semantic continuity"]}
