"""Portable candidate admission and immutable knowledge-record evolution."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any

from .canonical import canonical_bytes, receipt_with_digest, sha256_bytes
from .knowledge import knowledge_schema
from .schema_resources import load_schema
from .validator import ValidationFailure, validate


AUTHORITY_BOUNDARY = (
    "candidate admission grants no execution, disclosure, routing, mutation, merge, "
    "deployment, spending, credential, declassification, or approval authority"
)
RECORD_RELATIONSHIPS = {"supersedes", "disputes", "contradicts"}
OUTCOMES = {"accepted", "rejected", "quarantined", "duplicate", "stale", "unsupported", "conflict"}


def _record_digest(record: dict[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(record))


def _source_refs(values: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    materialized = []
    for value in values:
        if not isinstance(value, Mapping):
            raise ValidationFailure("candidate-source-invalid", "source record references must be objects")
        if set(value) != {"record_id", "revision_digest"}:
            raise ValidationFailure("candidate-source-invalid", "source record references have unsupported fields")
        record_id = value.get("record_id")
        revision_digest = value.get("revision_digest")
        if not isinstance(record_id, str) or not isinstance(revision_digest, str):
            raise ValidationFailure("candidate-source-invalid", "source record references must contain strings")
        materialized.append({"record_id": record_id, "revision_digest": revision_digest})
    ordered = sorted(materialized, key=lambda value: value["record_id"])
    if not ordered or len({value["record_id"] for value in ordered}) != len(ordered):
        raise ValidationFailure("candidate-source-invalid", "candidate requires unique source record references")
    return ordered


def _candidate_body(candidate: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in candidate.items() if key not in {"candidate_id", "candidate_revision_digest"}}


def _candidate_identity(body: dict[str, Any]) -> tuple[str, str]:
    digest = sha256_bytes(canonical_bytes(body))
    return "candidate://" + body["candidate_provenance"][0]["source_ref"].split("://", 1)[0] + "/" + digest.removeprefix("sha-256:"), digest


def build_candidate(
    candidate_record: dict[str, Any],
    source_record_refs: Iterable[Mapping[str, Any]],
    candidate_provenance: Iterable[Mapping[str, Any]],
    *,
    sensitivity: str | None = None,
    owner_review_state: str = "required",
) -> dict[str, Any]:
    """Build one digest-bound draft candidate without admitting it."""
    sources = _source_refs(source_record_refs)
    source_revisions = {item["record_id"]: item["revision_digest"] for item in sources}
    normalized_record = deepcopy(candidate_record)
    for relationship in normalized_record.get("relationships", []):
        if isinstance(relationship, dict) and relationship.get("type") in RECORD_RELATIONSHIPS:
            revision = source_revisions.get(relationship.get("target_ref"))
            if revision is not None:
                relationship["target_revision_digest"] = revision
    validate(normalized_record, knowledge_schema(normalized_record))
    if normalized_record["schema_id"] not in {"artifact-memory/knowledge-record/v2", "artifact-memory/knowledge-record/v3"}:
        raise ValidationFailure("candidate-schema-unsupported", "candidate records require knowledge-record/v2 or v3")
    if normalized_record["lifecycle"] != "draft":
        raise ValidationFailure("candidate-lifecycle-invalid", "candidate records must remain draft before admission")
    provenance = []
    for item in candidate_provenance:
        if not isinstance(item, Mapping) or set(item) != {"kind", "source_ref"}:
            raise ValidationFailure("candidate-provenance-invalid", "candidate provenance fields are invalid")
        if item["kind"] not in {"agent", "adapter", "derivation"} or not isinstance(item["source_ref"], str) or not item["source_ref"]:
            raise ValidationFailure("candidate-provenance-invalid", "candidate provenance values are invalid")
        provenance.append({"kind": item["kind"], "source_ref": item["source_ref"]})
    if not provenance:
        raise ValidationFailure("candidate-provenance-invalid", "candidate provenance is required")
    if sensitivity is None:
        sensitivity = normalized_record.get("sensitivity", "restricted")
    if sensitivity not in {"public", "private", "restricted"}:
        raise ValidationFailure("candidate-sensitivity-invalid", "candidate sensitivity is unsupported")
    if normalized_record.get("sensitivity", sensitivity) != sensitivity:
        raise ValidationFailure("candidate-sensitivity-invalid", "candidate and record sensitivity must agree")
    if owner_review_state != "required":
        raise ValidationFailure("candidate-review-state-invalid", "new candidates require owner review")
    body = {
        "schema_id": "artifact-memory/knowledge-candidate/v1",
        "candidate_record": normalized_record,
        "source_record_refs": sources,
        "candidate_provenance": sorted(provenance, key=lambda item: (item["kind"], item["source_ref"])),
        "sensitivity": sensitivity,
        "owner_review_state": owner_review_state,
        "authority_boundary": AUTHORITY_BOUNDARY,
    }
    candidate_id, candidate_digest = _candidate_identity(body)
    result = {**body, "candidate_id": candidate_id, "candidate_revision_digest": candidate_digest}
    validate(result, load_schema("core", "knowledge-candidate.v1.schema.json"))
    return result


def _receipt(
    candidate: dict[str, Any],
    *,
    outcome: str,
    decision_ref: str,
    diagnostics: list[dict[str, str]] | None = None,
    result_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result_ref = None
    if result_record is not None:
        result_ref = {
            "record_id": result_record["record_id"],
            "revision_digest": _record_digest(result_record),
        }
    body = {
        "candidate_id": candidate["candidate_id"],
        "candidate_revision_digest": candidate["candidate_revision_digest"],
        "source_record_refs": candidate["source_record_refs"],
        "outcome": outcome,
        "decision_ref": decision_ref,
        "result_record_ref": result_ref,
        "diagnostics": diagnostics or [],
        "authority_boundary": AUTHORITY_BOUNDARY,
    }
    receipt = receipt_with_digest(
        "artifact-memory/candidate-admission-receipt/v1",
        "candidate-admission-receipt://",
        body,
    )
    validate(receipt, load_schema("core", "candidate-admission-receipt.v1.schema.json"))
    return receipt


def admit_candidate(
    candidate: dict[str, Any],
    *,
    decision: str,
    decision_ref: str,
    current_source_revisions: Mapping[str, str] | None = None,
    seen_candidate_ids: Iterable[str] = (),
    supported_result_schema_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Receipt one candidate decision and return a new accepted record when applicable.

    The function records a caller-supplied decision. It does not infer WITS meaning,
    authenticate an owner, or authorize any mutation outside the returned objects.
    """
    validate(candidate, load_schema("core", "knowledge-candidate.v1.schema.json"))
    candidate_id, candidate_digest = _candidate_identity(_candidate_body(candidate))
    if candidate["candidate_id"] != candidate_id:
        raise ValidationFailure("candidate-identity-mismatch", "candidate identity does not match its canonical body")
    if candidate["candidate_revision_digest"] != candidate_digest:
        raise ValidationFailure("candidate-digest-mismatch", "candidate revision digest does not match its canonical body")
    if not isinstance(decision_ref, str) or not decision_ref:
        raise ValidationFailure("candidate-decision-invalid", "candidate decision reference is required")
    if decision not in OUTCOMES:
        raise ValidationFailure("candidate-decision-invalid", "candidate decision outcome is unsupported")
    if candidate["candidate_id"] in set(seen_candidate_ids):
        return {"record": None, "receipt": _receipt(candidate, outcome="duplicate", decision_ref=decision_ref, diagnostics=[{"code": "candidate-replay", "message": "candidate identity was already processed"}])}

    if current_source_revisions is not None:
        stale = [
            item["record_id"]
            for item in candidate["source_record_refs"]
            if current_source_revisions.get(item["record_id"]) != item["revision_digest"]
        ]
        if stale:
            return {
                "record": None,
                "receipt": _receipt(candidate, outcome="stale", decision_ref=decision_ref, diagnostics=[{"code": "source-revision-stale", "message": "one or more source revisions are no longer current"}]),
            }

    if decision != "accepted":
        return {
            "record": None,
            "receipt": _receipt(candidate, outcome=decision, decision_ref=decision_ref, diagnostics=[{"code": "candidate-not-admitted", "message": "candidate was not admitted as current knowledge"}]),
        }

    supported_schema_values = list(supported_result_schema_ids)
    if any(not isinstance(value, str) or not value for value in supported_schema_values):
        raise ValidationFailure("candidate-schema-negotiation-invalid", "supported result schemas must be non-empty strings")
    supported_schemas = set(supported_schema_values)
    candidate_schema = candidate["candidate_record"]["schema_id"]
    if candidate_schema not in supported_schemas:
        return {
            "record": None,
            "receipt": _receipt(candidate, outcome="unsupported", decision_ref=decision_ref, diagnostics=[{"code": "result-schema-unnegotiated", "message": "the target consumer did not negotiate the candidate record schema"}]),
        }

    accepted_record = deepcopy(candidate["candidate_record"])
    accepted_record["lifecycle"] = "accepted"
    source_revisions = {item["record_id"]: item["revision_digest"] for item in candidate["source_record_refs"]}
    for relationship in accepted_record.get("relationships", []):
        if relationship["type"] in RECORD_RELATIONSHIPS and (
            relationship["target_ref"] not in source_revisions
            or relationship.get("target_revision_digest") != source_revisions[relationship["target_ref"]]
        ):
            return {
                "record": None,
                "receipt": _receipt(candidate, outcome="conflict", decision_ref=decision_ref, diagnostics=[{"code": "relationship-source-unbound", "message": "evolution relationship does not bind a declared source record"}]),
            }
    validate(accepted_record, knowledge_schema(accepted_record))
    return {"record": accepted_record, "receipt": _receipt(candidate, outcome="accepted", decision_ref=decision_ref, result_record=accepted_record)}


def current_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return accepted or sealed records eligible for a current projection."""
    materialized = []
    for record in records:
        validate(record, knowledge_schema(record))
        if record["lifecycle"] in {"accepted", "sealed"}:
            materialized.append(record)
    materialized.sort(key=lambda record: record["record_id"])
    if len({record["record_id"] for record in materialized}) != len(materialized):
        raise ValidationFailure("current-record-duplicate", "current record set contains duplicate logical identities")
    return materialized
