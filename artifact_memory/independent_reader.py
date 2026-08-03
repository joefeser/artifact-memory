"""Materially separate stdlib-only exchange reader for conformance testing."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from typing import Any


EXTENSION_ID = re.compile(r"^https://[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~/-]+)?$")


class ReaderFailure(Exception):
    pass


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReaderFailure("duplicate object key")
        result[key] = value
    return result


def _validate_record(record: dict[str, Any]) -> None:
    allowed = {"schema_id", "record_id", "record_type", "lifecycle", "meaning", "artifact_refs", "provenance", "relationships", "derivative", "sensitivity", "extensions"}
    required = {"schema_id", "record_id", "record_type", "lifecycle", "meaning", "artifact_refs", "provenance"}
    if set(record) - allowed or required - set(record):
        raise ReaderFailure("canonical record fields are invalid")
    schema_id = record.get("schema_id")
    if schema_id not in {"artifact-memory/knowledge-record/v1", "artifact-memory/knowledge-record/v2"}:
        raise ReaderFailure("unsupported canonical record schema")
    record_id = record.get("record_id")
    if not isinstance(record_id, str) or re.fullmatch(r"record://[A-Za-z0-9._~-]+/[A-Za-z0-9._~-]+", record_id) is None:
        raise ReaderFailure("canonical record identity is invalid")
    if record.get("record_type") not in {"note", "decision", "claim", "question", "workstream"}:
        raise ReaderFailure("canonical record type is invalid")
    if record.get("lifecycle") not in {"draft", "accepted", "sealed", "superseded", "rejected"}:
        raise ReaderFailure("canonical record lifecycle is invalid")
    meaning = record.get("meaning")
    if not isinstance(meaning, dict) or set(meaning) - {"summary", "labels"} or not isinstance(meaning.get("summary"), str) or not meaning["summary"]:
        raise ReaderFailure("canonical record meaning is invalid")
    if "labels" in meaning and (not isinstance(meaning["labels"], list) or not all(isinstance(item, str) for item in meaning["labels"])):
        raise ReaderFailure("canonical record labels are invalid")
    artifact_refs = record.get("artifact_refs")
    if not isinstance(artifact_refs, list) or not all(isinstance(item, str) and re.fullmatch(r"artifact://[A-Za-z0-9._~/-]+", item) for item in artifact_refs):
        raise ReaderFailure("canonical artifact references are invalid")
    provenance = record.get("provenance")
    if not isinstance(provenance, list) or not provenance:
        raise ReaderFailure("canonical record provenance is required")
    for entry in provenance:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"kind", "source_ref"}
            or entry.get("kind") not in {"author", "observation", "import", "derivation"}
            or not isinstance(entry.get("source_ref"), str)
            or not entry["source_ref"]
        ):
            raise ReaderFailure("canonical record provenance is invalid")
    relationships = record.get("relationships", [])
    if not isinstance(relationships, list):
        raise ReaderFailure("canonical record relationships are invalid")
    for relationship in relationships:
        if (
            not isinstance(relationship, dict)
            or set(relationship) != {"type", "target_ref"}
            or relationship.get("type") not in (
                {"related-to", "produced-from", "supported-by-external-evidence"}
                if schema_id == "artifact-memory/knowledge-record/v1"
                else {"related-to", "produced-from", "redacted-from", "supported-by-external-evidence"}
            )
            or not isinstance(relationship.get("target_ref"), str)
            or not relationship["target_ref"]
        ):
            raise ReaderFailure("canonical record relationship is invalid")
    if "derivative" in record:
        derivative = record["derivative"]
        derivative_fields = {"source_task_ref", "transformation_ref", "uncertainty"}
        if not isinstance(derivative, dict) or set(derivative) != derivative_fields or not all(isinstance(derivative[key], str) and derivative[key] for key in derivative_fields):
            raise ReaderFailure("canonical derivative record is invalid")
    if "sensitivity" in record and record["sensitivity"] not in {"public", "private", "restricted"}:
        raise ReaderFailure("canonical record sensitivity is invalid")


def _revision_digest(record: dict[str, Any]) -> str:
    canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha-256:" + hashlib.sha256(canonical).hexdigest()


def _supported_required_pairs(value: Iterable[tuple[str, str]] | None) -> set[tuple[str, str]]:
    """Validate independently; sharing the reference helper would invalidate this reader's conformance role."""
    if value is None:
        return set()
    if isinstance(value, (str, bytes, dict)):
        raise ReaderFailure("supported required extensions are invalid")
    try:
        entries = list(value)
    except TypeError as exc:
        raise ReaderFailure("supported required extensions are invalid") from exc
    for entry in entries:
        if (
            not isinstance(entry, tuple)
            or len(entry) != 2
            or not all(isinstance(part, str) for part in entry)
            or EXTENSION_ID.fullmatch(entry[0]) is None
            or re.fullmatch(r"v[0-9]+", entry[1]) is None
        ):
            raise ReaderFailure("supported required extensions are invalid")
    return set(entries)


