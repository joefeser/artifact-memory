"""Strict v0 coordination-record validation without hub admission claims."""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any

from .canonical import CanonicalizationFailure, canonical_bytes, sha256_bytes
from .extensions import ExtensionFailure, preserve_extensions
from .location import ARTIFACT_REF, ENDPOINT_REF, RELATIVE_PATH
from .schema_resources import core_schemas
from .validator import ValidationFailure, load_json, validate


TASK_PACKET_SCHEMA_ID = "artifact-memory/coordination-task-packet/v0"
WORK_RECEIPT_SCHEMA_ID = "artifact-memory/coordination-work-receipt/v0"
ACCESS_LABEL_SCHEMA_ID = "artifact-memory/coordination-access-label/v0"
COORDINATION_SCHEMA_IDS = {
    TASK_PACKET_SCHEMA_ID,
    WORK_RECEIPT_SCHEMA_ID,
    ACCESS_LABEL_SCHEMA_ID,
}
FRESHNESS_EXTENSION_ID = (
    "https://artifact-memory.dev/extensions/coordination-freshness/v1"
)
AUTHORITY_BOUNDARY = (
    "informational only; authority requires independently authenticated WITS enforcement"
)


def revision_digest(record: dict[str, Any]) -> str:
    """Return the external revision digest for one canonical record body."""
    return sha256_bytes(canonical_bytes(record))


def _ref_key(reference: dict[str, str]) -> tuple[str, str]:
    return reference["record_id"], reference["revision_digest"]


def _with_record_path(exc: ValidationFailure, index: int) -> ValidationFailure:
    suffix = exc.path[1:] if exc.path.startswith("$") else f".{exc.path}"
    return ValidationFailure(exc.code, exc.message, f"$.records[{index}]{suffix}")


def _validate_extensions(record: dict[str, Any]) -> None:
    extensions = record.get("extensions")
    if extensions is None:
        return
    bundle = {
        "schema_id": "artifact-memory/extension-bundle/v1",
        "extensions": extensions,
    }
    try:
        preserved = preserve_extensions({"extensions": {}}, bundle)
    except ExtensionFailure as exc:
        raise ValidationFailure(exc.code, exc.message, exc.path) from exc
    if canonical_bytes(preserved["extensions"]) != canonical_bytes(extensions):
        raise ValidationFailure(
            "extension-preservation-failed",
            "optional extensions must be preserved canonically",
            "$.extensions",
        )
    freshness = extensions.get(FRESHNESS_EXTENSION_ID)
    if freshness is None:
        return
    if freshness.get("version") != "v1" or freshness.get("required") is not False:
        raise ValidationFailure(
            "freshness-extension-invalid",
            "coordination freshness must be optional version v1",
            f"$.extensions[{FRESHNESS_EXTENSION_ID!r}]",
        )
    value = freshness.get("value")
    if not isinstance(value, dict) or set(value) != {"trueAsOfCommit"}:
        raise ValidationFailure(
            "freshness-extension-invalid",
            "coordination freshness value must contain exactly trueAsOfCommit",
            f"$.extensions[{FRESHNESS_EXTENSION_ID!r}].value",
        )
    commit = value["trueAsOfCommit"]
    if not isinstance(commit, str) or len(commit) not in {40, 64} or any(
        character not in "0123456789abcdef" for character in commit
    ):
        raise ValidationFailure(
            "freshness-extension-invalid",
            "trueAsOfCommit must be a lowercase 40- or 64-hex Git object ID",
            f"$.extensions[{FRESHNESS_EXTENSION_ID!r}].value.trueAsOfCommit",
        )


def _validate_identity(record: dict[str, Any]) -> None:
    schema_id = record["schema_id"]
    if schema_id == TASK_PACKET_SCHEMA_ID:
        kind, identifier = "task", record["taskId"]
    elif schema_id == WORK_RECEIPT_SCHEMA_ID:
        kind, identifier = "receipt", record["receiptId"]
    else:
        kind, identifier = "label", record["labelId"]
    expected = f"record://coordination/{record['originId']}/{kind}/{identifier}"
    if record["record_id"] != expected:
        raise ValidationFailure(
            "coordination-record-id-mismatch",
            "record_id does not match originId and type-specific identifier",
            "$.record_id",
        )


