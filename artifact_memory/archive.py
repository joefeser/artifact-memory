"""Bounded ZIP inspection with explicit container/tree claim boundaries."""

from __future__ import annotations

import hashlib
import os
import stat
import zipfile
from pathlib import Path
from typing import Any, BinaryIO

from .canonical import canonical_bytes, receipt_with_digest, sha256_bytes, sha256_stream
from .schema_resources import load_schema
from .validator import ValidationFailure, validate


DEFAULT_MAX_ENTRIES = 10_000
DEFAULT_MAX_UNCOMPRESSED_BYTES = 16 * 1024 * 1024
AUTHORITY_BOUNDARY = "archive inspection grants no extraction, execution, mutation, disclosure, or trust authority"


def _diagnostic(code: str, message: str, path: str | None = None) -> dict[str, Any]:
    return {"code": code, "path": path, "message": message}


def _normalized_path(info: zipfile.ZipInfo) -> tuple[str | None, str | None]:
    normalized = info.filename.replace("\\", "/")
    if info.is_dir() and normalized.endswith("/"):
        normalized = normalized[:-1]
    parts = normalized.split("/")
    if (
        not normalized
        or normalized.startswith("/")
        or "\x00" in normalized
        or (len(normalized) >= 2 and normalized[0].isalpha() and normalized[1] == ":")
        or any(part in {"", ".", ".."} for part in parts)
    ):
        return None, "path-traversal"
    return normalized, None


def _entry_kind(info: zipfile.ZipInfo) -> str:
    if info.create_system != 3:
        return "directory" if info.is_dir() else "file"
    mode = info.external_attr >> 16
    kind = stat.S_IFMT(mode)
    if kind == stat.S_IFLNK:
        return "link"
    if kind not in {0, stat.S_IFREG, stat.S_IFDIR}:
        return "unsupported"
    return "directory" if info.is_dir() or kind == stat.S_IFDIR else "file"


def _base_receipt(
    *,
    outcome: str,
    container_digest: str | None,
    container_size: int | None,
    max_entries: int,
    max_uncompressed_bytes: int,
    completeness: str,
    entries: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    observed_digest = sha256_bytes(canonical_bytes(entries))
    manifest: dict[str, Any] | None = None
    manifest_digest: str | None = None
    relationship: dict[str, Any] | None = None
    if outcome == "supported" and container_digest is not None:
        manifest = {
            "schema_id": "artifact-memory/archive-extracted-tree-manifest/v1",
            "profile": "zip-v0-safe-files",
            "entries": entries,
        }
        manifest_digest = sha256_bytes(canonical_bytes(manifest))
        relationship = {
            "type": "container-extracts-to-tree",
            "container_content_digest": container_digest,
            "extracted_tree_manifest_digest": manifest_digest,
            "extraction_profile": "zip-v0-safe-files",
        }
    body = {
        "outcome": outcome,
        "format": "zip",
        "container": {
            "content_digest": container_digest,
            "byte_size": container_size,
            "integrity": "bytes-hashed" if container_digest is not None else "unavailable",
        },
        "limits": {"max_entries": max_entries, "max_uncompressed_bytes": max_uncompressed_bytes},
        "inspection_completeness": completeness,
        "entries": entries,
        "observed_entry_set_digest": observed_digest,
        "extracted_tree_manifest": manifest,
        "extracted_tree_manifest_digest": manifest_digest,
        "relationship": relationship,
        "diagnostics": diagnostics,
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": [
            "container bytes and extracted-tree manifest identity are separate claims",
            "partial or unsupported inspection establishes no extracted-tree manifest relationship",
            "inspection does not write or execute archive entries",
        ],
    }
    receipt = receipt_with_digest("artifact-memory/archive-receipt/v2", "archive-inspection-receipt://", body)
    validate_archive_receipt(receipt)
    return receipt


