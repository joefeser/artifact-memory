"""Portable candidate admission and immutable knowledge-record evolution."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any

from .canonical import canonical_bytes, expected_receipt_id, receipt_with_digest, sha256_bytes
from .knowledge import knowledge_schema
from .schema_resources import load_schema
from .validator import ValidationFailure, validate


AUTHORITY_BOUNDARY = (
    "candidate admission grants no execution, disclosure, routing, mutation, merge, "
    "deployment, spending, credential, declassification, or approval authority"
)
RECORD_RELATIONSHIPS = {"supersedes", "disputes", "contradicts"}
OUTCOMES = {"accepted", "rejected", "quarantined", "duplicate", "stale", "unsupported", "conflict"}
CANDIDATE_SCHEMAS = {
    "artifact-memory/knowledge-candidate/v1": "knowledge-candidate.v1.schema.json",
    "artifact-memory/knowledge-candidate/v2": "knowledge-candidate.v2.schema.json",
}
PORTABLE_REFERENCE = re.compile(r"^[a-z][a-z0-9+.-]*://[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)*$")
LOGICAL_REFERENCE_SCHEMES = {
    "actor",
    "adapter",
    "artifact",
    "artifact-version",
    "authority",
    "candidate",
    "codex-task",
    "content",
    "decision",
    "external-evidence-binding",
    "fixture",
    "record",
    "record-revision",
    "release",
    "task",
    "tombstone",
    "transformation",
}
CANDIDATE_NAMESPACE = re.compile(r"^[A-Za-z0-9._~-]+$")


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
    if body.get("schema_id") == "artifact-memory/knowledge-candidate/v2":
        namespace = body["candidate_scope"]["namespace"]
    else:
        namespace = body["candidate_provenance"][0]["source_ref"].split("://", 1)[0]
    return "candidate://" + namespace + "/" + digest.removeprefix("sha-256:"), digest


def _portable_references(values: Iterable[str]) -> list[str]:
    if isinstance(values, str):
        raise ValidationFailure("candidate-scope-invalid", "bounded input references must be an iterable of portable references")
    try:
        materialized = list(values)
    except TypeError as exc:
        raise ValidationFailure("candidate-scope-invalid", "bounded input references must be an iterable of portable references") from exc
    if (
        not materialized
        or any(
            not isinstance(value, str)
            or PORTABLE_REFERENCE.fullmatch(value) is None
            or value.partition("://")[0] not in LOGICAL_REFERENCE_SCHEMES
            for value in materialized
        )
        or len(set(materialized)) != len(materialized)
    ):
        raise ValidationFailure("candidate-scope-invalid", "candidate scope requires unique portable input references")
    return sorted(materialized)


def _validate_v2_canonical_order(candidate: dict[str, Any]) -> None:
    provenance = candidate["candidate_provenance"]
    sources = candidate["source_record_refs"]
    bounded_inputs = candidate["candidate_scope"]["bounded_input_refs"]
    source_ids = [item["record_id"] for item in sources]
    if len(source_ids) != len(set(source_ids)):
        raise ValidationFailure("candidate-source-invalid", "candidate source references must have unique logical identities")
    if provenance != sorted(provenance, key=lambda item: (item["kind"], item["source_ref"])):
        raise ValidationFailure("candidate-order-invalid", "candidate provenance must use canonical order")
    if sources != sorted(sources, key=lambda item: item["record_id"]):
        raise ValidationFailure("candidate-order-invalid", "candidate source references must use canonical order")
    if bounded_inputs != sorted(bounded_inputs):
        raise ValidationFailure("candidate-order-invalid", "candidate bounded inputs must use canonical order")


def build_candidate(
    candidate_record: dict[str, Any],
    source_record_refs: Iterable[Mapping[str, Any]],
    candidate_provenance: Iterable[Mapping[str, Any]],
    *,
    sensitivity: str | None = None,
    owner_review_state: str = "required",
    candidate_namespace: str | None = None,
    bounded_input_refs: Iterable[str] | None = None,
    uncertainty: str | None = None,
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
    use_v2 = candidate_namespace is not None or bounded_input_refs is not None or uncertainty is not None
    if use_v2 and (candidate_namespace is None or bounded_input_refs is None):
        raise ValidationFailure("candidate-scope-invalid", "candidate v2 requires an explicit namespace and bounded input references")
    if use_v2 and (
        not isinstance(candidate_namespace, str)
        or CANDIDATE_NAMESPACE.fullmatch(candidate_namespace) is None
    ):
        raise ValidationFailure("candidate-scope-invalid", "candidate namespace is invalid")
    if uncertainty is not None and (not isinstance(uncertainty, str) or not uncertainty):
        raise ValidationFailure("candidate-uncertainty-invalid", "candidate uncertainty must be a non-empty string")

    provenance = []
    for item in candidate_provenance:
        if not isinstance(item, Mapping) or set(item) != {"kind", "source_ref"}:
            raise ValidationFailure("candidate-provenance-invalid", "candidate provenance fields are invalid")
        if item["kind"] not in {"agent", "adapter", "derivation"} or not isinstance(item["source_ref"], str) or not item["source_ref"]:
            raise ValidationFailure("candidate-provenance-invalid", "candidate provenance values are invalid")
        if use_v2 and (
            PORTABLE_REFERENCE.fullmatch(item["source_ref"]) is None
            or item["source_ref"].partition("://")[0] not in LOGICAL_REFERENCE_SCHEMES
        ):
            raise ValidationFailure("candidate-provenance-invalid", "candidate provenance references must use the portable reference form")
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
    schema_version = "v2" if use_v2 else "v1"
    body = {
        "schema_id": f"artifact-memory/knowledge-candidate/{schema_version}",
        "candidate_record": normalized_record,
        "source_record_refs": sources,
        "candidate_provenance": sorted(provenance, key=lambda item: (item["kind"], item["source_ref"])),
        "sensitivity": sensitivity,
        "owner_review_state": owner_review_state,
        "authority_boundary": AUTHORITY_BOUNDARY,
    }
    if use_v2:
        body["candidate_scope"] = {
            "namespace": candidate_namespace,
            "bounded_input_refs": _portable_references(bounded_input_refs),
        }
        if uncertainty is not None:
            body["uncertainty"] = uncertainty
    candidate_id, candidate_digest = _candidate_identity(body)
    result = {**body, "candidate_id": candidate_id, "candidate_revision_digest": candidate_digest}
    validate(result, load_schema("core", CANDIDATE_SCHEMAS[result["schema_id"]]))
    return result


def _receipt(
    candidate: dict[str, Any],
    *,
    outcome: str,
    decision_ref: str,
    diagnostics: list[dict[str, str]] | None = None,
    result_record: dict[str, Any] | None = None,
    predecessor_transitions: list[dict[str, Any]] | None = None,
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
    candidate_version = candidate["schema_id"].rsplit("/", 1)[-1]
    if candidate_version == "v2":
        body["predecessor_transitions"] = predecessor_transitions or []
    receipt = receipt_with_digest(
        f"artifact-memory/candidate-admission-receipt/{candidate_version}",
        "candidate-admission-receipt://",
        body,
    )
    validate_candidate_admission_receipt(receipt)
    return receipt


def validate_candidate_admission_receipt(receipt: dict[str, Any]) -> None:
    """Validate receipt shape, digest identity, and predecessor cross-bindings."""
    schema_id = receipt.get("schema_id") if isinstance(receipt, dict) else None
    if schema_id not in {
        "artifact-memory/candidate-admission-receipt/v1",
        "artifact-memory/candidate-admission-receipt/v2",
    }:
        raise ValidationFailure("candidate-receipt-unsupported", "candidate admission receipt schema is unsupported")
    version = schema_id.rsplit("/", 1)[-1]
    validate(receipt, load_schema("core", f"candidate-admission-receipt.{version}.schema.json"))
    if receipt["receipt_id"] != expected_receipt_id(receipt, "candidate-admission-receipt://"):
        raise ValidationFailure("candidate-receipt-identity-mismatch", "candidate admission receipt identity does not match its canonical body")
    if receipt["candidate_id"].rsplit("/", 1)[-1] != receipt["candidate_revision_digest"].removeprefix("sha-256:"):
        raise ValidationFailure("candidate-receipt-binding-mismatch", "candidate identity does not bind the candidate revision digest")
    source_revisions: dict[str, str] = {}
    for source in receipt["source_record_refs"]:
        if source["record_id"] in source_revisions:
            raise ValidationFailure("candidate-source-invalid", "receipt source references must have unique logical identities")
        source_revisions[source["record_id"]] = source["revision_digest"]
    if version == "v2" and receipt["source_record_refs"] != sorted(
        receipt["source_record_refs"], key=lambda item: item["record_id"]
    ):
        raise ValidationFailure("candidate-order-invalid", "receipt source references must use canonical order")
    transitions = receipt.get("predecessor_transitions", [])
    if (
        version == "v2"
        and receipt["outcome"] == "accepted"
        and receipt["result_record_ref"]["revision_digest"] in set(source_revisions.values())
    ):
        raise ValidationFailure("candidate-result-duplicate", "accepted candidate result must differ from every declared source revision")
    if transitions != sorted(transitions, key=lambda item: item["record_id"]):
        raise ValidationFailure("candidate-transition-order-invalid", "predecessor transitions must use canonical order")
    transition_ids = [transition["record_id"] for transition in transitions]
    if len(transition_ids) != len(set(transition_ids)):
        raise ValidationFailure("candidate-transition-duplicate", "predecessor transitions must have unique logical identities")
    for transition in transitions:
        if (
            source_revisions.get(transition["record_id"]) != transition["from_revision_digest"]
            or transition["superseded_by"] != receipt["result_record_ref"]
            or transition["from_revision_digest"] == transition["to_revision_digest"]
            or transition["from_revision_digest"] == receipt["result_record_ref"]["revision_digest"]
            or transition["to_revision_digest"] == receipt["result_record_ref"]["revision_digest"]
        ):
            raise ValidationFailure("candidate-transition-binding-mismatch", "predecessor transition does not bind the source and result revisions")


def _admission_result(
    candidate: dict[str, Any],
    *,
    record: dict[str, Any] | None,
    receipt: dict[str, Any],
    predecessor_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    result = {"record": record, "receipt": receipt}
    if candidate["schema_id"] == "artifact-memory/knowledge-candidate/v2":
        result["predecessor_records"] = predecessor_records or []
    return result


def admit_candidate(
    candidate: dict[str, Any],
    *,
    decision: str,
    decision_ref: str,
    current_source_revisions: Mapping[str, str] | None = None,
    seen_candidate_ids: Iterable[str] = (),
    supported_result_schema_ids: Iterable[str] = (),
    source_records: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Receipt one candidate decision and return a new accepted record when applicable.

    The function records a caller-supplied decision. It does not infer WITS meaning,
    authenticate an owner, or authorize any mutation outside the returned objects.
    """
    candidate_schema_id = candidate.get("schema_id") if isinstance(candidate, dict) else None
    candidate_schema_name = CANDIDATE_SCHEMAS.get(candidate_schema_id)
    if candidate_schema_name is None:
        raise ValidationFailure("candidate-schema-unsupported", "candidate schema is unsupported")
    validate(candidate, load_schema("core", candidate_schema_name))
    if candidate_schema_id == "artifact-memory/knowledge-candidate/v2":
        _validate_v2_canonical_order(candidate)
    candidate_id, candidate_digest = _candidate_identity(_candidate_body(candidate))
    if candidate["candidate_id"] != candidate_id:
        raise ValidationFailure("candidate-identity-mismatch", "candidate identity does not match its canonical body")
    if candidate["candidate_revision_digest"] != candidate_digest:
        raise ValidationFailure("candidate-digest-mismatch", "candidate revision digest does not match its canonical body")
    if not isinstance(decision_ref, str) or not decision_ref:
        raise ValidationFailure("candidate-decision-invalid", "candidate decision reference is required")
    if candidate_schema_id == "artifact-memory/knowledge-candidate/v2" and (
        PORTABLE_REFERENCE.fullmatch(decision_ref) is None
        or decision_ref.partition("://")[0] != "decision"
    ):
        raise ValidationFailure("candidate-decision-invalid", "candidate v2 decision reference must be a logical decision reference")
    if decision not in OUTCOMES:
        raise ValidationFailure("candidate-decision-invalid", "candidate decision outcome is unsupported")
    if candidate["candidate_id"] in set(seen_candidate_ids):
        receipt = _receipt(candidate, outcome="duplicate", decision_ref=decision_ref, diagnostics=[{"code": "candidate-replay", "message": "candidate identity was already processed"}])
        return _admission_result(candidate, record=None, receipt=receipt)

    if current_source_revisions is not None:
        stale = [
            item["record_id"]
            for item in candidate["source_record_refs"]
            if current_source_revisions.get(item["record_id"]) != item["revision_digest"]
        ]
        if stale:
            receipt = _receipt(candidate, outcome="stale", decision_ref=decision_ref, diagnostics=[{"code": "source-revision-stale", "message": "one or more source revisions are no longer current"}])
            return _admission_result(candidate, record=None, receipt=receipt)

    if decision != "accepted":
        receipt = _receipt(candidate, outcome=decision, decision_ref=decision_ref, diagnostics=[{"code": "candidate-not-admitted", "message": "candidate was not admitted as current knowledge"}])
        return _admission_result(candidate, record=None, receipt=receipt)

    if isinstance(supported_result_schema_ids, str):
        raise ValidationFailure("candidate-schema-negotiation-invalid", "supported result schemas must be non-empty strings")
    try:
        supported_schema_values = list(supported_result_schema_ids)
    except TypeError as exc:
        raise ValidationFailure("candidate-schema-negotiation-invalid", "supported result schemas must be non-empty strings") from exc
    if any(not isinstance(value, str) or not value for value in supported_schema_values):
        raise ValidationFailure("candidate-schema-negotiation-invalid", "supported result schemas must be non-empty strings")
    supported_schemas = set(supported_schema_values)
    candidate_record = candidate["candidate_record"]
    candidate_schema = candidate_record.get("schema_id") if isinstance(candidate_record, dict) else None
    if not isinstance(candidate_schema, str) or not candidate_schema:
        receipt = _receipt(candidate, outcome="rejected", decision_ref=decision_ref, diagnostics=[{"code": "candidate-record-invalid", "message": "embedded candidate record is not a valid knowledge record"}])
        return _admission_result(candidate, record=None, receipt=receipt)
    if candidate_schema not in supported_schemas:
        receipt = _receipt(candidate, outcome="unsupported", decision_ref=decision_ref, diagnostics=[{"code": "result-schema-unnegotiated", "message": "the target consumer did not negotiate the candidate record schema"}])
        return _admission_result(candidate, record=None, receipt=receipt)

    accepted_record = deepcopy(candidate["candidate_record"])
    accepted_record["lifecycle"] = "accepted"
    source_revisions = {item["record_id"]: item["revision_digest"] for item in candidate["source_record_refs"]}
    relationships = accepted_record.get("relationships", [])
    if not isinstance(relationships, list) or any(
        not isinstance(relationship, dict)
        or not isinstance(relationship.get("type"), str)
        or not relationship["type"]
        or not isinstance(relationship.get("target_ref"), str)
        or not relationship["target_ref"]
        for relationship in relationships
    ):
        receipt = _receipt(candidate, outcome="rejected", decision_ref=decision_ref, diagnostics=[{"code": "candidate-record-invalid", "message": "embedded candidate record relationships are malformed"}])
        return _admission_result(candidate, record=None, receipt=receipt)
    for relationship in relationships:
        if relationship["type"] in RECORD_RELATIONSHIPS and (
            relationship["target_ref"] not in source_revisions
            or relationship.get("target_revision_digest") != source_revisions[relationship["target_ref"]]
        ):
            receipt = _receipt(candidate, outcome="conflict", decision_ref=decision_ref, diagnostics=[{"code": "relationship-source-unbound", "message": "evolution relationship does not bind a declared source record"}])
            return _admission_result(candidate, record=None, receipt=receipt)
    validate(accepted_record, knowledge_schema(accepted_record))
    if (
        candidate_schema_id == "artifact-memory/knowledge-candidate/v2"
        and _record_digest(accepted_record) in set(source_revisions.values())
    ):
        receipt = _receipt(candidate, outcome="duplicate", decision_ref=decision_ref, diagnostics=[{"code": "result-revision-duplicate", "message": "candidate result matches an exact declared source revision"}])
        return _admission_result(candidate, record=None, receipt=receipt)

    predecessor_records: list[dict[str, Any]] = []
    predecessor_transitions: list[dict[str, Any]] = []
    if candidate_schema_id == "artifact-memory/knowledge-candidate/v2":
        try:
            source_record_values = list(source_records)
        except TypeError as exc:
            raise ValidationFailure("candidate-source-invalid", "source records must be iterable") from exc
        source_records_by_id: dict[str, dict[str, Any]] = {}
        for source_record in source_record_values:
            validate(source_record, knowledge_schema(source_record))
            source_id = source_record["record_id"]
            if source_id in source_records_by_id:
                raise ValidationFailure("candidate-source-invalid", "source records must have unique logical identities")
            source_records_by_id[source_id] = source_record
        accepted_ref = {"record_id": accepted_record["record_id"], "revision_digest": _record_digest(accepted_record)}
        supersedes_targets = [
            relationship["target_ref"]
            for relationship in relationships
            if relationship["type"] == "supersedes"
        ]
        if len(supersedes_targets) != len(set(supersedes_targets)):
            receipt = _receipt(candidate, outcome="conflict", decision_ref=decision_ref, diagnostics=[{"code": "predecessor-transition-duplicate", "message": "one predecessor cannot be transitioned more than once"}])
            return _admission_result(candidate, record=None, receipt=receipt)
        for relationship in sorted(relationships, key=lambda value: (value["type"], value["target_ref"])):
            if relationship["type"] != "supersedes":
                continue
            predecessor = source_records_by_id.get(relationship["target_ref"])
            if (
                predecessor is None
                or _record_digest(predecessor) != relationship["target_revision_digest"]
                or predecessor["lifecycle"] not in {"accepted", "sealed"}
            ):
                receipt = _receipt(candidate, outcome="conflict", decision_ref=decision_ref, diagnostics=[{"code": "predecessor-transition-unproven", "message": "supersession requires the exact current predecessor record"}])
                return _admission_result(candidate, record=None, receipt=receipt)
            if (
                current_source_revisions is None
                or current_source_revisions.get(predecessor["record_id"])
                != relationship["target_revision_digest"]
            ):
                receipt = _receipt(candidate, outcome="stale", decision_ref=decision_ref, diagnostics=[{"code": "predecessor-currentness-unproven", "message": "supersession requires current-revision evidence for the exact predecessor"}])
                return _admission_result(candidate, record=None, receipt=receipt)
            superseded = deepcopy(predecessor)
            superseded["lifecycle"] = "superseded"
            validate(superseded, knowledge_schema(superseded))
            predecessor_records.append(superseded)
            predecessor_transitions.append({
                "record_id": predecessor["record_id"],
                "from_revision_digest": _record_digest(predecessor),
                "from_lifecycle": predecessor["lifecycle"],
                "to_revision_digest": _record_digest(superseded),
                "to_lifecycle": "superseded",
                "superseded_by": accepted_ref,
            })
    receipt = _receipt(
        candidate,
        outcome="accepted",
        decision_ref=decision_ref,
        result_record=accepted_record,
        predecessor_transitions=predecessor_transitions,
    )
    return _admission_result(
        candidate,
        record=accepted_record,
        receipt=receipt,
        predecessor_records=predecessor_records,
    )


