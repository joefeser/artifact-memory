"""Materially separate stdlib-only exchange reader for conformance testing."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any


EXTENSION_ID = re.compile(r"^https://[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~/-]+)?$")
RECORD_ID = re.compile(r"^record://[A-Za-z0-9._~-]+/[A-Za-z0-9._~-]+$")
REVISION_DIGEST = re.compile(r"^sha-256:[0-9a-f]{64}$")
ARTIFACT_REF = re.compile(r"^artifact://[A-Za-z0-9._~/-]+$")
AUTHORITY_BOUNDARY = "knowledge exchange grants no execution, disclosure, routing, spending, credential, deployment, merge, or mutation authority"
DEFAULT_RECORD_SCHEMAS = {
    "artifact-memory/knowledge-record/v1",
    "artifact-memory/knowledge-record/v2",
}
MAX_INTEROPERABLE_INTEGER = 9_007_199_254_740_991
PRIVATE_KEY_HEADER = re.compile(
    r"-----BEGIN (?:[A-Z0-9][A-Z0-9 -]* )?PRIVATE KEY-----", re.IGNORECASE
)
TOKEN_VALUE = re.compile(
    r"(?:gh[opusr]_[A-Za-z0-9_]{20,}|github"
    + r"_pat_[A-Za-z0-9_]{20,}|sk[-_][A-Za-z0-9_-]{20,})"
)
BEARER_VALUE = re.compile(
    r"(?:authorization\s*:\s*)?bearer\s+[A-Za-z0-9._~+/=-]{16,}",
    re.IGNORECASE,
)


class ReaderFailure(Exception):
    pass


def _bundled_record_id_or_invalid(record: Any) -> str:
    candidate = record.get("record_id") if isinstance(record, dict) else None
    if not isinstance(candidate, str) or RECORD_ID.fullmatch(candidate) is None:
        return "record://invalid/bundled-record"
    return candidate


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
    if not isinstance(schema_id, str) or schema_id not in {
        "artifact-memory/knowledge-record/v1",
        "artifact-memory/knowledge-record/v2",
        "artifact-memory/knowledge-record/v3",
    }:
        raise ReaderFailure("unsupported canonical record schema")
    record_id = record.get("record_id")
    if not isinstance(record_id, str) or re.fullmatch(r"record://[A-Za-z0-9._~-]+/[A-Za-z0-9._~-]+", record_id) is None:
        raise ReaderFailure("canonical record identity is invalid")
    record_type = record.get("record_type")
    if not isinstance(record_type, str) or record_type not in {
        "note",
        "decision",
        "claim",
        "question",
        "workstream",
    }:
        raise ReaderFailure("canonical record type is invalid")
    lifecycle = record.get("lifecycle")
    if not isinstance(lifecycle, str) or lifecycle not in {
        "draft",
        "accepted",
        "sealed",
        "superseded",
        "rejected",
    }:
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
            or not isinstance(entry.get("kind"), str)
            or entry["kind"] not in {"author", "observation", "import", "derivation"}
            or not isinstance(entry.get("source_ref"), str)
            or not entry["source_ref"]
        ):
            raise ReaderFailure("canonical record provenance is invalid")
    relationships = record.get("relationships", [])
    if not isinstance(relationships, list):
        raise ReaderFailure("canonical record relationships are invalid")
    allowed_relationship_types = {
        "artifact-memory/knowledge-record/v1": {"related-to", "produced-from", "supported-by-external-evidence"},
        "artifact-memory/knowledge-record/v2": {"related-to", "produced-from", "redacted-from", "supported-by-external-evidence"},
        "artifact-memory/knowledge-record/v3": {"related-to", "produced-from", "redacted-from", "supported-by-external-evidence", "supersedes", "disputes", "contradicts"},
    }[schema_id]
    for relationship in relationships:
        if not isinstance(relationship, dict):
            raise ReaderFailure("canonical record relationship is invalid")
        relationship_type = relationship.get("type")
        evolution_relationship = relationship_type in {"supersedes", "disputes", "contradicts"}
        allowed_relationship_fields = {"type", "target_ref", "target_revision_digest"} if evolution_relationship else {"type", "target_ref"}
        if (
            set(relationship) != allowed_relationship_fields
            or not isinstance(relationship.get("type"), str)
            or relationship_type not in allowed_relationship_types
            or not isinstance(relationship.get("target_ref"), str)
            or not relationship["target_ref"]
        ):
            raise ReaderFailure("canonical record relationship is invalid")
        if evolution_relationship and (
            RECORD_ID.fullmatch(relationship["target_ref"]) is None
            or not isinstance(relationship.get("target_revision_digest"), str)
            or REVISION_DIGEST.fullmatch(relationship["target_revision_digest"]) is None
        ):
            raise ReaderFailure("canonical record evolution relationship is invalid")
    if "derivative" in record:
        derivative = record["derivative"]
        derivative_fields = {"source_task_ref", "transformation_ref", "uncertainty"}
        if not isinstance(derivative, dict) or set(derivative) != derivative_fields or not all(isinstance(derivative[key], str) and derivative[key] for key in derivative_fields):
            raise ReaderFailure("canonical derivative record is invalid")
    if "sensitivity" in record and (
        not isinstance(record["sensitivity"], str)
        or record["sensitivity"] not in {"public", "private", "restricted"}
    ):
        raise ReaderFailure("canonical record sensitivity is invalid")
    if "extensions" in record and not isinstance(record["extensions"], dict):
        raise ReaderFailure("canonical record extensions must be an object")


def _revision_digest(record: dict[str, Any]) -> str:
    """Retain the legacy v1 reader's historical digest profile."""
    canonical = json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha-256:" + hashlib.sha256(canonical).hexdigest()