def _preserve_record_extensions(extensions: dict[str, Any], supported_required: set[tuple[str, str]]) -> dict[str, Any]:
    """Preserve v1 opaque values; interpret only complete v0 declarations."""
    preserved: dict[str, Any] = {}
    declaration_fields = {"version", "required", "value"}
    for identifier, value in extensions.items():
        is_declaration = (
            isinstance(value, dict)
            and set(value) == declaration_fields
            and isinstance(value.get("version"), str)
            and re.fullmatch(r"v[0-9]+", value["version"]) is not None
            and isinstance(value.get("required"), bool)
            and isinstance(value.get("value"), dict)
            and EXTENSION_ID.fullmatch(identifier) is not None
        )
        if is_declaration and value["required"] and (identifier, value["version"]) not in supported_required:
            raise ReaderFailure("required extension is unsupported")
        preserved[identifier] = value
    return preserved


def read_bundle(envelope_json: bytes, supported_required_extensions: Iterable[tuple[str, str]] | None = None) -> dict[str, Any]:
    supported_required_extensions = _supported_required_pairs(supported_required_extensions)
    try:
        envelope = json.loads(envelope_json, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, ReaderFailure) as exc:
        raise ReaderFailure("invalid exchange JSON") from exc
    if not isinstance(envelope, dict):
        raise ReaderFailure("exchange envelope must be an object")
    if envelope.get("schema_id") != "artifact-memory/exchange-envelope/v1":
        raise ReaderFailure("unsupported exchange schema")
    bundle_present = "record_bundle" in envelope
    record_bundle = envelope.get("record_bundle", [])
    record_refs = envelope.get("record_refs", [])
    artifact_refs = envelope.get("artifact_refs", [])
    if not isinstance(record_bundle, list) or not isinstance(record_refs, list) or not isinstance(artifact_refs, list) or not all(isinstance(item, str) for item in artifact_refs):
        raise ReaderFailure("exchange bundle fields have invalid shapes")
    declared_revisions: dict[str, str] = {}
    for item in record_refs:
        if (
            not isinstance(item, dict)
            or set(item) != {"record_id", "revision_digest"}
            or not isinstance(item.get("record_id"), str)
            or re.fullmatch(r"record://[A-Za-z0-9._~-]+/[A-Za-z0-9._~-]+", item["record_id"]) is None
            or not isinstance(item.get("revision_digest"), str)
            or re.fullmatch(r"sha-256:[0-9a-f]{64}", item["revision_digest"]) is None
            or item["record_id"] in declared_revisions
        ):
            raise ReaderFailure("record references are invalid")
        declared_revisions[item["record_id"]] = item["revision_digest"]
    accepted = []
    bundled_ids: set[str] = set()
    for record in record_bundle:
        if not isinstance(record, dict):
            raise ReaderFailure("canonical record must be an object")
        _validate_record(record)
        record_id = record["record_id"]
        if record_id in bundled_ids or record_id not in declared_revisions:
            raise ReaderFailure("record bundle does not match declared record references")
        if _revision_digest(record) != declared_revisions[record_id]:
            raise ReaderFailure("record revision digest does not match bundled record")
        bundled_ids.add(record_id)
        extensions = record.get("extensions", {})
        if not isinstance(extensions, dict):
            raise ReaderFailure("record extensions must be an object")
        preserved = _preserve_record_extensions(extensions, supported_required_extensions)
        accepted.append({"record_id": record["record_id"], "extensions": preserved})
    if bundle_present and bundled_ids != set(declared_revisions):
        raise ReaderFailure("record bundle does not match declared record references")
    return {"outcome": "accepted", "record_ids": [item["record_id"] for item in accepted], "preserved_extensions": [item["extensions"] for item in accepted], "artifact_refs": list(artifact_refs), "artifact_retrieval": "separately-authorized"}