def render_candidate_admission_receipt(receipt: dict[str, Any]) -> str:
    """Render a stable human-readable projection of a checked admission receipt."""
    validate_candidate_admission_receipt(receipt)
    schema_id = receipt["schema_id"]
    result_ref = receipt["result_record_ref"]
    result = "none" if result_ref is None else f'{result_ref["record_id"]} @ {result_ref["revision_digest"]}'
    diagnostics = receipt["diagnostics"]
    transitions = receipt.get("predecessor_transitions", [])
    lines = [
        "# Candidate admission receipt",
        "",
        f'- Receipt: `{receipt["receipt_id"]}`',
        f'- Candidate: `{receipt["candidate_id"]}` @ `{receipt["candidate_revision_digest"]}`',
        f'- Outcome: `{receipt["outcome"]}`',
        f'- Decision reference: `{receipt["decision_ref"]}`',
        f'- Result record: `{result}`',
        f"- Predecessor transitions: `{len(transitions)}`",
        f"- Diagnostics: `{len(diagnostics)}`",
    ]
    for transition in transitions:
        lines.append(
            f'- Transition: `{transition["record_id"]}` from `{transition["from_lifecycle"]}` '
            f'@ `{transition["from_revision_digest"]}` to `{transition["to_lifecycle"]}` '
            f'@ `{transition["to_revision_digest"]}`'
        )
    for diagnostic in diagnostics:
        lines.append(f'- Diagnostic `{diagnostic["code"]}`: {diagnostic["message"]}')
    lines.extend(["", f'Authority boundary: {receipt["authority_boundary"]}.', ""])
    return "\n".join(lines)


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
