"""Shared canonical JSON and streaming digest helpers."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, BinaryIO


CHUNK_SIZE = 1024 * 1024
MAX_INTEROPERABLE_INTEGER = 9_007_199_254_740_991


class CanonicalizationFailure(ValueError):
    """Raised when a value is outside the portable v0 canonical profile."""


def _check_canonical_value(value: Any, path: str = "$", ancestors: set[int] | None = None) -> None:
    ancestors = set() if ancestors is None else ancestors
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > MAX_INTEROPERABLE_INTEGER:
            raise CanonicalizationFailure(f"integer outside interoperable range at {path}")
        return
    if isinstance(value, float):
        detail = "non-finite number" if not math.isfinite(value) else "fractional number"
        raise CanonicalizationFailure(f"{detail} is unsupported at {path}")
    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise CanonicalizationFailure(f"unpaired Unicode surrogate is unsupported at {path}")
        return
    if isinstance(value, list):
        identity = id(value)
        if identity in ancestors:
            raise CanonicalizationFailure(f"cyclic container is unsupported at {path}")
        ancestors.add(identity)
        try:
            for index, item in enumerate(value):
                _check_canonical_value(item, f"{path}[{index}]", ancestors)
        finally:
            ancestors.remove(identity)
        return
    if isinstance(value, dict):
        identity = id(value)
        if identity in ancestors:
            raise CanonicalizationFailure(f"cyclic container is unsupported at {path}")
        ancestors.add(identity)
        try:
            for key, item in value.items():
                if not isinstance(key, str):
                    raise CanonicalizationFailure(f"object key is not a string at {path}")
                _check_canonical_value(key, f"{path}.<key>", ancestors)
                _check_canonical_value(item, f"{path}.{key}", ancestors)
        finally:
            ancestors.remove(identity)
        return
    raise CanonicalizationFailure(f"non-JSON value is unsupported at {path}")


def canonical_bytes(value: Any) -> bytes:
    """Serialize a value with the Artifact Memory v0 canonical JSON profile."""
    _check_canonical_value(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
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