def _validate_portable_locations(receipt: dict[str, Any]) -> None:
    for evidence_index, evidence in enumerate(receipt["evidence"]):
        for artifact_index, artifact in enumerate(evidence["artifacts"]):
            artifact_ref = artifact["artifactId"]
            endpoint_ref = artifact["location"]["endpoint_ref"]
            relative_path = artifact["location"]["relative_path"]
            logical_references = (
                (
                    artifact_ref,
                    ARTIFACT_REF,
                    f"$.evidence[{evidence_index}].artifacts[{artifact_index}].artifactId",
                ),
                (
                    endpoint_ref,
                    ENDPOINT_REF,
                    f"$.evidence[{evidence_index}].artifacts[{artifact_index}].location.endpoint_ref",
                ),
            )
            for value, pattern, path in logical_references:
                segments = value.split("://", 1)[-1].split("/")
                if pattern.fullmatch(value) is None or any(
                    not segment.strip(".") for segment in segments
                ):
                    raise ValidationFailure(
                        "artifact-logical-reference-invalid",
                        "artifact evidence must use canonical logical references",
                        path,
                    )
            if RELATIVE_PATH.fullmatch(relative_path) is None:
                raise ValidationFailure(
                    "artifact-location-nonportable",
                    "artifact location must be a portable endpoint-relative path",
                    f"$.evidence[{evidence_index}].artifacts[{artifact_index}].location.relative_path",
                )


def _validate_label_sets(label: dict[str, Any]) -> None:
    allowed = label["may"]["readProjects"]
    denied = label["mayNot"]["readProjects"]
    if len(allowed) != len(set(allowed)):
        raise ValidationFailure(
            "access-label-read-duplicate",
            "may.readProjects contains a duplicate project UUID",
            "$.may.readProjects",
        )
    if len(denied) != len(set(denied)):
        raise ValidationFailure(
            "access-label-read-duplicate",
            "mayNot.readProjects contains a duplicate project UUID",
            "$.mayNot.readProjects",
        )
    if set(allowed) & set(denied):
        raise ValidationFailure(
            "access-label-read-overlap",
            "read grants and denials must be disjoint",
            "$.mayNot.readProjects",
        )


def _label_declares_project(label: dict[str, Any], project_id: str) -> bool:
    """Match only the authoritative UUID; projectName is immutable provenance."""
    return any(item["projectId"] == project_id for item in label["projectNames"])


def _validate_task_chains(
    tasks: list[dict[str, Any]],
    pairs: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, tuple[str, str]]:
    by_record: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in tasks:
        by_record[task["record_id"]].append(task)
    leaves: dict[str, tuple[str, str]] = {}
    for record_id, revisions in by_record.items():
        genesis = [task for task in revisions if task["predecessor"] is None]
        if len(genesis) != 1:
            raise ValidationFailure(
                "coordination-chain-genesis-invalid",
                "each TaskPacket chain must contain exactly one genesis revision",
                "$.predecessor",
            )
        children: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        predecessor_pairs: set[tuple[str, str]] = set()
        for task in revisions:
            predecessor = task["predecessor"]
            if predecessor is None:
                continue
            predecessor_key = _ref_key(predecessor)
            predecessor_pairs.add(predecessor_key)
            if predecessor["record_id"] != record_id:
                raise ValidationFailure(
                    "coordination-predecessor-identity-mismatch",
                    "TaskPacket predecessor must retain the same record_id",
                    "$.predecessor.record_id",
                )
            prior = pairs.get(predecessor_key)
            if prior is None or prior.get("schema_id") != TASK_PACKET_SCHEMA_ID:
                raise ValidationFailure(
                    "coordination-predecessor-unresolved",
                    "TaskPacket predecessor does not resolve to an exact supplied revision",
                    "$.predecessor",
                )
            children[predecessor_key].append(task)
            if len(children[predecessor_key]) > 1:
                raise ValidationFailure(
                    "coordination-chain-forked",
                    "TaskPacket chain has more than one successor for an exact predecessor",
                    "$.predecessor",
                )
            # Contract source: v0-coordination-plane.md, "Canonical coordination
            # identity and task state". V0 permits only the exact open-to-claimed
            # successor described below; these are contract invariants, not policy.
            if task["status"] != "claimed" or prior["status"] != "open":
                raise ValidationFailure(
                    "coordination-transition-invalid",
                    "v0 TaskPacket successors must transition from open to claimed",
                    "$.status",
                )
            claim = task["claims"][0]
            if _ref_key(claim["taskRef"]) != predecessor_key:
                raise ValidationFailure(
                    "claim-task-ref-mismatch",
                    "claim taskRef must equal the successor's exact open predecessor",
                    "$.claims[0].taskRef",
                )
            if claim["principalId"] != task["assignedWriter"]:
                raise ValidationFailure(
                    "claim-principal-mismatch",
                    "claim principalId must equal assignedWriter",
                    "$.claims[0].principalId",
                )
            unchanged_fields = set(task) - {"status", "claims", "predecessor"}
            if unchanged_fields != set(prior) - {"status", "claims", "predecessor"} or any(
                task[field] != prior[field] for field in unchanged_fields
            ):
                raise ValidationFailure(
                    "coordination-transition-fields-changed",
                    "claim successor changed fields outside status, claims, and predecessor",
                    "$",
                )
        leaf_records = [
            task
            for task in revisions
            if (task["record_id"], revision_digest(task)) not in predecessor_pairs
        ]
        if len(leaf_records) != 1:
            raise ValidationFailure(
                "coordination-chain-forked",
                "TaskPacket chain must have one unique leaf in the supplied record set",
                "$",
            )
        leaf = leaf_records[0]
        leaves[record_id] = record_id, revision_digest(leaf)
    return leaves


