"""Shared canonical knowledge-record schema dispatch."""

from __future__ import annotations

from typing import Any

from .schema_resources import load_schema
from .validator import ValidationFailure


KNOWLEDGE_SCHEMA_FILES = {
    "artifact-memory/knowledge-record/v1": "knowledge-record.v1.schema.json",
    "artifact-memory/knowledge-record/v2": "knowledge-record.v2.schema.json",
    "artifact-memory/knowledge-record/v3": "knowledge-record.v3.schema.json",
}


def knowledge_schema(record: Any) -> dict[str, Any]:
    """Load the schema selected by a canonical record's explicit identifier."""
    if not isinstance(record, dict):
        raise ValidationFailure("invalid-input", "canonical record must be a JSON object")
    schema_name = KNOWLEDGE_SCHEMA_FILES.get(record.get("schema_id"))
    if schema_name is None:
        raise ValidationFailure("unsupported-record-schema", "canonical record uses an unsupported schema")
    return load_schema("core", schema_name)
