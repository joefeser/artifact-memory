"""Synthetic AM-3 convergence and golden-vector proof."""

from __future__ import annotations

import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from .canonical import receipt_with_digest
from .coordination import revision_digest
from .coordination_sync import (
    SyncFailure,
    build_membership_pages,
    configure_local_hub,
    directory_digest,
    load_authorized_projection,
    pair_set_digest,
    pull,
    push,
    store_coordination_record,
    validate_membership_pages,
    validate_sync_receipt,
)
from .validator import load_json


PROJECT_A = "11111111-1111-4111-8111-111111111111"
PROJECT_B = "22222222-2222-4222-8222-222222222222"
PRINCIPAL = "coordination-principal://synthetic/agent-1"
SESSION = "coordination-session://synthetic/session-1"
READER_SESSION = "coordination-session://synthetic/session-reader"
HUB_ID = "coordination-hub://synthetic/hub-a"


def _label(fixtures: Path) -> dict[str, Any]:
    label = load_json(fixtures / "coordination" / "access-label.json")
    label["may"]["readProjects"] = [PROJECT_A, PROJECT_B]
    label["mayNot"]["readProjects"] = []
    label["may"]["syncTaskPackets"] = [PROJECT_A, PROJECT_B]
    return label


def _task(fixtures: Path, label: dict[str, Any], other: bool) -> dict[str, Any]:
    name = "same-human-id-other-origin.json" if other else "task-open.json"
    task = load_json(fixtures / "coordination" / name)
    if other:
        task["projectId"] = PROJECT_B
        task["projectName"] = "sample-analytics"
    task["accessLabelRef"] = {
        "record_id": label["record_id"],
        "revision_digest": revision_digest(label),
    }
    return task


def _label_identity(label: dict[str, Any], label_id: str) -> dict[str, Any]:
    changed = deepcopy(label)
    changed["labelId"] = label_id
    changed["record_id"] = (
        f"record://coordination/{changed['originId']}/label/{label_id}"
    )
    return changed


def _vector_receipt(pairs: list[dict[str, str]], page_count: int, label: dict[str, Any]) -> dict[str, Any]:
    return receipt_with_digest(
        "artifact-memory/coordination-sync-receipt/v0",
        "coordination-sync-receipt://sha-256/",
        {
            "hub_id": HUB_ID,
            "principal_id": PRINCIPAL,
            "access_label_ref": {
                "record_id": label["record_id"],
                "revision_digest": revision_digest(label),
            },
            "scope_generation": 1,
            "completed_at": "2026-09-25T20:00:00Z",
            "authorized_membership": {
                "pair_count": len(pairs),
                "pair_set_digest": pair_set_digest(pairs),
                "page_count": page_count,
            },
            "excluded_count": 0,
            "submission_outcomes": [],
            "transport_state": "authenticated",
            "issuer_state": "unverified",
            "authority_boundary": "sync receipt grants no execution, disclosure, authorization, or trust",
        },
    )


