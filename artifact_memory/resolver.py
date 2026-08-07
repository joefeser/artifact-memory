"""Logical endpoint resolution with machine-local configuration outside records."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Any


AUTHORITY_BOUNDARY = "local resolution does not bypass local authorization"


def resolve(configs: list[dict[str, Any]], endpoint_ref: str, relative_path: str) -> dict[str, Any]:
    normalized = relative_path
    portable = isinstance(normalized, str) and bool(normalized) and "\\" not in normalized and "://" not in normalized and "?" not in normalized and "#" not in normalized
    if portable:
        path = PurePosixPath(normalized)
        portable = not (normalized == "." or path.is_absolute() or ".." in path.parts or path.as_posix() != normalized)
    base = {
        "schema_id": "artifact-memory/resolution-receipt/v1",
        "endpoint_ref": endpoint_ref,
        "relative_path": normalized if portable else "unsupported",
        "authority_boundary": AUTHORITY_BOUNDARY,
    }
    if not portable:
        return {**base, "outcome": "unsupported", "diagnostics": ["relative path is not portable"]}
    matches = [config for config in configs if config.get("endpoint_ref") == endpoint_ref]
    if not matches:
        return {**base, "outcome": "unavailable-endpoint", "diagnostics": ["logical endpoint is unavailable"]}
    if any(not config.get("authorized", False) for config in matches):
        return {**base, "outcome": "not-authorized", "diagnostics": ["local resolver authorization is required"]}
    roots = {str(Path(config["root"]).resolve()) for config in matches}
    if len(roots) > 1:
        return {**base, "outcome": "ambiguous", "diagnostics": ["multiple authorized roots match the endpoint"]}
    resolved = Path(next(iter(roots))) / Path(*path.parts)
    return {**base, "outcome": "resolved", "resolved_path_digest": "sha-256:" + hashlib.sha256(str(resolved).encode("utf-8")).hexdigest(), "diagnostics": []}