def validate_archive_receipt(receipt: dict[str, Any]) -> None:
    """Validate schema, receipt identity, and container/tree semantic bindings."""
    validate(receipt, load_schema("core", "archive-receipt.v2.schema.json"))
    body = {key: value for key, value in receipt.items() if key not in {"schema_id", "receipt_id"}}
    expected = receipt_with_digest(receipt["schema_id"], "archive-inspection-receipt://", body)
    if receipt["receipt_id"] != expected["receipt_id"]:
        raise ValidationFailure("archive-receipt-id-mismatch", "archive receipt identity does not match its canonical body", "$.receipt_id")
    entries = receipt["entries"]
    paths = [entry["path"] for entry in entries]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise ValidationFailure("archive-entry-order-invalid", "archive receipt entries must be unique and sorted", "$.entries")
    if receipt["observed_entry_set_digest"] != sha256_bytes(canonical_bytes(entries)):
        raise ValidationFailure("archive-entry-set-digest-mismatch", "observed entry set digest does not match entries", "$.observed_entry_set_digest")
    container = receipt["container"]
    if container["integrity"] == "bytes-hashed" and (container["content_digest"] is None or container["byte_size"] is None):
        raise ValidationFailure("archive-container-binding-invalid", "hashed container evidence requires digest and byte size", "$.container")
    if receipt["outcome"] in {"unsupported", "failed"} and entries:
        raise ValidationFailure("archive-outcome-entry-mismatch", "unsupported and failed receipts cannot admit entries", "$.entries")
    if receipt["outcome"] == "unsupported" and any(
        item["code"] not in {"encrypted-entry", "link-entry", "unsupported-compression", "unsupported-entry-kind"}
        for item in receipt["diagnostics"]
    ):
        raise ValidationFailure("archive-outcome-diagnostic-mismatch", "unsupported receipt contains a non-feature diagnostic", "$.diagnostics")
    if receipt["outcome"] != "supported":
        return
    manifest = receipt["extracted_tree_manifest"]
    relationship = receipt["relationship"]
    if manifest["entries"] != entries:
        raise ValidationFailure("archive-tree-entry-mismatch", "extracted-tree manifest entries do not match inspected entries", "$.extracted_tree_manifest.entries")
    manifest_digest = sha256_bytes(canonical_bytes(manifest))
    if receipt["extracted_tree_manifest_digest"] != manifest_digest:
        raise ValidationFailure("archive-tree-digest-mismatch", "extracted-tree manifest digest does not match manifest", "$.extracted_tree_manifest_digest")
    if relationship["container_content_digest"] != container["content_digest"] or relationship["extracted_tree_manifest_digest"] != manifest_digest:
        raise ValidationFailure("archive-relationship-binding-mismatch", "container/tree relationship does not bind receipt identities", "$.relationship")


