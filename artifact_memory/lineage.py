"""Read-only observations for WhereAreMyFiles historical evidence."""

from __future__ import annotations

import re
from typing import Any

from .schema_resources import load_schema
from .validator import ValidationFailure, validate


SOURCE_REF = "https://github.com/joefeser/WhereAreMyFiles"
_SHA1 = re.compile(r"^[0-9a-fA-F]{40}$")


def _require_row(row: dict[str, Any], field: str, expected: type) -> Any:
    value = row.get(field)
    if not isinstance(value, expected) or isinstance(value, bool):
        raise ValidationFailure("legacy-evidence-insufficient", f"legacy {field} is missing or malformed", f"$.{field}")
    if expected is str and not value:
        raise ValidationFailure("legacy-evidence-insufficient", f"legacy {field} is empty", f"$.{field}")
    return value


def observe_legacy_file(row: dict[str, Any], source_ref: str) -> dict[str, Any]:
    """Preserve legacy evidence without upgrading identity or mutating source."""
    if source_ref != SOURCE_REF:
        raise ValidationFailure("legacy-source-unsupported", "legacy observations require the attributed WhereAreMyFiles source", "$.source_ref")

    path = _require_row(row, "path", str)
    size = _require_row(row, "size", int)
    created = _require_row(row, "created", str)
    modified = _require_row(row, "modified", str)
    legacy_hash = _require_row(row, "sha1", str)
    if size < 0:
        raise ValidationFailure("legacy-evidence-insufficient", "legacy size cannot be negative", "$.size")
    if legacy_hash == "NONE":
        hash_state = "none-recorded"
    elif _SHA1.fullmatch(legacy_hash):
        hash_state = "sha-1-observed-not-upgraded"
    else:
        raise ValidationFailure("legacy-evidence-insufficient", "legacy sha1 must be a 40-hex digest or the exact NONE sentinel", "$.sha1")

    observation = {
        "schema_id": "artifact-memory/legacy-observation/v1",
        "source_ref": source_ref,
        "read_only": True,
        "historical_fields": {
            "path_observed": path,
            "byte_size_observed": size,
            "created_time_observed": created,
            "modified_time_observed": modified,
            "legacy_hash": {"algorithm": "sha-1", "state": hash_state, "value": legacy_hash},
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
    validate(observation, load_schema("core", "legacy-observation.v1.schema.json"))
    return observation