def run(fixtures: Path) -> dict[str, Any]:
    vectors = load_json(fixtures / "coordination-sync" / "v0" / "vectors.json")
    if not isinstance(vectors, dict):
        raise RuntimeError("coordination sync vectors must be an object")
    for vector in vectors["pair_set_vectors"]:
        if pair_set_digest(vector["pairs"]) != vector["expected_digest"]:
            raise RuntimeError(f"pair-set vector failed: {vector['name']}")
        if pair_set_digest(list(reversed(vector["pairs"]))) != vector["expected_digest"]:
            raise RuntimeError(f"pair-set order invariance failed: {vector['name']}")
    expected_outcomes = {
        "admitted": "admitted",
        "schema-invalid": "rejected",
        "digest-mismatch": "rejected",
        "unauthorized-project": "rejected",
        "unauthorized-record-type": "rejected",
        "label-mismatch": "rejected",
        "principal-mismatch": "rejected",
        "same-pair-different-bytes": "quarantined",
        "resource-limit": "rejected",
        "unsupported-required-extension": "rejected",
    }
    if {item["code"]: item["outcome"] for item in vectors["submission_outcomes"]} != expected_outcomes:
        raise RuntimeError("typed submission-outcome vector failed")

    label = _label(fixtures)
    invalid_reference = {
        "record_id": "record://synthetic/invalid-outcome",
        "revision_digest": "sha-256:" + "f" * 64,
    }
    for vector in vectors["invalid_submission_outcomes"]:
        invalid_receipt = _vector_receipt([], 1, label)
        invalid_body = {
            key: deepcopy(value)
            for key, value in invalid_receipt.items()
            if key not in {"schema_id", "receipt_id"}
        }
        invalid_body["submission_outcomes"] = [
            {
                "record_ref": invalid_reference,
                "code": vector["code"],
                "outcome": vector["outcome"],
            }
        ]
        digest_consistent_receipt = receipt_with_digest(
            "artifact-memory/coordination-sync-receipt/v0",
            "coordination-sync-receipt://sha-256/",
            invalid_body,
        )
        try:
            validate_sync_receipt(digest_consistent_receipt)
        except SyncFailure as exc:
            if exc.code != "sync-outcome-code-mismatch":
                raise RuntimeError(
                    "invalid submission-outcome vector returned the wrong diagnostic"
                ) from exc
        else:
            raise RuntimeError("invalid submission-outcome vector was accepted")

    pagination = vectors["pagination"]
    pairs = [
        {
            "record_id": f"record://synthetic/{index:04d}",
            "revision_digest": "sha-256:" + f"{index:064x}",
        }
        for index in range(pagination["pair_count"])
    ]
    receipt = _vector_receipt(pairs, pagination["expected_page_count"], label)
    pages = build_membership_pages(pairs, receipt["receipt_id"], PRINCIPAL, 1)
    if len(pages) != pagination["expected_page_count"]:
        raise RuntimeError("pagination vector failed")
    validate_membership_pages(receipt, deepcopy(pages))

    for vector in vectors["task_chain_vectors"]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            configure_local_hub(
                hub,
                hub_id=HUB_ID,
                scope_generation=1,
                bindings=[
                    {
                        "session_id": SESSION,
                        "principal_id": PRINCIPAL,
                        "access_label": label,
                    }
                ],
            )
            first = _task(fixtures, label, False)
            competing = deepcopy(first)
            competing["title"] = "Competing synthetic genesis"
            store_coordination_record(vault, first)
            store_coordination_record(vault, competing)
            outcomes = push(vault, hub, session_id=SESSION)
            if sorted(item["code"] for item in outcomes) != sorted(
                vector["expected_codes"]
            ):
                raise RuntimeError(f"task-chain vector failed: {vector['name']}")
            result = pull(
                vault,
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T20:00:00Z",
            )
            if (
                len(result["authorized_pairs"])
                != vector["expected_authorized_pair_count"]
            ):
                raise RuntimeError(
                    f"task-chain authorized-set vector failed: {vector['name']}"
                )

    for vector in vectors["record_bound_egress_vectors"]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, source, reader = root / "hub", root / "source", root / "reader"
            record_label = _label_identity(label, "label-sync-only")
            record_label["may"]["readProjects"] = []
            record_label["mayNot"]["readProjects"] = [PROJECT_A, PROJECT_B]
            reader_label = _label_identity(label, "label-reader")
            configure_local_hub(
                hub,
                hub_id=HUB_ID,
                scope_generation=1,
                bindings=[
                    {
                        "session_id": SESSION,
                        "principal_id": PRINCIPAL,
                        "access_label": record_label,
                    },
                    {
                        "session_id": READER_SESSION,
                        "principal_id": "coordination-principal://synthetic/reader",
                        "access_label": reader_label,
                    },
                ],
            )
            store_coordination_record(source, _task(fixtures, record_label, False))
            push(source, hub, session_id=SESSION)
            result = pull(
                reader,
                hub,
                session_id=READER_SESSION,
                completed_at="2026-09-25T20:00:00Z",
            )
            if (
                len(result["authorized_pairs"])
                != vector["expected_authorized_pair_count"]
                or result["receipt"]["excluded_count"]
                != vector["expected_excluded_count"]
            ):
                raise RuntimeError(
                    f"record-bound egress vector failed: {vector['name']}"
                )

    for vector in vectors["project_provenance_vectors"]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            provenance_label = deepcopy(label)
            provenance_label["projectNames"] = [
                item
                for item in provenance_label["projectNames"]
                if item["projectId"] == PROJECT_B
            ]
            configure_local_hub(
                hub,
                hub_id=HUB_ID,
                scope_generation=1,
                bindings=[
                    {
                        "session_id": SESSION,
                        "principal_id": PRINCIPAL,
                        "access_label": provenance_label,
                    }
                ],
            )
            store_coordination_record(
                vault,
                _task(fixtures, provenance_label, False),
            )
            outcomes = push(vault, hub, session_id=SESSION)
            if [item["code"] for item in outcomes] != [vector["expected_code"]]:
                raise RuntimeError(
                    f"project-provenance vector failed: {vector['name']}"
                )

    for vector in vectors["label_rotation_vectors"]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            broad = deepcopy(label)
            configure_local_hub(
                hub,
                hub_id=HUB_ID,
                scope_generation=vector["scope_generation"],
                bindings=[
                    {
                        "session_id": SESSION,
                        "principal_id": PRINCIPAL,
                        "access_label": broad,
                    }
                ],
            )
            store_coordination_record(vault, _task(fixtures, broad, True))
            outcomes = push(vault, hub, session_id=SESSION)
            narrow = deepcopy(broad)
            narrow["may"]["readProjects"] = [PROJECT_A]
            narrow["mayNot"]["readProjects"] = [PROJECT_B]
            configure_local_hub(
                hub,
                hub_id=HUB_ID,
                scope_generation=vector["scope_generation"],
                bindings=[
                    {
                        "session_id": SESSION,
                        "principal_id": PRINCIPAL,
                        "access_label": narrow,
                    }
                ],
            )
            result = pull(
                vault,
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T20:00:00Z",
            )
            if (
                result["receipt"]["submission_outcomes"] != outcomes
                or result["receipt"]["scope_generation"]
                != vector["scope_generation"]
                or len(result["authorized_pairs"])
                != vector["expected_authorized_pair_count"]
            ):
                raise RuntimeError(
                    f"label-rotation vector failed: {vector['name']}"
                )

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        hub, first, second = root / "hub", root / "first", root / "second"
        configure_local_hub(
            hub,
            hub_id=HUB_ID,
            scope_generation=1,
            bindings=[
                {
                    "session_id": SESSION,
                    "principal_id": PRINCIPAL,
                    "access_label": label,
                }
            ],
        )
        store_coordination_record(first, _task(fixtures, label, False))
        store_coordination_record(second, _task(fixtures, label, True))
        push(first, hub, session_id=SESSION)
        push(second, hub, session_id=SESSION)
        first_pull = pull(first, hub, session_id=SESSION, completed_at="2026-09-25T20:00:00Z")
        second_pull = pull(second, hub, session_id=SESSION, completed_at="2026-09-25T20:00:01Z")
        if len(load_authorized_projection(first)) != 2 or len(load_authorized_projection(second)) != 2:
            raise RuntimeError("two-replica union failed")
        before = (directory_digest(hub), directory_digest(first), directory_digest(second))
        push(first, hub, session_id=SESSION)
        pull(first, hub, session_id=SESSION, completed_at="2026-09-25T21:00:00Z")
        push(second, hub, session_id=SESSION)
        pull(second, hub, session_id=SESSION, completed_at="2026-09-25T21:00:01Z")
        after = (directory_digest(hub), directory_digest(first), directory_digest(second))
        if before != after:
            raise RuntimeError("unchanged second round was not byte-identical")

    body = {
        "outcome": "passed",
        "pair_set_vector_count": len(vectors["pair_set_vectors"]),
        "typed_outcome_count": len(vectors["submission_outcomes"]),
        "task_chain_vector_count": len(vectors["task_chain_vectors"]),
        "record_bound_egress_vector_count": len(
            vectors["record_bound_egress_vectors"]
        ),
        "project_provenance_vector_count": len(
            vectors["project_provenance_vectors"]
        ),
        "label_rotation_vector_count": len(vectors["label_rotation_vectors"]),
        "pagination_page_count": len(pages),
        "replica_count": 2,
        "authorized_union_pair_count": first_pull["receipt"]["authorized_membership"]["pair_count"],
        "second_replica_pair_count": second_pull["receipt"]["authorized_membership"]["pair_count"],
        "second_round": "byte-identical-no-op",
        "authority_boundary": "synthetic sync proof grants no execution, disclosure, authorization, or trust",
    }
    return receipt_with_digest(
        "artifact-memory/coordination-sync-conformance-receipt/v0",
        "coordination-sync-conformance-receipt://sha-256/",
        body,
    )
