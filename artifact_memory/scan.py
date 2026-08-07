"""Provider-free filesystem scan, verification, and content/tree diff."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator
from uuid import uuid4

from . import __version__
from .canonical import CHUNK_SIZE, CanonicalizationFailure, canonical_bytes, expected_receipt_id, receipt_with_digest
from .extensions import ExtensionFailure, preserve_extensions
from .schema_resources import load_schema
from .validator import ValidationFailure, validate

REFERENCE_ENDPOINT_REF = "endpoint://local/reference-cli"
SCAN_AUTHORITY_BOUNDARY = "filesystem observation grants no execution, disclosure, mutation, authenticity, trust, or authorization"
WINDOWS_RESERVED_COMPONENTS = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{suffix}" for suffix in (*range(1, 10), "¹", "²", "³")),
    *(f"lpt{suffix}" for suffix in (*range(1, 10), "¹", "²", "³")),
}
WINDOWS_FORBIDDEN_PATH_CHARACTERS = frozenset('<>:"|?*')


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


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_attempt_id() -> str:
    return f"urn:uuid:{uuid4()}"


def _policy_digest(policy: dict[str, Any]) -> str:
    payload = {key: value for key, value in policy.items() if key not in {"policy_id", "policy_digest"}}
    try:
        return "sha-256:" + hashlib.sha256(_canonical(payload)).hexdigest()
    except CanonicalizationFailure as exc:
        raise ValidationFailure("canonicalization-failed", str(exc), "$.policy") from exc


def _is_normalized_relative_path(value: str, *, allow_empty: bool = False) -> bool:
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    if value == "":
        return allow_empty
    normalized = PurePosixPath(value)
    parts = value.split("/")
    return not (
        value == "."
        or "\\" in value
        or any(character in WINDOWS_FORBIDDEN_PATH_CHARACTERS for character in value)
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or normalized.is_absolute()
        or normalized.as_posix() != value
        or any(part in {"", ".", ".."} or part.endswith((".", " ")) for part in parts)
        or any(part.split(".", 1)[0].casefold() in WINDOWS_RESERVED_COMPONENTS for part in parts)
    )


def _validate_policy_relative_path(value: str, path: str, *, allow_empty: bool) -> None:
    if not _is_normalized_relative_path(value, allow_empty=allow_empty):
        raise ValidationFailure("scan-policy-path-invalid", "scan policy path is not normalized", path)


def validate_scan_policy(policy: dict[str, Any]) -> None:
    """Validate one digest-bound v2 scan policy and implemented v0 behavior."""
    validate(policy, load_schema("core", "scan-policy.v2.schema.json"))
    try:
        preserve_extensions({}, {
            "schema_id": "artifact-memory/extension-bundle/v1",
            "extensions": policy.get("extensions", {}),
        })
    except ExtensionFailure as exc:
        raise ValidationFailure(exc.code, exc.message, "$.extensions") from exc
    prefixes = policy.get("exclusion_prefixes", [])
    if prefixes != sorted(set(prefixes)):
        raise ValidationFailure("scan-policy-invalid", "exclusion prefixes must be unique and sorted", "$.exclusion_prefixes")
    _validate_policy_relative_path(policy["root_relative_path"], "$.root_relative_path", allow_empty=True)
    for index, prefix in enumerate(prefixes):
        _validate_policy_relative_path(prefix, f"$.exclusion_prefixes[{index}]", allow_empty=False)
    expected_digest = _policy_digest(policy)
    expected_id = "scan-policy://sha-256/" + expected_digest.removeprefix("sha-256:")
    if policy["policy_digest"] != expected_digest or policy["policy_id"] != expected_id:
        raise ValidationFailure("scan-policy-identity-invalid", "scan policy identity does not match its canonical body")
    if policy["follow_symlinks"] is not False:
        raise ValidationFailure("scan-policy-unsupported", "the v0 reference scanner does not follow links", "$.follow_symlinks")
    if policy["comparison_profile"] != "v0-case-sensitive-unicode-codepoint":
        raise ValidationFailure("scan-policy-unsupported", "comparison profile is unsupported", "$.comparison_profile")


def _build_scan_policy(endpoint_ref: str, root_relative_path: str, exclusion_prefixes: tuple[str, ...]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_id": "artifact-memory/scan-policy/v2",
        "endpoint_ref": endpoint_ref,
        "root_relative_path": root_relative_path,
        "comparison_profile": "v0-case-sensitive-unicode-codepoint",
        "follow_symlinks": False,
        "exclusion_prefixes": sorted(exclusion_prefixes),
    }
    digest = _policy_digest(body)
    return {
        **body,
        "policy_id": "scan-policy://sha-256/" + digest.removeprefix("sha-256:"),
        "policy_digest": digest,
    }


def make_scan_policy(
    *,
    endpoint_ref: str = REFERENCE_ENDPOINT_REF,
    root_relative_path: str = "",
    exclusion_prefixes: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Create the effective digest-bound policy used by one scan attempt."""
    policy = _build_scan_policy(endpoint_ref, root_relative_path, exclusion_prefixes)
    validate_scan_policy(policy)
    return policy


