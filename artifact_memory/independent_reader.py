"""Materially separate stdlib-only exchange reader for conformance testing."""

from __future__ import annotations

import json
from typing import Any


class ReaderFailure(Exception):
    pass


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReaderFailure("duplicate object key")
        result[key] = value
    return result


def read_bundle(envelope_json: bytes, supported_required_extensions: set[str] | None = None) -> dict[str, Any]:
    supported_required_extensions = supported_required_extensions or set()
    try:
        envelope = json.loads(envelope_json, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, ReaderFailure) as exc:
        raise ReaderFailure("invalid exchange JSON") from exc
    if not isinstance(envelope, dict):
        raise ReaderFailure("exchange envelope must be an object")
    if envelope.get("schema_id") != "artifact-memory/exchange-envelope/v1":
        raise ReaderFailure("unsupported exchange schema")
    record_bundle = envelope.get("record_bundle", [])
    artifact_refs = envelope.get("artifact_refs", [])
    if not isinstance(record_bundle, list) or not isinstance(artifact_refs, list) or not all(isinstance(item, str) for item in artifact_refs):
        raise ReaderFailure("exchange bundle fields have invalid shapes")
    accepted = []
    for record in record_bundle:
        if not isinstance(record, dict) or record.get("schema_id") != "artifact-memory/knowledge-record/v1":
            raise ReaderFailure("unsupported canonical record schema")
        if not isinstance(record.get("record_id"), str):
            raise ReaderFailure("canonical record identity is required")
        extensions = record.get("extensions", {})
        if not isinstance(extensions, dict):
            raise ReaderFailure("record extensions must be an object")
        for identifier, declaration in extensions.items():
            if not isinstance(identifier, str) or not isinstance(declaration, dict):
                raise ReaderFailure("extension declaration must be an object")
            if declaration.get("required") and identifier not in supported_required_extensions:
                raise ReaderFailure("required extension unsupported")
        accepted.append({"record_id": record["record_id"], "extensions": extensions})
    return {"outcome": "accepted", "record_ids": [item["record_id"] for item in accepted], "preserved_extensions": [item["extensions"] for item in accepted], "artifact_refs": list(artifact_refs), "artifact_retrieval": "separately-authorized"}
