"""Immutable content-addressed registration in a local private vault."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


AUTHORITY_BOUNDARY = "registration does not grant execution, disclosure, or mutation authority"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def register_bytes(vault_root: Path, data: bytes, media_type: str = "application/octet-stream") -> dict[str, Any]:
    digest_hex = hashlib.sha256(data).hexdigest()
    digest = "sha-256:" + digest_hex
    objects = vault_root / "objects" / "sha256"
    objects.mkdir(parents=True, exist_ok=True)
    target = objects / digest_hex[:2] / digest_hex[2:]
    target.parent.mkdir(parents=True, exist_ok=True)
    outcome = "duplicate" if target.exists() else "registered"
    if outcome == "registered":
        fd, temporary = tempfile.mkstemp(prefix=".partial-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    content_ref = f"content://vault/{digest_hex}"
    artifact_version_ref = f"artifact-version://vault/{digest_hex}/1"
    body = {"outcome": outcome, "content_ref": content_ref, "artifact_version_ref": artifact_version_ref, "byte_size": len(data), "digest": digest, "authority_boundary": AUTHORITY_BOUNDARY}
    return {"schema_id": "artifact-memory/content-registration-receipt/v1", "receipt_id": "registration-receipt://" + hashlib.sha256(_canonical(body)).hexdigest(), **body, "media_type": media_type, "diagnostics": []}
