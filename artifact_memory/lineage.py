"""Read-only observations for WhereAreMyFiles historical evidence."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .schema_resources import load_schema
from .validator import ValidationFailure, validate


SOURCE_REF = "https://github.com/joefeser/WhereAreMyFiles"
_SHA1 = re.compile(r"^[0-9a-fA-F]{40}$")
_LEGACY_OBSERVATION_SCHEMAS = {
    "v1": load_schema("core", "legacy-observation.v1.schema.json"),
    "v2": load_schema("core", "legacy-observation.v2.schema.json"),
}


def _require_qualified_timestamp(value: str, field: str) -> None:
    """Require an ISO-8601 timestamp with an explicit UTC offset."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationFailure(
            "legacy-evidence-insufficient",
            f"legacy {field} must be a timezone-qualified ISO-8601 timestamp",
            f"$.historical_fields.{field}",
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationFailure(
            "legacy-evidence-insufficient",
            f"legacy {field} must be a timezone-qualified ISO-8601 timestamp",
            f"$.historical_fields.{field}",
        )


def validate_legacy_observation(observation: dict[str, Any]) -> dict[str, Any]:
    """Validate retained v1 read evidence or strict v2 observations by schema ID."""
    if not isinstance(observation, dict):
        raise ValidationFailure("legacy-observation-invalid", "legacy observation must be an object")
    schema_id = observation.get("schema_id")
    schema_version = {
        "artifact-memory/legacy-observation/v1": "v1",
        "artifact-memory/legacy-observation/v2": "v2",
    }.get(schema_id)
    if schema_version is None:
        raise ValidationFailure("legacy-schema-unsupported", "legacy observation schema version is unsupported")
    validate(observation, _LEGACY_OBSERVATION_SCHEMAS[schema_version])
    if schema_version == "v2":
        historical_fields = observation["historical_fields"]
        _require_qualified_timestamp(historical_fields["created_time_observed"], "created_time_observed")
        _require_qualified_timestamp(historical_fields["modified_time_observed"], "modified_time_observed")
    return observation


def _require_row(row: dict[str, Any], field: str, expected: type) -> Any:
    value = row.get(field)
    if not isinstance(value, expected) or isinstance(value, bool):
        raise ValidationFailure("legacy-evidence-insufficient", f"legacy {field} is missing or malformed", f"$.{field}")
    if expected is str and not value:
        raise ValidationFailure("legacy-evidence-insufficient", f"legacy {field} is empty", f"$.{field}")
    return value


def observe_legacy_file(
    row: dict[str, Any],
    source_ref: str,
    *,
    schema_version: str = "v1",
) -> dict[str, Any]:
    """Preserve legacy evidence without upgrading identity or mutating source."""
    if not isinstance(schema_version, str) or schema_version not in _LEGACY_OBSERVATION_SCHEMAS:
        raise ValidationFailure("legacy-schema-unsupported", "legacy observation schema version is unsupported")
    if not isinstance(row, dict):
        raise ValidationFailure("legacy-evidence-insufficient", "legacy row must be an object")
    if source_ref != SOURCE_REF:
        raise ValidationFailure("legacy-source-unsupported", "legacy observations require the attributed WhereAreMyFiles source", "$.source_ref")

    path = _require_row(row, "path", str)
    size = _require_row(row, "size", int)
    created = _require_row(row, "created", str)
    modified = _require_row(row, "modified", str)
    legacy_hash = _require_row(row, "sha1", str)
    if schema_version == "v2":
        _require_qualified_timestamp(created, "created_time_observed")
        _require_qualified_timestamp(modified, "modified_time_observed")
    if size < 0:
        raise ValidationFailure("legacy-evidence-insufficient", "legacy size cannot be negative", "$.size")
    if legacy_hash == "NONE":
        hash_state = "none-recorded"
    elif _SHA1.fullmatch(legacy_hash):
        hash_state = "sha-1-observed-not-upgraded"
    else:
        raise ValidationFailure("legacy-evidence-insufficient", "legacy sha1 must be a 40-hex digest or the exact NONE sentinel", "$.sha1")

    observation = {
        "schema_id": f"artifact-memory/legacy-observation/{schema_version}",
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
    return validate_legacy_observation(observation)