def _strict_revision_digest(record: dict[str, Any]) -> str:
    return "sha-256:" + hashlib.sha256(_canonical(record)).hexdigest()


def _check_canonical_value(value: Any, ancestors: set[int] | None = None) -> None:
    ancestors = set() if ancestors is None else ancestors
    if value is None or isinstance(value, (bool, str)):
        if isinstance(value, str) and any(
            0xD800 <= ord(character) <= 0xDFFF for character in value
        ):
            raise ValueError("unpaired Unicode surrogate")
        return
    if isinstance(value, int):
        if abs(value) > MAX_INTEROPERABLE_INTEGER:
            raise ValueError("integer outside interoperable range")
        return
    if isinstance(value, float):
        raise ValueError("fractional numbers are unsupported")
    if isinstance(value, (list, dict)):
        identity = id(value)
        if identity in ancestors:
            raise ValueError("cyclic container")
        ancestors.add(identity)
        try:
            if isinstance(value, list):
                for item in value:
                    _check_canonical_value(item, ancestors)
            else:
                for key, item in value.items():
                    if not isinstance(key, str):
                        raise ValueError("object key is not a string")
                    _check_canonical_value(key, ancestors)
                    _check_canonical_value(item, ancestors)
        finally:
            ancestors.remove(identity)
        return
    raise ValueError("non-JSON value")


