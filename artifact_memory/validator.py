"""Small fail-closed JSON Schema validator for the v0 contract subset."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


class ValidationFailure(Exception):
    """Raised for malformed JSON or unsupported schema input."""

    def __init__(self, code: str, message: str, path: str = "$") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationFailure("duplicate-key", f"duplicate object key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except ValidationFailure:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationFailure("invalid-json", "input is not valid UTF-8 JSON") from exc


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _fail(code: str, message: str, path: str) -> None:
    raise ValidationFailure(code, message, path)


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    supported = {"$schema", "$id", "title", "type", "additionalProperties", "required", "properties", "const", "enum", "pattern", "minLength", "minItems", "minimum", "format", "items"}
    unknown = set(schema) - supported
    if unknown:
        _fail("unsupported-schema-keyword", "unsupported schema keyword", path)
    if "const" in schema and value != schema["const"]:
        _fail("constraint-failed", "value does not match const", path)
    if "enum" in schema and value not in schema["enum"]:
        _fail("constraint-failed", "value is not in enum", path)
    expected = schema.get("type")
    if expected and _kind(value) != expected and not (expected == "number" and _kind(value) == "integer"):
        _fail("type-mismatch", f"expected {expected}", path)
    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                _fail("required-field-missing", f"required field is missing: {key}", path)
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unknown_fields = set(value) - set(properties)
            if unknown_fields:
                _fail("unknown-field", "unknown field is not allowed", f"{path}.{sorted(unknown_fields)[0]}")
        for key, child_schema in properties.items():
            if key in value:
                validate(value[key], child_schema, f"{path}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            _fail("constraint-failed", "array has too few items", path)
        if "items" in schema:
            for index, item in enumerate(value):
                validate(item, schema["items"], f"{path}[{index}]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            _fail("constraint-failed", "string is too short", path)
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            _fail("constraint-failed", "string does not match pattern", path)
        if schema.get("format") == "date-time":
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                _fail("constraint-failed", "invalid date-time", path)
    if isinstance(value, (int, float)) and value < schema.get("minimum", value):
        _fail("constraint-failed", "number is below minimum", path)


def validate_file(record_path: Path, schema_path: Path) -> dict[str, Any]:
    try:
        record = load_json(record_path)
        schema = load_json(schema_path)
        if not isinstance(schema, dict) or not isinstance(record, dict):
            raise ValidationFailure("invalid-input", "record and schema must be JSON objects")
        validate(record, schema)
    except ValidationFailure as exc:
        return {"valid": False, "outcome": "rejected", "diagnostics": [{"code": exc.code, "path": exc.path, "message": exc.message}]}
    return {"valid": True, "outcome": "accepted", "diagnostics": []}
