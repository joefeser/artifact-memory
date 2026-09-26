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
    apply_pull_response,
    build_pull_response,
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
from .schema_resources import load_schema
from .validator import load_json, validate


PROJECT_A = "11111111-1111-4111-8111-111111111111"
PROJECT_B = "22222222-2222-4222-8222-222222222222"
PRINCIPAL = "coordination-principal://synthetic/agent-1"
SESSION = "coordination-session://synthetic/session-1"
READER_SESSION = "coordination-session://synthetic/session-reader"
HUB_ID = "coordination-hub://synthetic/hub-a"
CONFORMANCE_SCHEMA_ID = (
    "artifact-memory/coordination-sync-conformance-receipt/v0"
)


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


def run(
    fixtures: Path,
    coordination_fixture: Path | None = None,
) -> dict[str, Any]:
    fixture = coordination_fixture or fixtures / "coordination-sync" / "v0"
    vectors = load_json(fixture / "vectors.json")
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

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        oversized_hub = root / "hub"
        configure_local_hub(
            oversized_hub,
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
        oversized = _task(fixtures, label, False)
        oversized["title"] = "x" * pagination["oversized_record_bytes"]
        store_coordination_record(oversized_hub, oversized)
        try:
            build_pull_response(
                oversized_hub,
                session_id=SESSION,
                completed_at="2026-09-25T20:00:00Z",
            )
        except SyncFailure as exc:
            if exc.code != pagination["expected_oversized_record_code"]:
                raise RuntimeError(
                    "oversized response-page vector returned the wrong diagnostic"
                ) from exc
        else:
            raise RuntimeError("oversized response-page vector escaped egress")

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
            direct_hub = root / "direct-hub"
            direct_vault = root / "direct-vault"
            configure_local_hub(
                direct_hub,
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
            store_coordination_record(direct_hub, first)
            store_coordination_record(direct_hub, competing)
            try:
                pull(
                    direct_vault,
                    direct_hub,
                    session_id=SESSION,
                    completed_at="2026-09-25T20:00:00Z",
                )
            except SyncFailure as exc:
                if exc.code != vector["expected_direct_egress_code"]:
                    raise RuntimeError(
                        "direct-hub task-chain vector returned the wrong diagnostic"
                    ) from exc
            else:
                raise RuntimeError("direct-hub task-chain vector escaped egress")

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
            store_coordination_record(hub, record_label)
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
            before_config = (hub / "hub-config.json").read_bytes()
            try:
                configure_local_hub(
                    hub,
                    hub_id=HUB_ID,
                    scope_generation=vector["rollback_generation"],
                    bindings=[
                        {
                            "session_id": SESSION,
                            "principal_id": PRINCIPAL,
                            "access_label": broad,
                        }
                    ],
                )
            except SyncFailure as exc:
                if exc.code != vector["expected_rollback_code"]:
                    raise RuntimeError(
                        "scope-generation rollback returned the wrong diagnostic"
                    ) from exc
            else:
                raise RuntimeError("scope-generation rollback was accepted")
            if (hub / "hub-config.json").read_bytes() != before_config:
                raise RuntimeError("scope-generation rollback mutated hub configuration")
            store_coordination_record(vault, _task(fixtures, broad, True))
            outcomes = push(vault, hub, session_id=SESSION)
            try:
                push(vault, hub, session_id=SESSION)
            except SyncFailure as exc:
                if exc.code != "sync-pending-reconciliation-required":
                    raise RuntimeError(
                        "pending outcome replay returned the wrong diagnostic"
                    ) from exc
            else:
                raise RuntimeError(
                    "a second push overwrote unacknowledged outcomes"
                )
            stale_broad = build_pull_response(
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T20:00:00Z",
                submission_outcomes=outcomes,
            )
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
            try:
                apply_pull_response(vault, stale_broad)
            except SyncFailure as exc:
                if exc.code != "sync-receipt-order-conflict":
                    raise RuntimeError(
                        "equal-time scope replay returned the wrong diagnostic"
                    ) from exc
            else:
                raise RuntimeError(
                    "equal-time broader scope replay restored suppressed membership"
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
        "pending_outcome_recovery": "protected-and-consumed",
        "equal_time_scope_replay": "rejected",
        "authority_boundary": "synthetic sync proof grants no execution, disclosure, authorization, or trust",
    }
    receipt = receipt_with_digest(
        CONFORMANCE_SCHEMA_ID,
        "coordination-sync-conformance-receipt://sha-256/",
        body,
    )
    validate(
        receipt,
        load_schema(
            "core",
            "coordination-sync-conformance-receipt.v0.schema.json",
        ),
    )
    return receipt


def render_coordination_sync_conformance_receipt(
    receipt: dict[str, Any],
) -> str:
    return (
        "# Coordination sync conformance receipt\n\n"
        f"- Outcome: `{receipt['outcome']}`\n"
        f"- Replicas: `{receipt['replica_count']}`\n"
        f"- Authorized union pairs: `{receipt['authorized_union_pair_count']}`\n"
        f"- Pair-set vectors: `{receipt['pair_set_vector_count']}`\n"
        f"- Typed outcomes: `{receipt['typed_outcome_count']}`\n"
        f"- Task-chain vectors: `{receipt['task_chain_vector_count']}`\n"
        f"- Record-bound egress vectors: `{receipt['record_bound_egress_vector_count']}`\n"
        f"- Project-provenance vectors: `{receipt['project_provenance_vector_count']}`\n"
        f"- Label-rotation vectors: `{receipt['label_rotation_vector_count']}`\n"
        f"- Pagination pages: `{receipt['pagination_page_count']}`\n"
        f"- Second round: `{receipt['second_round']}`\n"
        f"- Pending outcome recovery: `{receipt['pending_outcome_recovery']}`\n"
        f"- Equal-time scope replay: `{receipt['equal_time_scope_replay']}`\n"
        f"- Receipt: `{receipt['receipt_id']}`\n\n"
        f"Authority boundary: {receipt['authority_boundary']}.\n"
    )
