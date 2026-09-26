"""Synthetic AM-4 local-outbox outage and recovery proof."""

from __future__ import annotations

import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from .canonical import receipt_with_digest
from .coordination import revision_digest
from .coordination_sync import (
    SyncFailure,
    append_local_coordination_record,
    configure_local_hub,
    directory_digest,
    load_authorized_projection,
    sync,
)
from .schema_resources import load_schema
from .validator import load_json, validate


CONFORMANCE_SCHEMA_ID = (
    "artifact-memory/coordination-outbox-conformance-receipt/v0"
)
PROJECT_ID = "11111111-1111-4111-8111-111111111111"
PRINCIPAL_ID = "coordination-principal://synthetic/agent-1"
SESSION_ID = "coordination-session://synthetic/session-1"
HUB_ID = "coordination-hub://synthetic/hub-a"
SOAK_COUNT = 100
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _ulid(value: int) -> str:
    encoded = []
    for _ in range(26):
        encoded.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(encoded))


def _label(fixtures: Path) -> dict[str, Any]:
    label = load_json(fixtures / "coordination" / "access-label.json")
    label["may"]["readProjects"] = [PROJECT_ID]
    label["mayNot"]["readProjects"] = []
    label["may"]["syncTaskPackets"] = [PROJECT_ID]
    return label


def _task(
    fixtures: Path, label: dict[str, Any], ordinal: int
) -> dict[str, Any]:
    task = deepcopy(load_json(fixtures / "coordination" / "task-open.json"))
    task_id = "task_" + _ulid(ordinal)
    task["taskId"] = task_id
    task["record_id"] = (
        f"record://coordination/{task['originId']}/task/{task_id}"
    )
    task["title"] = f"Synthetic offline task {ordinal:03d}"
    task["accessLabelRef"] = {
        "record_id": label["record_id"],
        "revision_digest": revision_digest(label),
    }
    return task


def _canonical_pair_count(root: Path) -> int:
    return len(list((root / "canonical" / "coordination").glob("*/*.json")))


def run(fixtures: Path, _: Path | None = None) -> dict[str, Any]:
    label = _label(fixtures)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        vault = root / "vault"
        hub = root / "unreachable-hub"
        hub.write_text("synthetic unavailable endpoint", encoding="utf-8")

        append_receipts = [
            append_local_coordination_record(vault, _task(fixtures, label, ordinal))
            for ordinal in range(SOAK_COUNT)
        ]
        if any(item["outcome"] != "appended" for item in append_receipts):
            raise RuntimeError("offline local append did not store every pair")
        duplicate = append_local_coordination_record(
            vault, _task(fixtures, label, 0)
        )
        if duplicate["outcome"] != "duplicate":
            raise RuntimeError("exact local replay was not idempotent")

        local_before_failed_delivery = directory_digest(vault)
        try:
            sync(
                vault,
                hub,
                session_id=SESSION_ID,
                completed_at="2026-09-26T18:00:00Z",
            )
        except SyncFailure as exc:
            outage_code = exc.code
        else:
            raise RuntimeError("unreachable synthetic hub unexpectedly accepted sync")
        if outage_code != "sync-storage-unsafe":
            raise RuntimeError("unreachable synthetic hub returned the wrong diagnostic")
        if directory_digest(vault) != local_before_failed_delivery:
            raise RuntimeError("failed delivery changed the local canonical outbox")

        local_before_recovery = _canonical_pair_count(vault)
        if local_before_recovery != SOAK_COUNT:
            raise RuntimeError("failed sync changed the local canonical outbox")

        hub.unlink()
        configure_local_hub(
            hub,
            hub_id=HUB_ID,
            scope_generation=1,
            bindings=[
                {
                    "session_id": SESSION_ID,
                    "principal_id": PRINCIPAL_ID,
                    "access_label": label,
                }
            ],
        )
        recovered = sync(
            vault,
            hub,
            session_id=SESSION_ID,
            completed_at="2026-09-26T18:01:00Z",
        )
        admitted_count = sum(
            item["outcome"] == "admitted"
            for item in recovered["receipt"]["submission_outcomes"]
        )
        authorized_count = len(load_authorized_projection(vault))
        hub_count = _canonical_pair_count(hub)
        before_retry = (directory_digest(vault), directory_digest(hub))
        sync(
            vault,
            hub,
            session_id=SESSION_ID,
            completed_at="2026-09-26T18:02:00Z",
        )
        after_retry = (directory_digest(vault), directory_digest(hub))

        if admitted_count != SOAK_COUNT:
            raise RuntimeError("recovery did not admit every local pair")
        if authorized_count != SOAK_COUNT or hub_count != SOAK_COUNT:
            raise RuntimeError("recovery did not converge to the exact local union")
        if _canonical_pair_count(vault) != SOAK_COUNT:
            raise RuntimeError("recovery duplicated or lost a local pair")
        if before_retry != after_retry:
            raise RuntimeError("unchanged recovery retry was not byte-identical")

    receipt = receipt_with_digest(
        CONFORMANCE_SCHEMA_ID,
        "coordination-outbox-conformance-receipt://sha-256/",
        {
            "outcome": "passed",
            "append_count": SOAK_COUNT,
            "failed_delivery_code": outage_code,
            "local_pair_count_before_recovery": local_before_recovery,
            "admitted_pair_count_after_recovery": admitted_count,
            "hub_pair_count_after_recovery": hub_count,
            "authorized_pair_count_after_recovery": authorized_count,
            "loss_count": SOAK_COUNT - hub_count,
            "duplicate_count": hub_count - len(
                {
                    (
                        item["record_ref"]["record_id"],
                        item["record_ref"]["revision_digest"],
                    )
                    for item in append_receipts
                }
            ),
            "exact_local_replay": "duplicate-no-op",
            "unchanged_sync_retry": "byte-identical-no-op",
            "authority_boundary": (
                "synthetic outbox proof grants no execution, disclosure, authorization, or delivery authority"
            ),
        },
    )
    validate(
        receipt,
        load_schema(
            "core",
            "coordination-outbox-conformance-receipt.v0.schema.json",
        ),
    )
    return receipt


def render_coordination_outbox_conformance_receipt(
    receipt: dict[str, Any],
) -> str:
    return (
        "# Coordination outbox conformance receipt\n\n"
        f"- Outcome: `{receipt['outcome']}`\n"
        f"- Offline appends: `{receipt['append_count']}`\n"
        f"- Failed delivery code: `{receipt['failed_delivery_code']}`\n"
        f"- Local pairs before recovery: `{receipt['local_pair_count_before_recovery']}`\n"
        f"- Admitted pairs after recovery: `{receipt['admitted_pair_count_after_recovery']}`\n"
        f"- Hub pairs after recovery: `{receipt['hub_pair_count_after_recovery']}`\n"
        f"- Authorized pairs after recovery: `{receipt['authorized_pair_count_after_recovery']}`\n"
        f"- Losses: `{receipt['loss_count']}`\n"
        f"- Duplicates: `{receipt['duplicate_count']}`\n"
        f"- Exact local replay: `{receipt['exact_local_replay']}`\n"
        f"- Unchanged sync retry: `{receipt['unchanged_sync_retry']}`\n"
        f"- Receipt: `{receipt['receipt_id']}`\n\n"
        f"Authority boundary: {receipt['authority_boundary']}.\n"
    )
