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


def load_json_bytes(data: bytes) -> Any:
    def reject_non_finite(token: str) -> None:
        raise ValidationFailure("invalid-json", f"non-finite JSON number is not allowed: {token}")

    try:
        text = data.decode("utf-8")
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=reject_non_finite,
        )
    except ValidationFailure:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationFailure("invalid-json", "input is not valid UTF-8 JSON") from exc


def load_json(path: Path) -> Any:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValidationFailure("invalid-json", "input is not valid UTF-8 JSON") from exc
    return load_json_bytes(data)


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
    if isinstance(value, dict):
        return "object"
    return "non-json"


def _fail(code: str, message: str, path: str) -> None:
    raise ValidationFailure(code, message, path)


def _json_equal(left: Any, right: Any) -> bool:
    """Compare JSON values without Python's bool/int equality coercion."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_json_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_json_equal(left[key], right[key]) for key in left)
    return type(left) is type(right) and left == right


def _matches(value: Any, schema: dict[str, Any], path: str) -> bool:
    try:
        validate(value, schema, path)
    except ValidationFailure as exc:
        if exc.code == "unsupported-schema-keyword":
            raise
        return False
    return True


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    supported = {"$schema", "$id", "title", "type", "additionalProperties", "propertyNames", "required", "dependentRequired", "properties", "const", "enum", "pattern", "minLength", "minItems", "maxItems", "minimum", "format", "items", "allOf", "anyOf", "not", "if", "then", "else"}
    unknown = set(schema) - supported
    if unknown:
        _fail("unsupported-schema-keyword", "unsupported schema keyword", path)
    for child_schema in schema.get("allOf", []):
        validate(value, child_schema, path)
    if "anyOf" in schema and not any(_matches(value, child_schema, path) for child_schema in schema["anyOf"]):
        _fail("constraint-failed", "value does not match any allowed schema", path)
    if "not" in schema and _matches(value, schema["not"], path):
        _fail("constraint-failed", "value matches a forbidden schema", path)
    if "if" in schema:
        branch = "then" if _matches(value, schema["if"], path) else "else"
        if branch in schema:
            validate(value, schema[branch], path)
    if "const" in schema and not _json_equal(value, schema["const"]):
        _fail("constraint-failed", "value does not match const", path)
    if "enum" in schema and not any(_json_equal(value, candidate) for candidate in schema["enum"]):
        _fail("constraint-failed", "value is not in enum", path)
    expected = schema.get("type")
    if expected and _kind(value) != expected and not (expected == "number" and _kind(value) == "integer"):
        _fail("type-mismatch", f"expected {expected}", path)
    if isinstance(value, dict):
        if "propertyNames" in schema:
            for key in sorted(value):
                validate(key, schema["propertyNames"], f"{path}[{key!r}]")
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                _fail("required-field-missing", f"required field is missing: {key}", path)
        for key, dependencies in schema.get("dependentRequired", {}).items():
            if key in value:
                for dependency in dependencies:
                    if dependency not in value:
                        _fail("required-field-missing", f"field {dependency} is required with {key}", path)
        properties = schema.get("properties", {})
        unknown_fields = set(value) - set(properties)
        additional = schema.get("additionalProperties")
        if additional is False:
            if unknown_fields:
                _fail("unknown-field", "unknown field is not allowed", f"{path}.{sorted(unknown_fields)[0]}")
        elif isinstance(additional, dict):
            for key in sorted(unknown_fields):
                validate(value[key], additional, f"{path}.{key}")
        for key, child_schema in properties.items():
            if key in value:
                validate(value[key], child_schema, f"{path}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            _fail("constraint-failed", "array has too few items", path)
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            _fail("constraint-failed", "array has too many items", path)
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
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                _fail("constraint-failed", "invalid date-time", path)
            if parsed.utcoffset() is None:
                _fail("constraint-failed", "date-time requires a timezone offset", path)
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
