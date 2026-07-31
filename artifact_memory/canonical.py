"""Shared canonical JSON and streaming digest helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, BinaryIO


CHUNK_SIZE = 1024 * 1024


def canonical_bytes(value: Any) -> bytes:
    """Serialize a value with the Artifact Memory v0 canonical JSON profile."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return "sha-256:" + hashlib.sha256(data).hexdigest()


def sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(CHUNK_SIZE):
        digest.update(chunk)
    return "sha-256:" + digest.hexdigest()


def sha256_path(path: Path) -> str:
    with path.open("rb") as stream:
        return sha256_stream(stream)


def receipt_with_digest(schema_id: str, id_prefix: str, body: dict[str, Any]) -> dict[str, Any]:
    """Build a receipt whose identifier is the canonical digest of its body."""
    reserved = {"schema_id", "receipt_id"} & body.keys()
    if reserved:
        raise ValueError(f"receipt body contains reserved identity field: {sorted(reserved)[0]}")
    return {
        "schema_id": schema_id,
        "receipt_id": id_prefix + sha256_bytes(canonical_bytes(body)).removeprefix("sha-256:"),
        **body,
    }
