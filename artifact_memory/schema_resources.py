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
            continue
        schema_id = schema["properties"].get("schema_id", {}).get("const")
        if isinstance(schema_id, str):
            result[schema_id] = schema
    return result
