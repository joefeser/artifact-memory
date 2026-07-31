"""Access the single canonical schema tree from source and installed packages."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from .validator import ValidationFailure


def load_schema(category: str, name: str) -> dict[str, Any]:
    resource = files("artifact_memory.schemas").joinpath(category, name)
    try:
        value = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationFailure("invalid-schema", "packaged schema is unavailable or invalid") from exc
    if not isinstance(value, dict):
        raise ValidationFailure("invalid-schema", "packaged schema must be an object")
    return value


def load_contract_text(category: str, name: str) -> str:
    resource = files("artifact_memory.schemas").joinpath(category, name)
    try:
        value = resource.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValidationFailure("invalid-schema", "packaged contract resource is unavailable or invalid") from exc
    if not value.strip():
        raise ValidationFailure("invalid-schema", "packaged contract resource is empty")
    return value


def core_schemas() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    root = files("artifact_memory.schemas").joinpath("core")
    for resource in sorted(root.iterdir(), key=lambda item: item.name):
        if not resource.name.endswith(".schema.json"):
            continue
        try:
            schema = json.loads(resource.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValidationFailure("invalid-schema", "packaged schema is unavailable or invalid") from exc
        if not isinstance(schema, dict) or not isinstance(schema.get("properties"), dict):
            raise ValidationFailure("invalid-schema", f"packaged core schema is structurally invalid: {resource.name}")
        schema_id_property = schema["properties"].get("schema_id")
        if not isinstance(schema_id_property, dict) or not isinstance(schema_id_property.get("const"), str):
            raise ValidationFailure("invalid-schema", f"packaged core schema has no constant schema_id: {resource.name}")
        result[schema_id_property["const"]] = schema
    return result
