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
    if envelope.get("schema_id") != "artifact-memory/exchange-envelope/v1":
        raise ReaderFailure("unsupported exchange schema")
    accepted = []
    for record in envelope.get("record_bundle", []):
        if not isinstance(record, dict) or record.get("schema_id") != "artifact-memory/knowledge-record/v1":
            raise ReaderFailure("unsupported canonical record schema")
        extensions = record.get("extensions", {})
        for identifier, declaration in extensions.items():
            if declaration.get("required") and identifier not in supported_required_extensions:
                raise ReaderFailure("required extension unsupported")
        accepted.append({"record_id": record["record_id"], "extensions": extensions})
    return {"outcome": "accepted", "record_ids": [item["record_id"] for item in accepted], "preserved_extensions": [item["extensions"] for item in accepted], "artifact_refs": list(envelope.get("artifact_refs", [])), "artifact_retrieval": "separately-authorized"}