def _canonical(value: Any) -> bytes:
    """Implement the v0 canonical JSON profile without reference-runtime imports."""
    _check_canonical_value(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _contains_protected_material(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_protected_material(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_protected_material(item) for item in value)
    return isinstance(value, str) and (
        BEARER_VALUE.search(value) is not None
        or PRIVATE_KEY_HEADER.search(value) is not None
        or TOKEN_VALUE.search(value) is not None
    )


def _receipt_v2(
    envelope_ref: str,
    outcome: str,
    *,
    accepted_record_ids: list[str] | None = None,
    unresolved_record_ids: list[str] | None = None,
    artifact_refs: list[str] | None = None,
    diagnostics: list[dict[str, str]] | None = None,
    extensions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = {
        "envelope_ref": envelope_ref,
        "outcome": outcome,
        "accepted_record_ids": sorted(accepted_record_ids or []),
        "unresolved_record_ids": sorted(unresolved_record_ids or []),
        "artifact_refs": sorted(artifact_refs or []),
        "artifact_retrieval": "not-attempted/separately-authorized",
        "diagnostics": diagnostics or [],
        "extensions": extensions or {},
        "authority_boundary": AUTHORITY_BOUNDARY,
    }
    return {
        "schema_id": "artifact-memory/admission-receipt/v2",
        "receipt_id": "admission-receipt://" + hashlib.sha256(_canonical(body)).hexdigest(),
        **body,
    }


def _rejected_v2(envelope_ref: str, code: str, message: str, **kwargs: Any) -> dict[str, Any]:
    """Keep common fail-closed receipt construction uniform."""
    return _receipt_v2(
        envelope_ref,
        "rejected",
        diagnostics=[{"code": code, "message": message}],
        **kwargs,
    )


def _v2_extensions(
    extensions: Any,
    supported_required: set[tuple[str, str]],
) -> dict[str, Any]:
    if not isinstance(extensions, dict):
        raise ReaderFailure("extension declarations are invalid")
    for identifier, declaration in extensions.items():
        if (
            not isinstance(identifier, str)
            or EXTENSION_ID.fullmatch(identifier) is None
            or not isinstance(declaration, dict)
            or set(declaration) != {"version", "required", "value"}
            or not isinstance(declaration.get("version"), str)
            or re.fullmatch(r"v[0-9]+", declaration["version"]) is None
            or not isinstance(declaration.get("required"), bool)
            or not isinstance(declaration.get("value"), dict)
        ):
            raise ReaderFailure("extension declarations are invalid")
        if declaration["required"] and (
            identifier,
            declaration["version"],
        ) not in supported_required:
            raise ReaderFailure("required extension is unsupported")
    return extensions


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
    except (json.JSONDecodeError, ReaderFailure, UnicodeDecodeError) as exc:
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


def admit_bundle_v2(
    envelope_json: bytes,
    *,
    expected_audience_ref: str,
    now: str,
    supported_required_extensions: Iterable[tuple[str, str]] | None = None,
    supported_record_schema_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Independently validate one complete v2 bundle and emit a compatible receipt.

    This intentionally implements only the issue #23 exact-bundle interoperability
    profile. The reference runtime remains responsible for replay, partial local
    resolution, and the wider issue #22 outcome matrix.
    """
    supported = _supported_required_pairs(supported_required_extensions)
    if supported_record_schema_ids is None:
        supported_record_schemas = set(DEFAULT_RECORD_SCHEMAS)
    elif isinstance(supported_record_schema_ids, str):
        supported_record_schema_values = []
    else:
        try:
            supported_record_schema_values = list(supported_record_schema_ids)
        except TypeError:
            supported_record_schema_values = []
    if supported_record_schema_ids is not None:
        if (
            not supported_record_schema_values
            or any(not isinstance(value, str) or not value for value in supported_record_schema_values)
        ):
            raise ReaderFailure("supported record schemas must be non-empty strings")
        supported_record_schemas = set(supported_record_schema_values)
    try:
        envelope = json.loads(envelope_json, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, ReaderFailure, UnicodeDecodeError) as exc:
        raise ReaderFailure("invalid exchange JSON") from exc
    if not isinstance(envelope, dict):
        raise ReaderFailure("exchange envelope must be an object")

    body = {key: value for key, value in envelope.items() if key != "envelope_id"}
    try:
        envelope_ref = "exchange://" + hashlib.sha256(_canonical(body)).hexdigest()
    except (TypeError, UnicodeEncodeError, ValueError):
        return _rejected_v2(
            "exchange://" + "0" * 64,
            "invalid-envelope",
            "exchange envelope is not canonicalizable",
        )

    allowed = {
        "schema_id",
        "envelope_id",
        "audience_ref",
        "correlation_id",
        "expires_at",
        "bundle_manifest",
        "record_bundle",
        "handling",
        "authority_boundary",
        "extensions",
    }
    required = allowed - {"record_bundle", "extensions"}
    if set(envelope) - allowed or required - set(envelope):
        return _rejected_v2(
            envelope_ref,
            "invalid-envelope",
            "exchange envelope does not satisfy the v2 contract",
        )
    if envelope.get("schema_id") != "artifact-memory/exchange-envelope/v2":
        return _rejected_v2(
            envelope_ref,
            "invalid-envelope",
            "exchange envelope does not satisfy the v2 contract",
        )
    if (
        not isinstance(envelope.get("audience_ref"), str)
        or not envelope["audience_ref"]
        or not isinstance(envelope.get("expires_at"), str)
    ):
        return _rejected_v2(
            envelope_ref,
            "invalid-envelope",
            "exchange envelope does not satisfy the v2 contract",
        )
    if envelope.get("envelope_id") != envelope_ref:
        return _rejected_v2(
            envelope_ref,
            "envelope-id-mismatch",
            "exchange envelope identity does not match its canonical body",
        )
    if envelope.get("audience_ref") != expected_audience_ref:
        return _rejected_v2(
            envelope_ref,
            "audience-mismatch",
            "exchange audience does not match this receiver",
        )
    if (
        not isinstance(envelope.get("correlation_id"), str)
        or re.fullmatch(r"[A-Za-z0-9._~-]+", envelope["correlation_id"]) is None
        or envelope.get("authority_boundary") != AUTHORITY_BOUNDARY
    ):
        return _rejected_v2(
            envelope_ref,
            "invalid-envelope",
            "exchange envelope does not satisfy the v2 contract",
        )
    if _contains_protected_material(envelope):
        return _rejected_v2(
            envelope_ref,
            "bearer-material-prohibited",
            "exchange envelope contains prohibited bearer material",
        )

    handling = envelope.get("handling")
    handling_fields = {"sensitivity", "disclosure", "artifact_retrieval"}
    if (
        not isinstance(handling, dict)
        or set(handling) != handling_fields
        or not isinstance(handling.get("sensitivity"), str)
        or handling["sensitivity"] not in {"public", "private", "restricted"}
        or not isinstance(handling.get("disclosure"), str)
        or handling["disclosure"]
        not in {"informational-only", "receiver-policy-required"}
        or handling.get("artifact_retrieval") != "separately-authorized"
    ):
        return _rejected_v2(
            envelope_ref,
            "invalid-envelope",
            "exchange envelope does not satisfy the v2 contract",
        )

    try:
        preserved_extensions = _v2_extensions(
            envelope.get("extensions", {}), supported
        )
    except ReaderFailure as exc:
        code = (
            "required-extension-unsupported"
            if str(exc) == "required extension is unsupported"
            else "invalid-extension"
        )
        return _receipt_v2(
            envelope_ref,
            "quarantined",
            diagnostics=[{"code": code, "message": str(exc)}],
        )

    try:
        expiry = datetime.fromisoformat(envelope["expires_at"].replace("Z", "+00:00"))
        current = datetime.fromisoformat(now.replace("Z", "+00:00"))
        if expiry.tzinfo is None or current.tzinfo is None:
            raise ValueError("timezone required")
        if expiry <= current.astimezone(timezone.utc):
            return _rejected_v2(
                envelope_ref,
                "expired",
                "exchange envelope is expired",
                extensions=preserved_extensions,
            )
    except (AttributeError, TypeError, ValueError):
        return _rejected_v2(
            envelope_ref,
            "invalid-expiry",
            "exchange expiry is invalid",
            extensions=preserved_extensions,
        )

    manifest = envelope.get("bundle_manifest")
    if not isinstance(manifest, dict) or set(manifest) != {
        "bundle_id",
        "records",
        "artifact_refs",
    }:
        return _rejected_v2(
            envelope_ref,
            "invalid-envelope",
            "exchange envelope does not satisfy the v2 contract",
        )
    record_refs = manifest.get("records")
    artifact_refs = manifest.get("artifact_refs")
    if (
        not isinstance(record_refs, list)
        or not isinstance(artifact_refs, list)
        or not all(isinstance(item, str) and ARTIFACT_REF.fullmatch(item) for item in artifact_refs)
    ):
        return _rejected_v2(
            envelope_ref,
            "invalid-envelope",
            "exchange envelope does not satisfy the v2 contract",
        )
    manifest_body = {"records": record_refs, "artifact_refs": artifact_refs}
    expected_bundle_id = "exchange-bundle://" + hashlib.sha256(
        _canonical(manifest_body)
    ).hexdigest()
    if manifest.get("bundle_id") != expected_bundle_id:
        return _rejected_v2(
            envelope_ref,
            "bundle-id-mismatch",
            "bundle manifest identity does not match its canonical body",
        )

    declared: dict[str, str] = {}
    contradictory: set[str] = set()
    for item in record_refs:
        if (
            not isinstance(item, dict)
            or set(item) != {"record_id", "revision_digest"}
            or not isinstance(item.get("record_id"), str)
            or RECORD_ID.fullmatch(item["record_id"]) is None
            or not isinstance(item.get("revision_digest"), str)
            or REVISION_DIGEST.fullmatch(item["revision_digest"]) is None
        ):
            return _rejected_v2(
                envelope_ref,
                "invalid-envelope",
                "exchange envelope does not satisfy the v2 contract",
            )
        prior = declared.get(item["record_id"])
        if prior is not None and prior != item["revision_digest"]:
            contradictory.add(item["record_id"])
        elif prior is None:
            declared[item["record_id"]] = item["revision_digest"]

    record_bundle = envelope.get("record_bundle", [])
    if not isinstance(record_bundle, list):
        return _rejected_v2(
            envelope_ref,
            "invalid-envelope",
            "exchange envelope does not satisfy the v2 contract",
        )
    if not all(isinstance(record, dict) for record in record_bundle):
        return _rejected_v2(
            envelope_ref,
            "invalid-envelope",
            "exchange envelope does not satisfy the v2 contract",
        )
    bundled: set[str] = set()
    invalid_bundle_ids: set[str] = set()
    invalid_bundle_codes: set[str] = set()
    handling_conflict = False
    sensitivity_rank = {"public": 0, "private": 1, "restricted": 2}
    for record in record_bundle:
        extensions = record.get("extensions", {})
        try:
            _validate_record(record)
            if record["schema_id"] not in supported_record_schemas:
                raise ReaderFailure("bundled record schema was not negotiated")
            if not isinstance(extensions, dict):
                raise ReaderFailure("record extensions must be an object")
            if any(
                isinstance(declaration, dict)
                and declaration.get("required") is True
                for declaration in extensions.values()
            ):
                _v2_extensions(extensions, supported)
            else:
                _preserve_record_extensions(extensions, supported)
            revision = _strict_revision_digest(record)
        except ReaderFailure as exc:
            if str(exc) == "required extension is unsupported":
                failure_code = "required-extension-unsupported"
            elif str(exc) == "bundled record schema was not negotiated":
                failure_code = "unsupported-record"
            elif str(exc) == "unsupported canonical record schema":
                failure_code = "unsupported-record"
            elif (
                record.get("schema_id") == "artifact-memory/knowledge-record/v1"
                and isinstance(extensions, dict)
                and any(
                    isinstance(declaration, dict)
                    and declaration.get("required") is True
                    and not {"version", "required", "value"}.issubset(declaration)
                    for declaration in extensions.values()
                )
            ):
                failure_code = "required-field-missing"
            else:
                failure_code = "invalid-record"
            candidate_id = _bundled_record_id_or_invalid(record)
            invalid_bundle_ids.add(candidate_id)
            invalid_bundle_codes.add(failure_code)
            contradictory.add(candidate_id)
            continue
        except (TypeError, UnicodeEncodeError, ValueError):
            candidate_id = _bundled_record_id_or_invalid(record)
            invalid_bundle_ids.add(candidate_id)
            invalid_bundle_codes.add("invalid-record")
            contradictory.add(candidate_id)
            continue
        record_id = record["record_id"]
        sensitivity = record.get("sensitivity", "restricted")
        if (
            record_id in bundled
            or declared.get(record_id) != revision
        ):
            contradictory.add(record_id)
            continue
        if sensitivity_rank[sensitivity] > sensitivity_rank[handling["sensitivity"]]:
            handling_conflict = True
            continue
        bundled.add(record_id)

    if contradictory or handling_conflict:
        if invalid_bundle_ids:
            diagnostic = {
                "code": "bundled-record-invalid",
                "message": "bundled record validation failed ("
                + ",".join(sorted(invalid_bundle_codes))
                + ")",
            }
        elif contradictory:
            diagnostic = {
                "code": "contradictory-bundle",
                "message": "bundle declarations or bytes contradict each other",
            }
        else:
            diagnostic = {
                "code": "handling-sensitivity-mismatch",
                "message": "bundle handling is weaker than a record sensitivity",
            }
        return _receipt_v2(
            envelope_ref,
            "quarantined",
            unresolved_record_ids=sorted(
                set(declared) | invalid_bundle_ids | contradictory
            ),
            artifact_refs=artifact_refs,
            diagnostics=[diagnostic],
            extensions=preserved_extensions,
        )

    unresolved = sorted(set(declared) - bundled)
    accepted = sorted(bundled)
    if unresolved:
        outcome = "quarantined"
        accepted = []
        unresolved = sorted(declared)
        diagnostics = [
            {
                "code": "incomplete-bundle",
                "message": "the independent receiver requires a complete embedded bundle",
            }
        ]
    elif accepted or artifact_refs:
        outcome = "admitted"
        diagnostics = []
    else:
        outcome = "quarantined"
        diagnostics = [
            {
                "code": "empty-bundle",
                "message": "bundle contains no knowledge or artifact references",
            }
        ]
    return _receipt_v2(
        envelope_ref,
        outcome,
        accepted_record_ids=accepted,
        unresolved_record_ids=unresolved,
        artifact_refs=artifact_refs,
        diagnostics=diagnostics,
        extensions=preserved_extensions,
    )