# Compatibility constants remain computation-only; schema I/O starts with a scan.
REFERENCE_POLICY = _build_scan_policy(REFERENCE_ENDPOINT_REF, "", ())
POLICY_REF = REFERENCE_POLICY["policy_id"]


def _tree_digest(entries: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for entry in entries:
        if entry["kind"] == "directory":
            lines.append(f"directory\t{entry['path']}\n")
        else:
            lines.append(f"file\t{entry['path']}\t{entry['content_digest']}\t{entry['byte_size']}\n")
    digest = hashlib.sha256("".join(lines).encode("utf-8"))
    return "sha-256:" + digest.hexdigest()


def _manifest_id(payload: dict[str, Any], path: str = "$") -> str:
    try:
        canonical = _canonical(payload)
    except CanonicalizationFailure as exc:
        raise ValidationFailure("canonicalization-failed", str(exc), path) from exc
    return "manifest://" + hashlib.sha256(canonical).hexdigest()


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


def _hash_exact_size(stream: Any, byte_size: int) -> str:
    digest = hashlib.sha256()
    remaining = byte_size
    while remaining:
        chunk = stream.read(min(CHUNK_SIZE, remaining))
        if not chunk:
            raise _ObservationFailure("unstable", "file changed while it was being admitted")
        digest.update(chunk)
        remaining -= len(chunk)
    return "sha-256:" + digest.hexdigest()


def _hash_regular_file(path: Path, root: Path, remaining_budget: int | None = None) -> tuple[int, str]:
    try:
        _reject_linked_path(root, path)
        before = path.stat(follow_symlinks=False)
        if _is_link_or_reparse(before) or not stat.S_ISREG(before.st_mode):
            raise _ObservationFailure("unsupported", "entry changed to a non-regular file")
        if getattr(before, "st_nlink", 1) > 1:
            raise _ObservationFailure("unsupported", "hard-linked files are outside the v0 ordinary-tree profile")
        allocated_blocks = getattr(before, "st_blocks", None)
        if isinstance(allocated_blocks, int) and before.st_size > 0 and allocated_blocks * 512 < before.st_size:
            raise _ObservationFailure("unsupported", "sparse files are outside the v0 ordinary-tree profile")
        if remaining_budget is not None and before.st_size > remaining_budget:
            raise _ObservationFailure("resource-limit", "scan byte limit reached")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise _ObservationFailure("unsupported", "entry changed to a non-regular file")
            if not _same_file_observation(before, opened):
                raise _ObservationFailure("unstable", "file changed while it was being admitted")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                digest = _hash_exact_size(stream, opened.st_size)
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
    except ValueError as exc:
        raise _ObservationFailure("unsupported", "entry path is not a portable UTF-8 relative path") from exc
    if not _is_normalized_relative_path(relative):
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
        if not _is_normalized_relative_path(entry_path):
            raise ValidationFailure("manifest-path-invalid", "manifest path is not normalized", f"{entry_pointer}.path")
        normalized = PurePosixPath(entry_path)
        parent = normalized.parent
        while parent != PurePosixPath("."):
            if parent.as_posix() not in directory_paths:
                raise ValidationFailure("manifest-parent-missing", "manifest entry parent directory is missing", f"{entry_pointer}.path")
            parent = parent.parent
        if entry["kind"] == "directory":
            directory_paths.add(entry_path)
    identity_payload = {key: value for key, value in manifest.items() if key not in {"manifest_id", "tree_digest"}}
    if manifest["tree_digest"] != _tree_digest(entries) or manifest["manifest_id"] != _manifest_id(identity_payload, path):
        raise ValidationFailure("manifest-identity-invalid", "manifest identity does not match its canonical body", path)


def validate_scan_receipt(receipt: dict[str, Any], policy: dict[str, Any] | None = None, manifest: dict[str, Any] | None = None) -> None:
    """Validate v2 receipt identity, chronology, counts, and optional bindings."""
    validate(receipt, load_schema("core", "scan-receipt.v2.schema.json"))
    started = datetime.fromisoformat(receipt["started_at"].replace("Z", "+00:00"))
    ended = datetime.fromisoformat(receipt["ended_at"].replace("Z", "+00:00"))
    if ended < started:
        raise ValidationFailure("scan-receipt-time-invalid", "scan end time precedes start time", "$.ended_at")
    if receipt["excluded_entry_count"] != len(receipt["exclusions"]):
        raise ValidationFailure("scan-receipt-count-invalid", "excluded entry count does not match exclusions", "$.excluded_entry_count")
    if receipt["receipt_id"] != expected_receipt_id(
        receipt, "scan-receipt://sha-256/"
    ):
        raise ValidationFailure("scan-receipt-identity-invalid", "scan receipt identity does not match its canonical body")
    if policy is not None:
        validate_scan_policy(policy)
        expected_scope = {"endpoint_ref": policy["endpoint_ref"], "root_relative_path": policy["root_relative_path"]}
        if receipt["policy_ref"] != policy["policy_id"] or receipt["policy_digest"] != policy["policy_digest"] or receipt["scope"] != expected_scope:
            raise ValidationFailure("scan-receipt-policy-mismatch", "scan receipt does not bind the supplied policy")
    if manifest is not None:
        validate_manifest_identity(manifest)
        if receipt["manifest_ref"] != manifest["manifest_id"] or receipt["manifest_tree_digest"] != manifest["tree_digest"]:
            raise ValidationFailure("scan-receipt-manifest-mismatch", "scan receipt does not bind the supplied manifest")
        if receipt["accounted_entry_count"] != len(manifest["entries"]):
            raise ValidationFailure("scan-receipt-count-invalid", "accounted entry count does not match the supplied manifest", "$.accounted_entry_count")


def _excluded_by(relative: str, prefixes: tuple[str, ...]) -> str | None:
    return next((prefix for prefix in prefixes if relative == prefix or relative.startswith(prefix + "/")), None)


def _walk(root: Path, limits: ScanLimits | None = None, exclusion_prefixes: tuple[str, ...] = ()) -> Iterator[tuple[Path, str]]:
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
                    item_path = Path(item.path)
                    try:
                        relative = _normalized_relative_path(item_path, root)
                    except _ObservationFailure:
                        entries.append((item.name, item_path, "unsupported"))
                        continue
                    if _excluded_by(relative, exclusion_prefixes) is not None:
                        entries.append((item.name, item_path, "excluded"))
                        continue
                    metadata = item.stat(follow_symlinks=False)
                    if _is_link_or_reparse(metadata):
                        kind = "unsupported"
                    elif stat.S_ISDIR(metadata.st_mode):
                        kind = "directory"
                    elif stat.S_ISREG(metadata.st_mode):
                        kind = "file"
                    else:
                        kind = "unsupported"
                    entries.append((item.name, item_path, kind))
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


def scan_path(root: Path, limits: ScanLimits | None = None, policy: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Scan one root into a deterministic manifest and policy-bound receipt."""
    attempt_id = _new_attempt_id()
    started_at = _utc_now()
    caller_limits = limits or ScanLimits()
    if policy is None:
        policy = make_scan_policy()
    else:
        validate_scan_policy(policy)
    effective_limits = caller_limits
    exclusion_prefixes = tuple(policy.get("exclusion_prefixes", []))
    root = Path(os.path.abspath(root))
    entries: list[dict[str, Any]] = []
    diagnostics: list[dict[str, str]] = []
    exclusions: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    casefold_paths: dict[str, str] = {}
    total_bytes = 0
    cancelled = False
    root_failed = False
    incomplete = False
    for path, kind in _walk(root, effective_limits, exclusion_prefixes):
        if kind == "cancelled":
            warning = {"code": "cancelled", "message": "scan cancelled by caller"}
            warnings.append(warning)
            diagnostics.append(warning)
            cancelled = True
            break
        if kind == "resource-limit":
            warning = {"code": "resource-limit", "message": "scan resource limit reached"}
            warnings.append(warning)
            diagnostics.append(warning)
            incomplete = True
            break
        relative: str | None = None
        if path != root:
            try:
                relative = _normalized_relative_path(path, root)
            except _ObservationFailure as exc:
                failure = {"code": exc.code, "message": exc.message}
                failures.append(failure)
                diagnostics.append(failure)
                incomplete = True
                continue
        if kind == "excluded":
            assert relative is not None
            rule = _excluded_by(relative, exclusion_prefixes)
            exclusion = {"relative_path": relative, "rule": f"prefix:{rule}"}
            exclusions.append(exclusion)
            diagnostics.append({"code": "excluded", "message": "entry excluded by declared policy", "relative_path": relative})
            continue
        if kind not in {"directory", "file"}:
            failure = {"code": kind, "message": "entry could not be admitted by the v0 profile"}
            if relative is not None:
                failure["relative_path"] = relative
            failures.append(failure)
            diagnostics.append(failure)
            incomplete = True
            if path == root:
                root_failed = True
            continue
        assert relative is not None
        if kind == "directory":
            entry = {"path": relative, "kind": "directory"}
        elif kind == "file":
            try:
                remaining_budget = None if effective_limits.max_bytes is None else effective_limits.max_bytes - total_bytes
                byte_size, content_digest = _hash_regular_file(path, root, remaining_budget)
                entry = {"path": relative, "kind": "file", "byte_size": byte_size, "content_digest": content_digest}
                total_bytes += byte_size
            except _ObservationFailure as exc:
                incomplete = True
                if exc.code == "resource-limit":
                    warning = {"code": exc.code, "message": exc.message, "relative_path": relative}
                    warnings.append(warning)
                    diagnostics.append(warning)
                    break
                failure = {"code": exc.code, "message": exc.message, "relative_path": relative}
                failures.append(failure)
                diagnostics.append(failure)
                continue
        folded = relative.casefold()
        if folded in casefold_paths and casefold_paths[folded] != relative:
            warning = {"code": "collision", "message": "case-folded path collision detected", "relative_path": relative}
            warnings.append(warning)
            diagnostics.append(warning)
            incomplete = True
        casefold_paths[folded] = relative
        entries.append(entry)
    entries.sort(key=lambda entry: entry["path"])
    if cancelled:
        outcome = "cancelled"
    elif root_failed:
        outcome = "failed"
    elif incomplete:
        outcome = "partial"
    else:
        outcome = "complete"
    payload = {"schema_id": "artifact-memory/manifest/v1", "policy_ref": policy["policy_id"], "comparison_profile": "v0-case-sensitive-unicode-codepoint", "completeness": outcome, "entries": entries}
    manifest_ref = _manifest_id(payload)
    manifest = {**payload, "manifest_id": manifest_ref, "tree_digest": _tree_digest(entries)}
    ended_at = _utc_now()
    receipt = receipt_with_digest(
        "artifact-memory/scan-receipt/v2",
        "scan-receipt://sha-256/",
        {
            "attempt_id": attempt_id,
            "policy_ref": policy["policy_id"],
            "policy_digest": policy["policy_digest"],
            "scope": {"endpoint_ref": policy["endpoint_ref"], "root_relative_path": policy["root_relative_path"]},
            "started_at": started_at,
            "ended_at": ended_at,
            "implementation": {"name": "artifact-memory-python", "version": __version__},
            "attempt_limits": {
                **({"max_entries": effective_limits.max_entries} if effective_limits.max_entries is not None else {}),
                **({"max_bytes": effective_limits.max_bytes} if effective_limits.max_bytes is not None else {}),
                "cancellation_enabled": effective_limits.cancellation_check is not None,
            },
            "manifest_ref": manifest_ref,
            "manifest_tree_digest": manifest["tree_digest"],
            "outcome": outcome,
            "accounted_entry_count": len(entries),
            "excluded_entry_count": len(exclusions),
            "exclusions": exclusions,
            "warnings": warnings,
            "failures": failures,
            "diagnostics": diagnostics,
            "authority_boundary": SCAN_AUTHORITY_BOUNDARY,
        },
    )
    validate_manifest_identity(manifest)
    validate_scan_receipt(receipt, policy, manifest)
    return manifest, receipt


def verify_path(root: Path, manifest: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        validate_manifest_identity(manifest)
    except ValidationFailure as exc:
        return {
            "outcome": "rejected",
            "manifest_ref": manifest.get("manifest_id") if isinstance(manifest, dict) else None,
            "diagnostics": [{"code": exc.code, "path": exc.path, "message": exc.message}],
        }
    if policy is None:
        effective_policy = make_scan_policy()
        if manifest["policy_ref"] != effective_policy["policy_id"]:
            return {
                "outcome": "policy-required",
                "manifest_ref": manifest["manifest_id"],
                "diagnostics": [
                    {
                        "code": "scan-policy-required",
                        "path": "$.policy_ref",
                        "message": "verification requires the exact digest-bound scan policy",
                        "policy_ref": manifest["policy_ref"],
                    }
                ],
            }
    else:
        effective_policy = policy
    try:
        validate_scan_policy(effective_policy)
    except ValidationFailure as exc:
        return {
            "outcome": "rejected",
            "manifest_ref": manifest.get("manifest_id"),
            "diagnostics": [{"code": exc.code, "path": exc.path, "message": exc.message}],
        }
    if manifest["policy_ref"] != effective_policy["policy_id"]:
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
    actual, receipt = scan_path(root, policy=effective_policy)
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
