"""Bounded archive inspection with explicit unsafe and partial outcomes."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import PurePosixPath
from pathlib import Path
from typing import Any


def _digest(data: bytes) -> str:
    return "sha-256:" + hashlib.sha256(data).hexdigest()


def inspect_zip(path: Path, max_uncompressed_bytes: int = 16 * 1024 * 1024) -> dict[str, Any]:
    container_digest = _digest(path.read_bytes())
    entries: list[dict[str, Any]] = []
    diagnostics: list[dict[str, str]] = []
    seen: set[str] = set()
    total = 0
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                normalized = info.filename.replace("\\", "/")
                parsed = PurePosixPath(normalized)
                if parsed.is_absolute() or ".." in parsed.parts:
                    diagnostics.append({"code": "path-traversal", "message": "archive entry path is unsafe"})
                    continue
                if normalized.casefold() in {item.casefold() for item in seen}:
                    diagnostics.append({"code": "collision", "message": "archive entry has a case-folded duplicate"})
                    continue
                if info.flag_bits & 0x1:
                    diagnostics.append({"code": "encrypted", "message": "encrypted archive entry is unsupported"})
                    continue
                if info.is_dir():
                    seen.add(normalized)
                    continue
                total += info.file_size
                if total > max_uncompressed_bytes:
                    diagnostics.append({"code": "decompression-limit", "message": "archive exceeds the v0 decompression limit"})
                    break
                try:
                    data = archive.read(info)
                except (OSError, RuntimeError, zipfile.BadZipFile):
                    diagnostics.append({"code": "corrupt", "message": "archive entry could not be read"})
                    continue
                seen.add(normalized)
                entries.append({"path": normalized, "byte_size": len(data), "content_digest": _digest(data)})
    except (OSError, zipfile.BadZipFile):
        return {"schema_id": "artifact-memory/archive-receipt/v1", "outcome": "failed", "container_digest": container_digest, "entries": [], "limitations": ["archive could not be inspected"], "diagnostics": [{"code": "corrupt", "message": "archive container is invalid"}]}
    entries.sort(key=lambda item: item["path"])
    outcome = "supported" if not diagnostics else "partial"
    tree_lines = "".join(f"file\t{entry['path']}\t{entry['content_digest']}\t{entry['byte_size']}\n" for entry in entries)
    return {"schema_id": "artifact-memory/archive-receipt/v1", "outcome": outcome, "container_digest": container_digest, "entries": entries, "extracted_tree_digest": _digest(tree_lines.encode()), "limitations": ["container bytes and extracted-tree identity are separate claims", "archive inspection does not execute content"], "diagnostics": diagnostics}