def _resolve_label(
    reference: dict[str, str],
    pairs: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    label = pairs.get(_ref_key(reference))
    if label is None or label.get("schema_id") != ACCESS_LABEL_SCHEMA_ID:
        raise ValidationFailure(
            "access-label-ref-unresolved",
            "accessLabelRef does not resolve to an exact supplied AccessLabel revision",
            "$.accessLabelRef",
        )
    return label


def validate_coordination_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate a complete supplied coordination record set and its exact bindings.

    This validates record bodies and in-batch revision relationships. It does not
    claim that a hub admitted any revision; AM-3 owns admission evidence.
    """
    if not records:
        raise ValidationFailure("invalid-input", "at least one coordination record is required")
    schemas = core_schemas()
    materialized: list[dict[str, Any]] = []
    materialized_digests: list[str] = []
    pairs: dict[tuple[str, str], dict[str, Any]] = {}
    for index, candidate in enumerate(records):
        if not isinstance(candidate, dict):
            raise ValidationFailure(
                "invalid-input",
                "coordination record must be a JSON object",
                f"$.records[{index}]",
            )
        schema_id = candidate.get("schema_id")
        if schema_id not in COORDINATION_SCHEMA_IDS:
            raise ValidationFailure(
                "schema-unsupported",
                "records validate accepts only coordination v0 record schemas",
                f"$.records[{index}].schema_id",
            )
        try:
            validate(candidate, schemas[schema_id])
            _validate_identity(candidate)
            _validate_extensions(candidate)
            if schema_id == ACCESS_LABEL_SCHEMA_ID:
                _validate_label_sets(candidate)
            elif schema_id == WORK_RECEIPT_SCHEMA_ID:
                _validate_portable_locations(candidate)
            digest = revision_digest(candidate)
        except CanonicalizationFailure as exc:
            raise ValidationFailure(
                "canonicalization-failed",
                str(exc),
                f"$.records[{index}]",
            ) from exc
        except ValidationFailure as exc:
            raise _with_record_path(exc, index) from exc
        record = deepcopy(candidate)
        key = record["record_id"], digest
        if key in pairs:
            raise ValidationFailure(
                "duplicate-record-revision",
                "the same coordination record revision was supplied more than once",
                f"$.records[{index}]",
            )
        pairs[key] = record
        materialized.append(record)
        materialized_digests.append(digest)

    tasks = [record for record in materialized if record["schema_id"] == TASK_PACKET_SCHEMA_ID]
    claim_ids: dict[tuple[str, str], str] = {}
    for index, task in enumerate(materialized):
        if task["schema_id"] != TASK_PACKET_SCHEMA_ID or not task["claims"]:
            continue
        claim = task["claims"][0]
        claim_key = task["originId"], claim["claimId"]
        prior_record_id = claim_ids.get(claim_key)
        if prior_record_id is not None and prior_record_id != task["record_id"]:
            raise ValidationFailure(
                "coordination-claim-id-duplicate",
                "claimId must be unique within its origin namespace",
                f"$.records[{index}].claims[0].claimId",
            )
        claim_ids[claim_key] = task["record_id"]
    leaves = _validate_task_chains(tasks, pairs)
    for index, record in enumerate(materialized):
        if record["schema_id"] not in {TASK_PACKET_SCHEMA_ID, WORK_RECEIPT_SCHEMA_ID}:
            continue
        try:
            if record["schema_id"] == TASK_PACKET_SCHEMA_ID:
                label = _resolve_label(record["accessLabelRef"], pairs)
                if not _label_declares_project(label, record["projectId"]):
                    raise ValidationFailure(
                        "access-label-project-mismatch",
                        "AccessLabel project provenance does not match the coordination record",
                        "$.accessLabelRef",
                    )
                continue
            task_key = _ref_key(record["taskRef"])
            task = pairs.get(task_key)
            if task is None or task.get("schema_id") != TASK_PACKET_SCHEMA_ID:
                raise ValidationFailure(
                    "work-receipt-task-ref-unresolved",
                    "WorkReceipt taskRef does not resolve to an exact supplied TaskPacket revision",
                    "$.taskRef",
                )
            if leaves.get(task["record_id"]) != task_key:
                raise ValidationFailure(
                    "work-receipt-task-ref-stale",
                    "WorkReceipt taskRef does not name the unique supplied TaskPacket leaf",
                    "$.taskRef",
                )
            if task["status"] != "claimed":
                raise ValidationFailure(
                    "work-receipt-task-not-claimed",
                    "WorkReceipt must bind a claimed TaskPacket revision",
                    "$.taskRef",
                )
            if record["projectId"] != task["projectId"]:
                raise ValidationFailure(
                    "work-receipt-project-mismatch",
                    "WorkReceipt project must match its exact TaskPacket revision",
                    "$.projectId",
                )
            if record["accessLabelRef"] != task["accessLabelRef"]:
                raise ValidationFailure(
                    "work-receipt-label-mismatch",
                    "WorkReceipt AccessLabel must match its exact TaskPacket revision",
                    "$.accessLabelRef",
                )
            if record["writer"] != task["assignedWriter"]:
                raise ValidationFailure(
                    "work-receipt-writer-mismatch",
                    "WorkReceipt writer must match TaskPacket assignedWriter",
                    "$.writer",
                )
            label = _resolve_label(record["accessLabelRef"], pairs)
            if not _label_declares_project(label, record["projectId"]):
                raise ValidationFailure(
                    "access-label-project-mismatch",
                    "AccessLabel project provenance does not match the coordination record",
                    "$.accessLabelRef",
                )
        except ValidationFailure as exc:
            raise _with_record_path(exc, index) from exc

    type_counts = Counter(record["schema_id"] for record in materialized)
    return {
        "valid": True,
        "outcome": "accepted",
        "record_count": len(materialized),
        "type_counts": dict(sorted(type_counts.items())),
        "record_revisions": sorted(
            (
                {"record_id": record["record_id"], "revision_digest": digest}
                for record, digest in zip(materialized, materialized_digests)
            ),
            key=lambda item: (item["record_id"], item["revision_digest"]),
        ),
        "extensions_preserved_canonically": True,
        "hub_admission_verified": False,
        "authority_boundary": AUTHORITY_BOUNDARY,
        "diagnostics": [],
    }


def validate_coordination_files(paths: list[Path]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for index, path in enumerate(paths):
        try:
            value = load_json(path)
        except ValidationFailure as exc:
            raise ValidationFailure(exc.code, exc.message, f"$.files[{index}]") from exc
        if not isinstance(value, dict):
            raise ValidationFailure(
                "invalid-input",
                "coordination record must be a JSON object",
                f"$.files[{index}]",
            )
        records.append(value)
    return validate_coordination_records(records)
