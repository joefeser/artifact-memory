"""Read-only observations for synthetic historical lineage records."""

from __future__ import annotations

from typing import Any


def observe_legacy_file(row: dict[str, Any], source_ref: str) -> dict[str, Any]:
    """Preserve legacy evidence without upgrading identity or mutating source."""
    legacy_hash = row.get("sha1")
    if not isinstance(legacy_hash, str) or legacy_hash.upper() == "NONE":
        hash_state = "none-recorded"
        hash_value = legacy_hash if isinstance(legacy_hash, str) else "NONE"
    else:
        hash_state = "sha-1-observed-not-upgraded"
        hash_value = legacy_hash
    return {
        "schema_id": "artifact-memory/legacy-observation/v1",
        "source_ref": source_ref,
        "read_only": True,
        "historical_fields": {
            "path_observed": row.get("path"),
            "byte_size_observed": row.get("size"),
            "created_time_observed": row.get("created"),
            "modified_time_observed": row.get("modified"),
            "legacy_hash": {"algorithm": "sha-1", "state": hash_state, "value": hash_value},
        },
        "artifact_identity": "not-established",
        "content_identity": "not-established",
        "mutation": "none",
        "limitations": [
            "historical evidence is not a current filesystem observation",
            "SHA-1 is preserved as historical evidence and never upgraded to SHA-256",
            "legacy NONE values remain not-recorded",
        ],
    }