def _inspect_open_zip(
    stream: BinaryIO,
    *,
    container_digest: str,
    container_size: int,
    max_uncompressed_bytes: int,
    max_entries: int,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    seen_exact: set[str] = set()
    seen_casefolded: set[str] = set()
    total = 0
    try:
        with zipfile.ZipFile(stream) as archive:
            for index, info in enumerate(archive.infolist()):
                if index >= max_entries:
                    diagnostics.append(_diagnostic("entry-count-limit", "archive exceeds the v0 entry-count limit"))
                    break
                normalized, path_failure = _normalized_path(info)
                if path_failure is not None:
                    diagnostics.append(_diagnostic(path_failure, "archive entry path is unsafe"))
                    continue
                assert normalized is not None
                if normalized in seen_exact:
                    diagnostics.append(_diagnostic("duplicate-entry", "archive repeats an exact normalized entry path", normalized))
                    continue
                folded = normalized.casefold()
                if folded in seen_casefolded:
                    diagnostics.append(_diagnostic("case-collision", "archive entry collides under Unicode case folding", normalized))
                    continue
                seen_exact.add(normalized)
                seen_casefolded.add(folded)

                kind = _entry_kind(info)
                if kind == "link":
                    diagnostics.append(_diagnostic("link-entry", "archive links are unsupported", normalized))
                    continue
                if kind == "unsupported":
                    diagnostics.append(_diagnostic("unsupported-entry-kind", "archive entry kind is unsupported", normalized))
                    continue
                if info.flag_bits & 0x1:
                    diagnostics.append(_diagnostic("encrypted-entry", "encrypted archive entries are unsupported", normalized))
                    continue
                if kind == "directory":
                    continue

                remaining = max_uncompressed_bytes - total
                if info.file_size > remaining:
                    diagnostics.append(_diagnostic("decompression-limit", "archive exceeds the v0 uncompressed-byte limit", normalized))
                    break
                try:
                    digest = hashlib.sha256()
                    byte_size = 0
                    limit_exceeded = False
                    with archive.open(info) as stream:
                        while chunk := stream.read(min(64 * 1024, remaining - byte_size + 1)):
                            byte_size += len(chunk)
                            if byte_size > remaining:
                                limit_exceeded = True
                                break
                            digest.update(chunk)
                except NotImplementedError:
                    diagnostics.append(_diagnostic("unsupported-compression", "archive compression method is unsupported", normalized))
                    continue
                except (OSError, RuntimeError, zipfile.BadZipFile):
                    diagnostics.append(_diagnostic("corrupt-entry", "archive entry failed integrity verification", normalized))
                    continue
                if limit_exceeded:
                    diagnostics.append(_diagnostic("decompression-limit", "archive exceeds the v0 uncompressed-byte limit", normalized))
                    break
                if byte_size != info.file_size:
                    diagnostics.append(_diagnostic("corrupt-entry", "archive entry size does not match its central-directory claim", normalized))
                    continue
                total += byte_size
                entries.append(
                    {
                        "path": normalized,
                        "kind": "file",
                        "byte_size": byte_size,
                        "content_digest": "sha-256:" + digest.hexdigest(),
                    }
                )
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
        return _base_receipt(
            outcome="failed",
            container_digest=container_digest,
            container_size=container_size,
            max_entries=max_entries,
            max_uncompressed_bytes=max_uncompressed_bytes,
            completeness="unavailable",
            entries=[],
            diagnostics=[_diagnostic("corrupt-container", "archive central directory is invalid")],
        )

    entries.sort(key=lambda item: item["path"])
    if not diagnostics:
        outcome, completeness = "supported", "complete"
    elif not entries and all(item["code"] in {"encrypted-entry", "link-entry", "unsupported-compression", "unsupported-entry-kind"} for item in diagnostics):
        outcome, completeness = "unsupported", "unavailable"
    else:
        outcome, completeness = "partial", "partial"
    return _base_receipt(
        outcome=outcome,
        container_digest=container_digest,
        container_size=container_size,
        max_entries=max_entries,
        max_uncompressed_bytes=max_uncompressed_bytes,
        completeness=completeness,
        entries=entries,
        diagnostics=diagnostics,
    )


def inspect_zip(
    path: Path,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> dict[str, Any]:
    """Inspect ZIP bytes in memory without extracting entries to the filesystem."""
    for value, name in ((max_entries, "max_entries"), (max_uncompressed_bytes, "max_uncompressed_bytes")):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValidationFailure("archive-limit-invalid", f"{name} must be a positive integer", f"$.{name}")

    try:
        with path.open("rb") as stream:
            before_size = os.fstat(stream.fileno()).st_size
            before_digest = sha256_stream(stream)
            stream.seek(0)
            receipt = _inspect_open_zip(
                stream,
                container_digest=before_digest,
                container_size=before_size,
                max_uncompressed_bytes=max_uncompressed_bytes,
                max_entries=max_entries,
            )
            stream.seek(0)
            after_digest = sha256_stream(stream)
            after_size = os.fstat(stream.fileno()).st_size
    except OSError:
        return _base_receipt(
            outcome="failed",
            container_digest=None,
            container_size=None,
            max_entries=max_entries,
            max_uncompressed_bytes=max_uncompressed_bytes,
            completeness="unavailable",
            entries=[],
            diagnostics=[_diagnostic("container-unavailable", "archive container bytes are unavailable")],
        )
    if before_digest != after_digest or before_size != after_size:
        return _base_receipt(
            outcome="failed",
            container_digest=None,
            container_size=None,
            max_entries=max_entries,
            max_uncompressed_bytes=max_uncompressed_bytes,
            completeness="unavailable",
            entries=[],
            diagnostics=[_diagnostic("container-changed-during-inspection", "archive container did not remain stable during inspection")],
        )
    return receipt
