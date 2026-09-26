import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from artifact_memory.canonical import canonical_bytes, receipt_with_digest, sha256_bytes
from artifact_memory.coordination import revision_digest
from artifact_memory.coordination_sync import (
    AUTHORITY_BOUNDARY,
    MEMBERSHIP_PAGE_SCHEMA_ID,
    SYNC_RECEIPT_SCHEMA_ID,
    SyncFailure,
    append_local_coordination_record,
    apply_pull_response,
    build_membership_pages,
    build_pull_response,
    configure_local_hub,
    directory_digest,
    export_authorized_coordination_context,
    load_authorized_projection,
    pair_set_digest,
    pull,
    push,
    sorted_pairs,
    store_coordination_record,
    sync,
    validate_membership_pages,
    validate_sync_receipt,
)
from artifact_memory.schema_resources import core_schemas
from artifact_memory.validator import ValidationFailure, load_json


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "coordination"
PROJECT_A = "11111111-1111-4111-8111-111111111111"
PROJECT_B = "22222222-2222-4222-8222-222222222222"
PRINCIPAL = "coordination-principal://synthetic/agent-1"
SESSION = "coordination-session://synthetic/session-1"
HUB_ID = "coordination-hub://synthetic/hub-a"


def fixture(name: str) -> dict:
    return load_json(FIXTURES / name)


def label_for(read_projects: list[str]) -> dict:
    label = fixture("access-label.json")
    label["may"]["readProjects"] = list(read_projects)
    label["mayNot"]["readProjects"] = [
        project for project in (PROJECT_A, PROJECT_B) if project not in read_projects
    ]
    label["may"]["syncTaskPackets"] = list(read_projects)
    label["may"]["syncWorkReceipts"] = list(read_projects)
    label["may"]["postReceipts"] = list(read_projects)
    return label


def label_identity(label: dict, label_id: str) -> dict:
    changed = copy.deepcopy(label)
    changed["labelId"] = label_id
    changed["record_id"] = (
        f"record://coordination/{changed['originId']}/label/{label_id}"
    )
    return changed


def task_for(label: dict, *, other_origin: bool = False, project_id: str = PROJECT_A) -> dict:
    task = fixture("same-human-id-other-origin.json" if other_origin else "task-open.json")
    task["projectId"] = project_id
    task["projectName"] = "sample-analytics" if project_id == PROJECT_B else "sample-service"
    task["accessLabelRef"] = {
        "record_id": label["record_id"],
        "revision_digest": revision_digest(label),
    }
    return task


def unique_task_for(label: dict, ordinal: int) -> dict:
    task = task_for(label)
    task_id = "task_" + f"{ordinal:026d}"
    task["taskId"] = task_id
    task["record_id"] = (
        f"record://coordination/{task['originId']}/task/{task_id}"
    )
    task["title"] = f"Synthetic bounded-batch task {ordinal}"
    return task


def claimed_task_for(label: dict) -> tuple[dict, dict]:
    opened = task_for(label)
    opened["assignedWriter"] = PRINCIPAL
    claimed = copy.deepcopy(opened)
    claimed["status"] = "claimed"
    claimed["predecessor"] = {
        "record_id": opened["record_id"],
        "revision_digest": revision_digest(opened),
    }
    claimed["claims"] = [
        {
            "claimId": "claim_01J00000000000000000000002",
            "principalId": PRINCIPAL,
            "taskRef": copy.deepcopy(claimed["predecessor"]),
            "claimedAt": "2026-09-25T19:05:00Z",
        }
    ]
    return opened, claimed


def work_receipt_for(label: dict, claimed_task: dict) -> dict:
    return {
        "schema_id": "artifact-memory/coordination-work-receipt/v0",
        "record_id": "record://coordination/33333333-3333-4333-8333-333333333333/receipt/rcpt-01J00000000000000000000001",
        "originId": "33333333-3333-4333-8333-333333333333",
        "receiptId": "rcpt-01J00000000000000000000001",
        "taskRef": {
            "record_id": claimed_task["record_id"],
            "revision_digest": revision_digest(claimed_task),
        },
        "writer": PRINCIPAL,
        "machine": "synthetic-client-a",
        "projectId": PROJECT_A,
        "projectName": "sample-service",
        "headSha": "a" * 40,
        "accessLabelRef": {
            "record_id": label["record_id"],
            "revision_digest": revision_digest(label),
        },
        "evidence": [
            {
                "command": "python3 -m unittest tests.test_synthetic_adapter",
                "exitCode": 0,
                "counts": {"passed": 1, "failed": 0, "skipped": 0},
                "artifacts": [],
            }
        ],
        "consumedTokensNote": None,
        "recordedAt": "2026-09-25T19:20:00Z",
        "authority_boundary": "informational only; authority requires independently authenticated WITS enforcement",
    }


def configure(hub: Path, label: dict, generation: int = 1) -> None:
    configure_local_hub(
        hub,
        hub_id=HUB_ID,
        scope_generation=generation,
        bindings=[
            {
                "session_id": SESSION,
                "principal_id": PRINCIPAL,
                "access_label": label,
            }
        ],
    )


def claimed_path(root: Path, record: dict, claimed_digest: str | None = None) -> Path:
    digest = claimed_digest or revision_digest(record)
    identity_hash = hashlib.sha256(record["record_id"].encode("utf-8")).hexdigest()
    return root / "canonical" / "coordination" / identity_hash / f"{digest.removeprefix('sha-256:')}.json"


def write_claimed(root: Path, record: dict, claimed_digest: str | None = None) -> Path:
    path = claimed_path(root, record, claimed_digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(record))
    return path


def receipt_for_pairs(pairs: list[dict[str, str]], page_count: int) -> dict:
    label = label_for([PROJECT_A])
    return receipt_with_digest(
        SYNC_RECEIPT_SCHEMA_ID,
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
            "authority_boundary": AUTHORITY_BOUNDARY,
        },
    )


class CoordinationSyncTests(unittest.TestCase):
    def test_two_vaults_converge_and_second_round_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, first, second = root / "hub", root / "first", root / "second"
            label = label_for([PROJECT_A, PROJECT_B])
            configure(hub, label)
            store_coordination_record(first, task_for(label))
            store_coordination_record(
                second, task_for(label, other_origin=True, project_id=PROJECT_B)
            )

            self.assertEqual([item["outcome"] for item in push(first, hub, session_id=SESSION)], ["admitted"])
            self.assertEqual([item["outcome"] for item in push(second, hub, session_id=SESSION)], ["admitted"])
            pull(first, hub, session_id=SESSION, completed_at="2026-09-25T20:00:00Z")
            pull(second, hub, session_id=SESSION, completed_at="2026-09-25T20:00:01Z")
            self.assertEqual(len(load_authorized_projection(first)), 2)
            self.assertEqual(len(load_authorized_projection(second)), 2)
            before = (directory_digest(hub), directory_digest(first), directory_digest(second))

            sync(first, hub, session_id=SESSION, completed_at="2026-09-25T21:00:00Z")
            sync(second, hub, session_id=SESSION, completed_at="2026-09-25T21:00:01Z")
            self.assertEqual(
                (directory_digest(hub), directory_digest(first), directory_digest(second)),
                before,
            )

    def test_outbox_larger_than_record_limit_drains_in_bounded_batches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            configure(hub, label)
            for ordinal in range(3):
                append_local_coordination_record(
                    vault, unique_task_for(label, ordinal)
                )

            with patch(
                "artifact_memory.coordination_sync.MAX_SUBMITTED_RECORDS", 2
            ):
                first = sync(
                    vault,
                    hub,
                    session_id=SESSION,
                    completed_at="2026-09-25T20:00:00Z",
                )
                second = sync(
                    vault,
                    hub,
                    session_id=SESSION,
                    completed_at="2026-09-25T20:00:01Z",
                )
                third = sync(
                    vault,
                    hub,
                    session_id=SESSION,
                    completed_at="2026-09-25T20:00:02Z",
                )

            self.assertEqual(len(first["submission_outcomes"]), 2)
            self.assertEqual(len(second["submission_outcomes"]), 1)
            self.assertEqual(third["submission_outcomes"], [])
            self.assertEqual(len(load_authorized_projection(vault)), 3)
            self.assertEqual(
                len(list((hub / "canonical" / "coordination").glob("*/*.json"))),
                3,
            )

    def test_outbox_larger_than_byte_limit_drains_in_bounded_batches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            configure(hub, label)
            tasks = [unique_task_for(label, ordinal) for ordinal in range(2)]
            for task in tasks:
                append_local_coordination_record(vault, task)
            one_record_limit = max(len(canonical_bytes(task)) for task in tasks) + 1

            with patch(
                "artifact_memory.coordination_sync.MAX_REQUEST_BYTES",
                one_record_limit,
            ):
                first = sync(
                    vault,
                    hub,
                    session_id=SESSION,
                    completed_at="2026-09-25T20:00:00Z",
                )
                second = sync(
                    vault,
                    hub,
                    session_id=SESSION,
                    completed_at="2026-09-25T20:00:01Z",
                )

            self.assertEqual(len(first["submission_outcomes"]), 1)
            self.assertEqual(len(second["submission_outcomes"]), 1)
            self.assertEqual(len(load_authorized_projection(vault)), 2)

    def test_local_append_rejects_undeliverable_record_bounds_before_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            label = label_for([PROJECT_A])
            oversized = unique_task_for(label, 1)
            limit = len(canonical_bytes(oversized)) + 1
            oversized["title"] += "x" * 100
            with patch(
                "artifact_memory.coordination_sync.MAX_RECORD_BYTES", limit
            ):
                with self.assertRaises(SyncFailure) as raised:
                    append_local_coordination_record(root / "oversized", oversized)
            self.assertEqual(raised.exception.code, "sync-record-too-large")
            self.assertFalse((root / "oversized").exists())

            long_field = unique_task_for(label, 2)
            long_field["title"] = "x" * 300
            with patch(
                "artifact_memory.coordination_sync.MAX_STRING_BYTES", 256
            ):
                with self.assertRaises(SyncFailure) as raised:
                    append_local_coordination_record(root / "long-field", long_field)
            self.assertEqual(raised.exception.code, "sync-field-too-large")
            self.assertFalse((root / "long-field").exists())

            too_deep = unique_task_for(label, 3)
            value: dict[str, object] = {}
            cursor = value
            for _ in range(70):
                nested: dict[str, object] = {}
                cursor["nested"] = nested
                cursor = nested
            too_deep["extensions"][
                "https://synthetic.example/extensions/deep/v1"
            ] = {"version": "v1", "required": False, "value": value}
            with self.assertRaises(SyncFailure) as raised:
                append_local_coordination_record(root / "too-deep", too_deep)
            self.assertEqual(raised.exception.code, "sync-depth-limit")
            self.assertFalse((root / "too-deep").exists())

    def test_local_append_syncs_created_directory_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vault = root / "vault"
            label = label_for([PROJECT_A])
            import artifact_memory.coordination_sync as coordination_sync

            with patch.object(
                coordination_sync,
                "_sync_directory",
                wraps=coordination_sync._sync_directory,
            ) as sync_directory:
                append_local_coordination_record(vault, unique_task_for(label, 1))

            synced = {call.args[0] for call in sync_directory.call_args_list}
            record_directories = list(
                (vault / "canonical" / "coordination").iterdir()
            )
            self.assertEqual(len(record_directories), 1)
            self.assertIn(record_directories[0], synced)

    def test_distinct_authoritative_revisions_of_one_record_merge_by_exact_pair(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            configure(hub, label)
            opened, claimed = claimed_task_for(label)
            store_coordination_record(hub, opened)
            store_coordination_record(hub, claimed)
            result = pull(vault, hub, session_id=SESSION, completed_at="2026-09-25T20:00:00Z")
            pairs = result["authorized_pairs"]
            self.assertEqual(len(pairs), 2)
            self.assertEqual({item["record_id"] for item in pairs}, {opened["record_id"]})
            self.assertEqual(len({item["revision_digest"] for item in pairs}), 2)

    def test_direct_hub_forked_or_incomplete_task_history_fails_egress_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            label = label_for([PROJECT_A])
            for scenario in ("competing-genesis", "orphan-successor"):
                with self.subTest(scenario=scenario):
                    hub, vault = root / scenario / "hub", root / scenario / "vault"
                    configure(hub, label)
                    opened, claimed = claimed_task_for(label)
                    if scenario == "competing-genesis":
                        competing = copy.deepcopy(opened)
                        competing["title"] = "Competing synthetic genesis"
                        store_coordination_record(hub, opened)
                        store_coordination_record(hub, competing)
                    else:
                        store_coordination_record(hub, claimed)
                    with self.assertRaises(SyncFailure) as raised:
                        pull(
                            vault,
                            hub,
                            session_id=SESSION,
                            completed_at="2026-09-25T20:00:00Z",
                        )
                    self.assertEqual(raised.exception.code, "hub-record-invalid")
                    self.assertFalse((vault / "generated").exists())

    def test_competing_open_task_genesis_is_rejected_without_forking_hub(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            configure(hub, label)
            first = task_for(label)
            competing = copy.deepcopy(first)
            competing["title"] = "Competing synthetic genesis"
            first_ref = store_coordination_record(vault, first)
            competing_ref = store_coordination_record(vault, competing)

            outcomes = push(vault, hub, session_id=SESSION)
            self.assertEqual(
                sorted(item["code"] for item in outcomes),
                ["admitted", "schema-invalid"],
            )
            admitted = {
                (
                    item["record_ref"]["record_id"],
                    item["record_ref"]["revision_digest"],
                )
                for item in outcomes
                if item["code"] == "admitted"
            }
            rejected = {
                (
                    item["record_ref"]["record_id"],
                    item["record_ref"]["revision_digest"],
                )
                for item in outcomes
                if item["code"] == "schema-invalid"
            }
            self.assertEqual(admitted | rejected, {
                (first_ref["record_id"], first_ref["revision_digest"]),
                (competing_ref["record_id"], competing_ref["revision_digest"]),
            })
            self.assertEqual(len(list((hub / "canonical" / "coordination").glob("*/*.json"))), 1)

            result = pull(
                vault,
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T20:00:00Z",
            )
            self.assertEqual(len(result["authorized_pairs"]), 1)
            self.assertEqual(
                {
                    (item["record_id"], item["revision_digest"])
                    for item in result["authorized_pairs"]
                },
                admitted,
            )

    def test_exact_open_replay_remains_admitted_after_claim_successor_exists(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            configure(hub, label)
            opened, claimed = claimed_task_for(label)
            store_coordination_record(hub, opened)
            store_coordination_record(hub, claimed)
            store_coordination_record(vault, opened)

            outcomes = push(vault, hub, session_id=SESSION)
            self.assertEqual([item["code"] for item in outcomes], ["admitted"])
            self.assertEqual(len(list((hub / "canonical" / "coordination").glob("*/*.json"))), 2)

    def test_task_identity_lock_prevents_cross_principal_admission_race(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, first_vault, second_vault = root / "hub", root / "first", root / "second"
            label = label_for([PROJECT_A])
            second_session = "coordination-session://synthetic/session-2"
            second_principal = "coordination-principal://synthetic/agent-2"
            configure_local_hub(
                hub,
                hub_id=HUB_ID,
                scope_generation=1,
                bindings=[
                    {
                        "session_id": SESSION,
                        "principal_id": PRINCIPAL,
                        "access_label": label,
                    },
                    {
                        "session_id": second_session,
                        "principal_id": second_principal,
                        "access_label": label,
                    },
                ],
            )
            first = task_for(label)
            competing = copy.deepcopy(first)
            competing["title"] = "Concurrent synthetic genesis"
            store_coordination_record(first_vault, first)
            store_coordination_record(second_vault, competing)

            entered = threading.Event()
            release = threading.Event()
            original = __import__(
                "artifact_memory.coordination_sync", fromlist=["_admit_submission"]
            )._admit_submission

            def blocked_admission(*args, **kwargs):
                entered.set()
                if not release.wait(timeout=5):
                    raise AssertionError("synthetic admission barrier timed out")
                return original(*args, **kwargs)

            thread_error: list[BaseException] = []

            def first_push() -> None:
                try:
                    push(first_vault, hub, session_id=SESSION)
                except BaseException as exc:  # pragma: no cover - asserted below
                    thread_error.append(exc)

            with patch(
                "artifact_memory.coordination_sync._admit_submission",
                side_effect=blocked_admission,
            ):
                worker = threading.Thread(target=first_push)
                worker.start()
                self.assertTrue(entered.wait(timeout=5))
                with self.assertRaises(SyncFailure) as busy:
                    push(second_vault, hub, session_id=second_session)
                self.assertEqual(busy.exception.code, "sync-task-admission-busy")
                release.set()
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
            self.assertEqual(thread_error, [])
            retry = push(second_vault, hub, session_id=second_session)
            self.assertEqual([item["code"] for item in retry], ["schema-invalid"])
            self.assertEqual(len(list((hub / "canonical" / "coordination").glob("*/*.json"))), 1)

    def test_work_receipt_requires_server_bound_writer_and_exact_claimed_task(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            configure(hub, label)
            opened, claimed = claimed_task_for(label)
            store_coordination_record(hub, opened)
            store_coordination_record(hub, claimed)
            receipt = work_receipt_for(label, claimed)
            store_coordination_record(vault, receipt)
            outcomes = push(vault, hub, session_id=SESSION)
            self.assertEqual(outcomes[0]["code"], "admitted")

            other = root / "other"
            wrong_writer = copy.deepcopy(receipt)
            wrong_writer["receiptId"] = "rcpt-01J00000000000000000000003"
            wrong_writer["record_id"] = (
                "record://coordination/33333333-3333-4333-8333-333333333333/receipt/"
                + wrong_writer["receiptId"]
            )
            wrong_writer["writer"] = "coordination-principal://synthetic/not-bound"
            store_coordination_record(other, wrong_writer)
            rejected = push(other, hub, session_id=SESSION)
            self.assertEqual(rejected[0]["code"], "principal-mismatch")

    def test_work_receipt_egress_requires_exact_current_claimed_task(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "valid-hub", root / "valid-vault"
            label = label_for([PROJECT_A])
            configure(hub, label)
            opened, claimed = claimed_task_for(label)
            receipt = work_receipt_for(label, claimed)
            for record in (opened, claimed, receipt):
                store_coordination_record(hub, record)
            result = pull(
                vault,
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T20:00:00Z",
            )
            self.assertEqual(len(result["authorized_pairs"]), 3)

        for case in ("missing", "open", "writer-mismatch"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                hub, vault = root / "hub", root / "vault"
                label = label_for([PROJECT_A])
                configure(hub, label)
                opened, claimed = claimed_task_for(label)
                receipt = work_receipt_for(label, claimed)
                if case == "open":
                    store_coordination_record(hub, opened)
                    receipt["taskRef"] = {
                        "record_id": opened["record_id"],
                        "revision_digest": revision_digest(opened),
                    }
                elif case == "writer-mismatch":
                    store_coordination_record(hub, opened)
                    store_coordination_record(hub, claimed)
                    receipt["writer"] = (
                        "coordination-principal://synthetic/different-writer"
                    )
                store_coordination_record(hub, receipt)

                with self.assertRaises(SyncFailure) as raised:
                    pull(
                        vault,
                        hub,
                        session_id=SESSION,
                        completed_at="2026-09-25T20:00:00Z",
                    )
                self.assertEqual(raised.exception.code, "hub-record-invalid")
                self.assertFalse((vault / "generated").exists())

    def test_sync_intake_requires_bound_label_project_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub = root / "hub"
            label = label_for([PROJECT_A, PROJECT_B])
            label["projectNames"] = [
                item
                for item in label["projectNames"]
                if item["projectId"] == PROJECT_B
            ]
            configure(hub, label)

            task_vault = root / "task-vault"
            store_coordination_record(task_vault, task_for(label))
            task_outcomes = push(task_vault, hub, session_id=SESSION)
            self.assertEqual([item["code"] for item in task_outcomes], ["schema-invalid"])

            opened, claimed = claimed_task_for(label)
            store_coordination_record(hub, opened)
            store_coordination_record(hub, claimed)
            receipt_vault = root / "receipt-vault"
            store_coordination_record(
                receipt_vault,
                work_receipt_for(label, claimed),
            )
            receipt_outcomes = push(receipt_vault, hub, session_id=SESSION)
            self.assertEqual(
                [item["code"] for item in receipt_outcomes],
                ["schema-invalid"],
            )

    def test_same_pair_different_bytes_quarantines_and_names_both_observed_digests(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            configure(hub, label)
            original = task_for(label)
            reference = store_coordination_record(hub, original)
            conflicting = copy.deepcopy(original)
            conflicting["title"] = "Different canonical bytes"
            write_claimed(vault, conflicting, reference["revision_digest"])
            outcomes = push(vault, hub, session_id=SESSION)
            self.assertEqual(outcomes[0]["outcome"], "quarantined")
            self.assertEqual(outcomes[0]["code"], "same-pair-different-bytes")
            reports = list((hub / "quarantine" / "coordination").glob("*.json"))
            self.assertEqual(len(reports), 1)
            report = load_json(reports[0])
            self.assertEqual(report["claimed_pair"], reference)
            self.assertEqual(
                report["observed_content_digests"],
                sorted([sha256_bytes(canonical_bytes(original)), sha256_bytes(canonical_bytes(conflicting))]),
            )
            self.assertEqual(claimed_path(hub, original).read_bytes(), canonical_bytes(original))

    def test_equivalent_noncanonical_json_is_not_quarantined_and_hub_stores_canonical_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            configure(hub, label)
            task = task_for(label)
            path = claimed_path(vault, task)
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(task, indent=2), encoding="utf-8")

            first = push(vault, hub, session_id=SESSION)
            self.assertEqual(first[0]["code"], "admitted")
            self.assertEqual(claimed_path(hub, task).read_bytes(), canonical_bytes(task))
            path.write_bytes(canonical_bytes(task))
            pull(
                vault,
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T20:00:00Z",
            )

            # Replaying alternate formatting for the same canonical pair is a
            # duplicate admission, never a same-pair collision.
            replay_vault = root / "replay-vault"
            path = claimed_path(replay_vault, task)
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(task, indent=4), encoding="utf-8")
            second = push(replay_vault, hub, session_id=SESSION)
            self.assertEqual(second[0]["code"], "admitted")
            self.assertEqual(list((hub / "quarantine").glob("**/*.json")), [])

    def test_push_cannot_overwrite_unacknowledged_outcomes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A, PROJECT_B])
            configure(hub, label)
            first_task = task_for(label)
            store_coordination_record(vault, first_task)
            first_outcomes = push(vault, hub, session_id=SESSION)
            pending_path = (
                vault
                / "generated"
                / "coordination-sync"
                / "pending-submission-outcomes.json"
            )
            before = pending_path.read_bytes()

            second_task = task_for(
                label,
                other_origin=True,
                project_id=PROJECT_B,
            )
            store_coordination_record(vault, second_task)
            with self.assertRaises(SyncFailure) as blocked:
                push(vault, hub, session_id=SESSION)
            self.assertEqual(
                blocked.exception.code,
                "sync-pending-reconciliation-required",
            )
            self.assertEqual(pending_path.read_bytes(), before)
            self.assertEqual(len(list((hub / "canonical" / "coordination").glob("*/*.json"))), 1)

            acknowledged = pull(
                vault,
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T20:00:00Z",
            )
            self.assertEqual(
                acknowledged["receipt"]["submission_outcomes"],
                first_outcomes,
            )
            self.assertEqual(
                [item["code"] for item in push(vault, hub, session_id=SESSION)],
                ["admitted"],
            )

    def test_receipt_manifest_and_submission_outcomes_bind_generated_projection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            configure(hub, label)
            task = task_for(label)
            store_coordination_record(vault, task)
            outcomes = push(vault, hub, session_id=SESSION)
            result = pull(vault, hub, session_id=SESSION, completed_at="2026-09-25T20:00:00Z")
            receipt = result["receipt"]
            validate_sync_receipt(receipt)
            self.assertEqual(receipt["submission_outcomes"], outcomes)
            self.assertEqual(receipt["authorized_membership"]["pair_count"], 1)
            self.assertEqual(receipt["excluded_count"], 1)
            self.assertEqual(receipt["transport_state"], "authenticated")
            self.assertEqual(receipt["issuer_state"], "unverified")
            self.assertNotIn(task["record_id"], json.dumps(receipt["excluded_count"]))

            forged = copy.deepcopy(receipt)
            forged["excluded_count"] += 1
            forged_path = root / "forged-receipt.json"
            forged_path.write_text(json.dumps(forged), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "artifact_memory",
                    "validate",
                    str(forged_path),
                    "--json",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(
                json.loads(completed.stdout)["diagnostics"][0]["code"],
                "sync-receipt-identity-mismatch",
            )

    def test_sync_receipt_schema_rejects_missing_unknown_nested_and_constant_mutations(self):
        receipt = receipt_for_pairs([], 1)
        for field in core_schemas()[SYNC_RECEIPT_SCHEMA_ID]["required"]:
            with self.subTest(missing=field):
                changed = copy.deepcopy(receipt)
                del changed[field]
                with self.assertRaises(ValidationFailure):
                    validate_sync_receipt(changed)

        mutations = []
        unknown = copy.deepcopy(receipt)
        unknown["unexpected"] = True
        mutations.append(unknown)
        for field, value in (
            ("schema_id", "artifact-memory/coordination-sync-receipt/v99"),
            ("receipt_id", "coordination-sync-receipt://sha-256/not-a-digest"),
            ("transport_state", "anonymous"),
            ("issuer_state", "verified"),
            ("authority_boundary", "grants authority"),
        ):
            changed = copy.deepcopy(receipt)
            changed[field] = value
            mutations.append(changed)
        missing_ref = copy.deepcopy(receipt)
        del missing_ref["access_label_ref"]["record_id"]
        mutations.append(missing_ref)
        unknown_membership = copy.deepcopy(receipt)
        unknown_membership["authorized_membership"]["unexpected"] = 1
        mutations.append(unknown_membership)
        invalid_outcome = copy.deepcopy(receipt)
        invalid_outcome["submission_outcomes"] = [
            {
                "record_ref": {
                    "record_id": "record://synthetic/one",
                    "revision_digest": "sha-256:" + "a" * 64,
                },
                "outcome": "admitted",
                "code": "admitted",
            }
        ]
        nested_required_paths = (
            ("access_label_ref", "record_id"),
            ("access_label_ref", "revision_digest"),
            ("authorized_membership", "pair_count"),
            ("authorized_membership", "pair_set_digest"),
            ("authorized_membership", "page_count"),
            ("submission_outcomes", 0, "record_ref"),
            ("submission_outcomes", 0, "outcome"),
            ("submission_outcomes", 0, "code"),
            ("submission_outcomes", 0, "record_ref", "record_id"),
            ("submission_outcomes", 0, "record_ref", "revision_digest"),
        )
        for path in nested_required_paths:
            changed = copy.deepcopy(invalid_outcome)
            target = changed
            for part in path[:-1]:
                target = target[part]
            del target[path[-1]]
            mutations.append(changed)

        nested_closed_paths = (
            ("access_label_ref",),
            ("authorized_membership",),
            ("submission_outcomes", 0),
            ("submission_outcomes", 0, "record_ref"),
        )
        for path in nested_closed_paths:
            changed = copy.deepcopy(invalid_outcome)
            target = changed
            for part in path:
                target = target[part]
            target["unexpected"] = True
            mutations.append(changed)

        invalid_values = (
            (("hub_id",), "https://synthetic.invalid/hub"),
            (("principal_id",), "synthetic-agent"),
            (("access_label_ref", "record_id"), "record://synthetic/not-a-label"),
            (("access_label_ref", "revision_digest"), "sha-256:not-a-digest"),
            (("scope_generation",), -1),
            (("completed_at",), "not-a-time"),
            (("authorized_membership", "pair_count"), -1),
            (("authorized_membership", "pair_set_digest"), "sha-256:bad"),
            (("authorized_membership", "page_count"), 0),
            (("excluded_count",), -1),
            (("submission_outcomes", 0, "record_ref", "record_id"), ""),
            (("submission_outcomes", 0, "record_ref", "revision_digest"), "bad"),
            (("submission_outcomes", 0, "outcome"), "accepted"),
            (("submission_outcomes", 0, "code"), "unknown-code"),
        )
        for path, value in invalid_values:
            changed = copy.deepcopy(invalid_outcome)
            target = changed
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value
            mutations.append(changed)
        for index, changed in enumerate(mutations):
            with self.subTest(mutation=index):
                with self.assertRaises(ValidationFailure):
                    validate_sync_receipt(changed)

    def test_sync_receipt_rejects_digest_consistent_outcome_code_mismatches(self):
        valid = receipt_for_pairs([], 1)
        reference = {
            "record_id": "record://synthetic/one",
            "revision_digest": "sha-256:" + "a" * 64,
        }
        mismatches = (
            ("admitted", "rejected"),
            ("schema-invalid", "admitted"),
            ("same-pair-different-bytes", "rejected"),
        )
        for code, outcome in mismatches:
            with self.subTest(code=code, outcome=outcome):
                body = {
                    key: copy.deepcopy(value)
                    for key, value in valid.items()
                    if key not in {"schema_id", "receipt_id"}
                }
                body["submission_outcomes"] = [
                    {"record_ref": reference, "outcome": outcome, "code": code}
                ]
                forged = receipt_with_digest(
                    SYNC_RECEIPT_SCHEMA_ID,
                    "coordination-sync-receipt://sha-256/",
                    body,
                )
                with self.assertRaises(SyncFailure) as raised:
                    validate_sync_receipt(forged)
                self.assertEqual(raised.exception.code, "sync-outcome-code-mismatch")

    def test_pair_set_digest_vectors_cover_empty_reordered_and_unicode(self):
        empty = pair_set_digest([])
        self.assertEqual(empty, sha256_bytes(b"[]"))
        pairs = [
            {"record_id": "record://synthetic/\u03b2", "revision_digest": "sha-256:" + "2" * 64},
            {"record_id": "record://synthetic/\u00e4", "revision_digest": "sha-256:" + "1" * 64},
        ]
        self.assertEqual(pair_set_digest(pairs), pair_set_digest(list(reversed(pairs))))
        self.assertEqual(sorted_pairs(pairs)[0]["record_id"], "record://synthetic/\u00e4")

    def test_pagination_reconstructs_complete_set_and_rejects_missing_or_duplicate_pages(self):
        pairs = [
            {
                "record_id": f"record://synthetic/{index:04d}",
                "revision_digest": "sha-256:" + f"{index:064x}",
            }
            for index in range(501)
        ]
        receipt = receipt_for_pairs(pairs, 2)
        pages = build_membership_pages(pairs, receipt["receipt_id"], PRINCIPAL, 1)
        self.assertEqual(len(pages), 2)
        self.assertEqual(validate_membership_pages(receipt, list(reversed(pages))), pairs)
        with self.assertRaises(SyncFailure) as missing:
            validate_membership_pages(receipt, pages[:1])
        self.assertEqual(missing.exception.code, "sync-page-missing")
        with self.assertRaises(SyncFailure) as duplicate:
            validate_membership_pages(receipt, [pages[0], pages[0]])
        self.assertEqual(duplicate.exception.code, "sync-page-duplicate")

    def test_oversized_singleton_hub_record_is_rejected_before_response_emission(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub = root / "hub"
            label = label_for([PROJECT_A])
            configure(hub, label)
            task = task_for(label)
            task["title"] = "oversized synthetic task"
            store_coordination_record(hub, task)
            with patch("artifact_memory.coordination_sync.MAX_PAGE_BYTES", 512):
                with self.assertRaises(SyncFailure) as raised:
                    build_pull_response(
                        hub,
                        session_id=SESSION,
                        completed_at="2026-09-25T20:00:00Z",
                    )
            self.assertEqual(raised.exception.code, "sync-page-too-large")

    def test_tampered_receipt_or_membership_does_not_advance_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            configure(hub, label)
            store_coordination_record(hub, task_for(label))
            response = build_pull_response(
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T20:00:00Z",
            )
            tampered = copy.deepcopy(response)
            tampered["receipt"]["excluded_count"] += 1
            with self.assertRaises(SyncFailure) as raised:
                apply_pull_response(vault, tampered)
            self.assertEqual(raised.exception.code, "sync-receipt-identity-mismatch")
            self.assertFalse((vault / "generated" / "coordination-sync" / "last-successful.json").exists())

            tampered = copy.deepcopy(response)
            tampered["pages"][0]["pairs"] = []
            with self.assertRaises(SyncFailure):
                apply_pull_response(vault, tampered)
            self.assertFalse((vault / "generated" / "coordination-sync" / "last-successful.json").exists())

    def test_projection_collision_precedes_canonical_record_exposure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            label = label_for([PROJECT_A])
            for target_name in ("receipt.json", "authorized-membership.json"):
                with self.subTest(target=target_name):
                    hub, vault = root / target_name / "hub", root / target_name / "vault"
                    configure(hub, label)
                    store_coordination_record(hub, task_for(label))
                    response = build_pull_response(
                        hub,
                        session_id=SESSION,
                        completed_at="2026-09-25T20:00:00Z",
                    )
                    projection = (
                        vault
                        / "generated"
                        / "coordination-sync"
                        / "projections"
                        / response["receipt"]["receipt_id"].rsplit("/", 1)[-1]
                    )
                    projection.mkdir(parents=True)
                    (projection / target_name).write_bytes(b"{}")
                    with self.assertRaises(SyncFailure) as raised:
                        apply_pull_response(vault, response)
                    self.assertEqual(
                        raised.exception.code,
                        "immutable-record-collision",
                    )
                    self.assertEqual(
                        list(
                            (vault / "canonical" / "coordination").glob("*/*.json")
                        ),
                        [],
                    )
                    self.assertFalse(
                        (
                            vault
                            / "generated"
                            / "coordination-sync"
                            / "last-successful.json"
                        ).exists()
                    )

    def test_push_ignores_malformed_historical_membership_without_crashing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A, PROJECT_B])
            configure(hub, label)
            store_coordination_record(hub, task_for(label))
            first = pull(
                vault,
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T20:00:00Z",
            )
            projection = (
                vault
                / "generated"
                / "coordination-sync"
                / "projections"
                / first["receipt"]["receipt_id"].rsplit("/", 1)[-1]
            )
            (projection / "authorized-membership.json").write_bytes(b"[{}]\n")
            store_coordination_record(
                vault,
                task_for(label, other_origin=True, project_id=PROJECT_B),
            )
            outcomes = push(vault, hub, session_id=SESSION)
            self.assertEqual(
                sorted(item["code"] for item in outcomes),
                ["admitted", "admitted"],
            )

    def test_tampered_existing_marker_and_prior_generation_cannot_advance_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            broad = label_for([PROJECT_A, PROJECT_B])
            configure(hub, broad, generation=1)
            store_coordination_record(hub, task_for(broad))
            pull(vault, hub, session_id=SESSION, completed_at="2026-09-25T20:00:00Z")
            marker_path = vault / "generated" / "coordination-sync" / "last-successful.json"
            marker = load_json(marker_path)
            marker["pair_count"] += 1
            marker_path.write_bytes(canonical_bytes(marker))
            response = build_pull_response(
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T20:01:00Z",
            )
            before = marker_path.read_bytes()
            with self.assertRaises(SyncFailure) as tampered:
                apply_pull_response(vault, response)
            self.assertEqual(tampered.exception.code, "sync-projection-mismatch")
            self.assertEqual(marker_path.read_bytes(), before)

            # Restore the valid generation-1 marker, advance to generation 2,
            # then prove a later-timestamped generation-1 replay cannot win.
            marker["pair_count"] -= 1
            marker_path.write_bytes(canonical_bytes(marker))
            stale = build_pull_response(
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T22:00:00Z",
            )
            narrow = label_for([PROJECT_A])
            configure(hub, narrow, generation=2)
            pull(vault, hub, session_id=SESSION, completed_at="2026-09-25T21:00:00Z")
            generation_two = marker_path.read_bytes()
            with self.assertRaises(SyncFailure) as replayed:
                apply_pull_response(vault, stale)
            self.assertEqual(replayed.exception.code, "sync-generation-stale")
            self.assertEqual(marker_path.read_bytes(), generation_two)

    def test_equal_time_conflicting_scope_receipt_cannot_restore_broader_view(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            broad = label_for([PROJECT_A, PROJECT_B])
            configure(hub, broad, generation=1)
            store_coordination_record(hub, task_for(broad))
            task_b = task_for(broad, other_origin=True, project_id=PROJECT_B)
            store_coordination_record(hub, task_b)
            pull(
                vault,
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T20:00:00Z",
            )
            stale_broad = build_pull_response(
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T21:00:00Z",
            )

            narrow = label_for([PROJECT_A])
            configure(hub, narrow, generation=1)
            pull(
                vault,
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T21:00:00Z",
            )
            marker_path = vault / "generated" / "coordination-sync" / "last-successful.json"
            before = marker_path.read_bytes()
            self.assertNotIn(task_b["record_id"], json.dumps(load_authorized_projection(vault)))

            with self.assertRaises(SyncFailure) as conflict:
                apply_pull_response(vault, stale_broad)
            self.assertEqual(conflict.exception.code, "sync-receipt-order-conflict")
            self.assertEqual(marker_path.read_bytes(), before)
            self.assertNotIn(task_b["record_id"], json.dumps(load_authorized_projection(vault)))

    def test_lowercase_z_timestamp_is_compared_without_untyped_crash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            configure(hub, label)
            store_coordination_record(hub, task_for(label))
            pull(vault, hub, session_id=SESSION, completed_at="2026-09-25T20:00:00z")
            result = pull(
                vault,
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T20:01:00Z",
            )
            self.assertEqual(result["outcome"], "no-op")

    def test_same_generation_membership_cannot_shrink_or_advance_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A, PROJECT_B])
            configure(hub, label)
            task_a = task_for(label)
            task_b = task_for(label, other_origin=True, project_id=PROJECT_B)
            store_coordination_record(hub, task_a)
            store_coordination_record(hub, task_b)
            pull(vault, hub, session_id=SESSION, completed_at="2026-09-25T20:00:00Z")
            marker_path = vault / "generated" / "coordination-sync" / "last-successful.json"
            before = marker_path.read_bytes()

            claimed_path(hub, task_b).unlink()
            with self.assertRaises(SyncFailure) as raised:
                pull(
                    vault,
                    hub,
                    session_id=SESSION,
                    completed_at="2026-09-25T20:01:00Z",
                )
            self.assertEqual(raised.exception.code, "sync-membership-regression")
            self.assertEqual(marker_path.read_bytes(), before)

    def test_label_rotation_rebuilds_projection_retains_history_and_suppresses_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            broad = label_for([PROJECT_A, PROJECT_B])
            configure(hub, broad, generation=1)
            task_a = task_for(broad)
            task_b = task_for(broad, other_origin=True, project_id=PROJECT_B)
            store_coordination_record(hub, task_a)
            store_coordination_record(hub, task_b)
            first = pull(vault, hub, session_id=SESSION, completed_at="2026-09-25T20:00:00Z")
            self.assertEqual(len(first["authorized_pairs"]), 2)

            narrow = label_for([PROJECT_A])
            configure(hub, narrow, generation=2)
            second = pull(vault, hub, session_id=SESSION, completed_at="2026-09-25T21:00:00Z")
            self.assertEqual(len(second["authorized_pairs"]), 1)
            self.assertEqual(second["receipt"]["excluded_count"], 3)
            self.assertEqual(len(list((vault / "canonical" / "coordination").glob("*/*.json"))), 2)
            exported = export_authorized_coordination_context(vault)
            self.assertEqual(exported["record_count"], 1)
            self.assertEqual(exported["records"][0]["projectId"], PROJECT_A)
            self.assertNotIn(task_b["record_id"], json.dumps(exported))
            self.assertEqual(len(list((hub / "policy" / "labels").glob("*/*.json"))), 2)

    def test_same_generation_label_revision_rebuilds_projection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            broad = label_for([PROJECT_A, PROJECT_B])
            configure(hub, broad, generation=1)
            store_coordination_record(hub, task_for(broad))
            task_b = task_for(broad, other_origin=True, project_id=PROJECT_B)
            store_coordination_record(hub, task_b)
            first = pull(
                vault,
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T20:00:00Z",
            )
            self.assertEqual(len(first["authorized_pairs"]), 2)

            narrow = label_for([PROJECT_A])
            configure(hub, narrow, generation=1)
            second = pull(
                vault,
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T21:00:00Z",
            )
            self.assertEqual(second["receipt"]["scope_generation"], 1)
            self.assertEqual(len(second["authorized_pairs"]), 1)
            self.assertNotIn(task_b["record_id"], json.dumps(second))

    def test_egress_intersects_caller_and_record_bound_access_labels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, source, reader = root / "hub", root / "source", root / "reader"
            record_label = label_identity(label_for([]), "label-sync-only")
            record_label["may"]["syncTaskPackets"] = [PROJECT_A]
            reader_label = label_identity(label_for([PROJECT_A]), "label-reader")
            reader_session = "coordination-session://synthetic/reader"
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
                        "session_id": reader_session,
                        "principal_id": "coordination-principal://synthetic/reader",
                        "access_label": reader_label,
                    },
                ],
            )
            task = task_for(record_label)
            store_coordination_record(source, task)
            self.assertEqual(push(source, hub, session_id=SESSION)[0]["code"], "admitted")

            result = pull(
                reader,
                hub,
                session_id=reader_session,
                completed_at="2026-09-25T20:00:00Z",
            )
            self.assertEqual(result["authorized_pairs"], [])
            self.assertEqual(result["receipt"]["excluded_count"], 3)
            self.assertNotIn(task["record_id"], json.dumps(result))

    def test_excluded_count_deduplicates_canonical_and_policy_label_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            configure(hub, label)
            store_coordination_record(hub, label)
            store_coordination_record(hub, task_for(label))
            result = pull(
                vault,
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T20:00:00Z",
            )
            self.assertEqual(len(result["authorized_pairs"]), 1)
            self.assertEqual(result["receipt"]["excluded_count"], 1)

    def test_malformed_unreferenced_policy_label_fails_egress_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            configure(hub, label)
            store_coordination_record(hub, task_for(label))
            malformed = (
                hub
                / "policy"
                / "labels"
                / ("f" * 64)
                / f"{'e' * 64}.json"
            )
            malformed.parent.mkdir()
            malformed.write_bytes(b"{}")
            with self.assertRaises(SyncFailure) as raised:
                pull(
                    vault,
                    hub,
                    session_id=SESSION,
                    completed_at="2026-09-25T20:00:00Z",
                )
            self.assertEqual(raised.exception.code, "hub-record-invalid")
            self.assertFalse((vault / "generated").exists())

    def test_egress_requires_project_provenance_in_the_caller_label(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            record_label = label_identity(label_for([PROJECT_A]), "label-record")
            configure(hub, record_label)
            task = task_for(record_label)
            store_coordination_record(hub, task)

            caller_label = label_identity(label_for([PROJECT_A]), "label-caller")
            caller_label["projectNames"] = [
                item
                for item in caller_label["projectNames"]
                if item["projectId"] != PROJECT_A
            ]
            configure(hub, caller_label, generation=2)
            result = pull(
                vault,
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T20:00:00Z",
            )
            self.assertEqual(result["authorized_pairs"], [])
            self.assertEqual(result["receipt"]["excluded_count"], 3)
            self.assertNotIn(task["record_id"], json.dumps(result))

    def test_missing_record_bound_access_label_fails_egress_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            configure(hub, label)
            store_coordination_record(hub, task_for(label))
            policy_path = next((hub / "policy" / "labels").glob("*/*.json"))
            policy_path.unlink()

            with self.assertRaises(SyncFailure) as raised:
                pull(
                    vault,
                    hub,
                    session_id=SESSION,
                    completed_at="2026-09-25T20:00:00Z",
                )
            self.assertEqual(raised.exception.code, "hub-record-invalid")
            self.assertFalse((vault / "generated").exists())

    def test_record_bound_label_without_project_provenance_fails_egress_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            malformed = label_identity(label_for([PROJECT_A]), "label-incomplete")
            malformed["projectNames"] = [
                item
                for item in malformed["projectNames"]
                if item["projectId"] != PROJECT_A
            ]
            configure(hub, malformed)
            store_coordination_record(hub, task_for(malformed))

            reader = label_identity(label_for([PROJECT_A]), "label-reader")
            configure(hub, reader, generation=2)
            with self.assertRaises(SyncFailure) as raised:
                pull(
                    vault,
                    hub,
                    session_id=SESSION,
                    completed_at="2026-09-25T20:00:00Z",
                )
            self.assertEqual(raised.exception.code, "hub-record-invalid")
            self.assertFalse((vault / "generated").exists())

    def test_local_authorized_set_tampering_fails_typed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            configure(hub, label)
            task = task_for(label)
            pair = store_coordination_record(hub, task)
            pull(vault, hub, session_id=SESSION, completed_at="2026-09-25T20:00:00Z")
            path = claimed_path(vault, task, pair["revision_digest"])
            changed = copy.deepcopy(task)
            changed["title"] = "tampered locally"
            path.write_bytes(canonical_bytes(changed))
            with self.assertRaises(SyncFailure) as raised:
                load_authorized_projection(vault)
            self.assertEqual(raised.exception.code, "sync-local-record-mismatch")

    def test_initial_outcome_codes_reject_or_quarantine_without_entering_union(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            configure(hub, label)

            write_claimed(vault, label)
            wrong_label = task_for(label, other_origin=True)
            wrong_label["accessLabelRef"]["revision_digest"] = "sha-256:" + "f" * 64
            write_claimed(vault, wrong_label)
            unauthorized = task_for(label, project_id=PROJECT_B)
            write_claimed(vault, unauthorized)
            malformed = task_for(label)
            malformed["unexpected"] = True
            write_claimed(vault, malformed)
            mismatch = task_for(label)
            mismatch["title"] = "digest mismatch"
            write_claimed(vault, mismatch, "sha-256:" + "e" * 64)
            required = task_for(label)
            required["extensions"] = {
                "https://synthetic.invalid/required/v1": {
                    "version": "v1",
                    "required": True,
                    "value": {},
                }
            }
            write_claimed(vault, required)

            outcomes = push(vault, hub, session_id=SESSION)
            codes = {item["code"] for item in outcomes}
            self.assertTrue(
                {
                    "unauthorized-record-type",
                    "label-mismatch",
                    "unauthorized-project",
                    "schema-invalid",
                    "digest-mismatch",
                    "unsupported-required-extension",
                }.issubset(codes)
            )
            self.assertEqual(list((hub / "canonical" / "coordination").glob("*/*.json")), [])

    def test_unknown_session_cannot_select_a_principal_or_label(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            configure(hub, label_for([PROJECT_A]))
            with self.assertRaises(SyncFailure) as raised:
                pull(
                    vault,
                    hub,
                    session_id="coordination-session://synthetic/not-bound",
                    completed_at="2026-09-25T20:00:00Z",
                )
            self.assertEqual(raised.exception.code, "principal-binding-invalid")
            self.assertFalse((vault / "generated").exists())

    def test_resource_limit_rejects_entire_request_before_admission(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            configure(hub, label)
            store_coordination_record(vault, task_for(label))
            with patch("artifact_memory.coordination_sync.MAX_RECORD_BYTES", 1):
                with self.assertRaises(SyncFailure) as raised:
                    push(vault, hub, session_id=SESSION)
            self.assertEqual(raised.exception.code, "sync-record-too-large")
            self.assertEqual(list((hub / "canonical" / "coordination").glob("*/*.json")), [])

    def test_pending_outcomes_reject_a_different_authenticated_principal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            other_session = "coordination-session://synthetic/session-2"
            other_principal = "coordination-principal://synthetic/agent-2"
            configure_local_hub(
                hub,
                hub_id=HUB_ID,
                scope_generation=1,
                bindings=[
                    {
                        "session_id": SESSION,
                        "principal_id": PRINCIPAL,
                        "access_label": label,
                    },
                    {
                        "session_id": other_session,
                        "principal_id": other_principal,
                        "access_label": label,
                    },
                ],
            )
            store_coordination_record(vault, task_for(label))
            push(vault, hub, session_id=SESSION)
            pending = vault / "generated" / "coordination-sync" / "pending-submission-outcomes.json"
            before = pending.read_bytes()
            with self.assertRaises(SyncFailure) as raised:
                pull(
                    vault,
                    hub,
                    session_id=other_session,
                    completed_at="2026-09-25T20:00:00Z",
                )
            self.assertEqual(raised.exception.code, "sync-pending-binding-mismatch")
            self.assertEqual(pending.read_bytes(), before)

    def test_pending_outcomes_follow_stable_principal_across_session_rotation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            configure(hub, label)
            store_coordination_record(vault, task_for(label))
            outcomes = push(vault, hub, session_id=SESSION)
            pending_path = (
                vault
                / "generated"
                / "coordination-sync"
                / "pending-submission-outcomes.json"
            )
            self.assertNotIn("session_id", load_json(pending_path))

            replacement_session = "coordination-session://synthetic/replacement"
            configure_local_hub(
                hub,
                hub_id=HUB_ID,
                scope_generation=1,
                bindings=[
                    {
                        "session_id": replacement_session,
                        "principal_id": PRINCIPAL,
                        "access_label": label,
                    }
                ],
            )
            result = pull(
                vault,
                hub,
                session_id=replacement_session,
                completed_at="2026-09-25T20:00:00Z",
            )
            self.assertEqual(result["receipt"]["submission_outcomes"], outcomes)
            self.assertFalse(pending_path.exists())
            with self.assertRaises(SyncFailure) as revoked:
                pull(
                    vault,
                    hub,
                    session_id=SESSION,
                    completed_at="2026-09-25T20:01:00Z",
                )
            self.assertEqual(revoked.exception.code, "principal-binding-invalid")

    def test_pending_outcomes_survive_access_label_identity_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            original_label = label_identity(label_for([PROJECT_A]), "label-original")
            configure(hub, original_label, generation=1)
            store_coordination_record(vault, task_for(original_label))
            outcomes = push(vault, hub, session_id=SESSION)
            pending_path = (
                vault
                / "generated"
                / "coordination-sync"
                / "pending-submission-outcomes.json"
            )

            replacement_label = label_identity(
                label_for([PROJECT_A]),
                "label-replacement",
            )
            configure(hub, replacement_label, generation=2)
            result = pull(
                vault,
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T20:00:00Z",
            )
            self.assertEqual(result["receipt"]["submission_outcomes"], outcomes)
            self.assertEqual(
                result["receipt"]["access_label_ref"],
                {
                    "record_id": replacement_label["record_id"],
                    "revision_digest": revision_digest(replacement_label),
                },
            )
            self.assertFalse(pending_path.exists())
            self.assertEqual(len(result["authorized_pairs"]), 1)

    def test_configuration_rotation_cannot_race_an_in_flight_principal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            broad = label_for([PROJECT_A, PROJECT_B])
            configure(hub, broad)
            store_coordination_record(vault, task_for(broad))
            entered = threading.Event()
            release = threading.Event()
            module = __import__(
                "artifact_memory.coordination_sync",
                fromlist=["_push_bound"],
            )
            original = module._push_bound
            thread_error: list[BaseException] = []

            def blocked_push(*args, **kwargs):
                entered.set()
                if not release.wait(timeout=5):
                    raise AssertionError("synthetic configuration barrier timed out")
                return original(*args, **kwargs)

            def run_push() -> None:
                try:
                    push(vault, hub, session_id=SESSION)
                except BaseException as exc:  # pragma: no cover - asserted below
                    thread_error.append(exc)

            with patch(
                "artifact_memory.coordination_sync._push_bound",
                side_effect=blocked_push,
            ):
                worker = threading.Thread(target=run_push)
                worker.start()
                self.assertTrue(entered.wait(timeout=5))
                narrow = label_for([PROJECT_A])
                with self.assertRaises(SyncFailure) as busy:
                    configure(hub, narrow, generation=2)
                self.assertEqual(busy.exception.code, "sync-principal-busy")
                release.set()
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())

            self.assertEqual(thread_error, [])
            configure(hub, narrow, generation=2)
            self.assertEqual(load_json(hub / "hub-config.json")["scope_generation"], 2)

    def test_configuration_cannot_relabel_an_existing_logical_hub(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            configure(hub, label)
            store_coordination_record(hub, task_for(label))
            config_path = hub / "hub-config.json"
            before_config = config_path.read_bytes()
            before_labels = {
                path.relative_to(hub): path.read_bytes()
                for path in (hub / "policy" / "labels").glob("*/*.json")
            }

            replacement = label_identity(label, "label-other-hub")
            with self.assertRaises(SyncFailure) as raised:
                configure_local_hub(
                    hub,
                    hub_id="coordination-hub://synthetic/hub-b",
                    scope_generation=2,
                    bindings=[
                        {
                            "session_id": SESSION,
                            "principal_id": PRINCIPAL,
                            "access_label": replacement,
                        }
                    ],
                )
            self.assertEqual(raised.exception.code, "hub-identity-mismatch")
            self.assertEqual(config_path.read_bytes(), before_config)
            self.assertEqual(
                {
                    path.relative_to(hub): path.read_bytes()
                    for path in (hub / "policy" / "labels").glob("*/*.json")
                },
                before_labels,
            )
            result = pull(
                vault,
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T20:00:00Z",
            )
            self.assertEqual(result["receipt"]["hub_id"], HUB_ID)
            self.assertEqual(len(result["authorized_pairs"]), 1)

    def test_configuration_rejects_scope_generation_rollback_without_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            broad = label_for([PROJECT_A, PROJECT_B])
            configure(hub, broad, generation=2)
            store_coordination_record(vault, task_for(broad))
            push(vault, hub, session_id=SESSION)
            config_path = hub / "hub-config.json"
            pending_path = (
                vault
                / "generated"
                / "coordination-sync"
                / "pending-submission-outcomes.json"
            )
            before_config = config_path.read_bytes()
            before_pending = pending_path.read_bytes()
            before_labels = {
                path.relative_to(hub): path.read_bytes()
                for path in (hub / "policy" / "labels").glob("*/*.json")
            }

            with self.assertRaises(SyncFailure) as raised:
                configure(hub, label_for([PROJECT_A]), generation=1)
            self.assertEqual(raised.exception.code, "scope-generation-rollback")
            self.assertEqual(config_path.read_bytes(), before_config)
            self.assertEqual(pending_path.read_bytes(), before_pending)
            self.assertEqual(
                {
                    path.relative_to(hub): path.read_bytes()
                    for path in (hub / "policy" / "labels").glob("*/*.json")
                },
                before_labels,
            )
            result = pull(
                vault,
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T20:00:00Z",
            )
            self.assertEqual(result["receipt"]["scope_generation"], 2)
            self.assertFalse(pending_path.exists())

    def test_pending_outcomes_reconcile_across_label_rotation_before_new_push(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            broad = label_for([PROJECT_A, PROJECT_B])
            configure(hub, broad, generation=1)
            task = task_for(broad)
            store_coordination_record(vault, task)
            outcomes = push(vault, hub, session_id=SESSION)
            pending_path = (
                vault
                / "generated"
                / "coordination-sync"
                / "pending-submission-outcomes.json"
            )
            pending = load_json(pending_path)
            self.assertEqual(pending["access_label_ref"], {
                "record_id": broad["record_id"],
                "revision_digest": revision_digest(broad),
            })
            self.assertEqual(pending["scope_generation"], 1)

            narrow = label_for([PROJECT_A])
            configure(hub, narrow, generation=2)
            before = pending_path.read_bytes()
            with self.assertRaises(SyncFailure) as push_blocked:
                push(vault, hub, session_id=SESSION)
            self.assertEqual(
                push_blocked.exception.code,
                "sync-pending-reconciliation-required",
            )
            self.assertEqual(pending_path.read_bytes(), before)

            result = pull(
                vault,
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T20:00:00Z",
            )
            self.assertEqual(result["receipt"]["submission_outcomes"], outcomes)
            self.assertEqual(result["receipt"]["access_label_ref"], {
                "record_id": narrow["record_id"],
                "revision_digest": revision_digest(narrow),
            })
            self.assertEqual(result["receipt"]["scope_generation"], 2)
            self.assertFalse(pending_path.exists())
            self.assertEqual(len(load_authorized_projection(vault)), 1)

    def test_pending_outcomes_reconcile_across_same_generation_label_revision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            broad = label_for([PROJECT_A, PROJECT_B])
            configure(hub, broad, generation=1)
            task = task_for(broad, other_origin=True, project_id=PROJECT_B)
            store_coordination_record(vault, task)
            outcomes = push(vault, hub, session_id=SESSION)
            pending_path = (
                vault
                / "generated"
                / "coordination-sync"
                / "pending-submission-outcomes.json"
            )

            narrow = label_for([PROJECT_A])
            configure(hub, narrow, generation=1)
            before = pending_path.read_bytes()
            with self.assertRaises(SyncFailure) as push_blocked:
                push(vault, hub, session_id=SESSION)
            self.assertEqual(
                push_blocked.exception.code,
                "sync-pending-reconciliation-required",
            )
            self.assertEqual(pending_path.read_bytes(), before)

            result = pull(
                vault,
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T20:00:00Z",
            )
            self.assertEqual(result["receipt"]["submission_outcomes"], outcomes)
            self.assertEqual(result["receipt"]["scope_generation"], 1)
            self.assertEqual(result["authorized_pairs"], [])
            self.assertFalse(pending_path.exists())

    def test_acknowledged_pairs_are_filtered_by_hub_and_principal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_hub, second_hub, vault = root / "first", root / "second", root / "vault"
            label = label_for([PROJECT_A])
            configure(first_hub, label)
            configure_local_hub(
                second_hub,
                hub_id="coordination-hub://synthetic/hub-b",
                scope_generation=1,
                bindings=[
                    {
                        "session_id": SESSION,
                        "principal_id": PRINCIPAL,
                        "access_label": label,
                    }
                ],
            )
            store_coordination_record(vault, task_for(label))
            push(vault, first_hub, session_id=SESSION)
            pull(
                vault,
                first_hub,
                session_id=SESSION,
                completed_at="2026-09-25T20:00:00Z",
            )
            outcomes = push(vault, second_hub, session_id=SESSION)
            self.assertEqual([item["code"] for item in outcomes], ["admitted"])

    def test_stale_lock_file_does_not_block_sync(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            configure(hub, label)
            store_coordination_record(vault, task_for(label))
            legacy_lock_name = hashlib.sha256(PRINCIPAL.encode("utf-8")).hexdigest()
            lock_name = hashlib.sha256(f"principal:{PRINCIPAL}".encode("utf-8")).hexdigest()
            # A crash from the prior directory-sentinel implementation and a
            # stale file from the advisory implementation are both inert.
            (hub / "locks" / legacy_lock_name).mkdir(parents=True)
            lock = hub / "locks" / f"{lock_name}.lock"
            lock.write_text("stale", encoding="utf-8")
            self.assertEqual(push(vault, hub, session_id=SESSION)[0]["code"], "admitted")

    def test_pull_holds_principal_lock_through_pending_outcome_consumption(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            configure(hub, label)
            store_coordination_record(vault, task_for(label))
            outcomes = push(vault, hub, session_id=SESSION)
            pending_path = (
                vault
                / "generated"
                / "coordination-sync"
                / "pending-submission-outcomes.json"
            )
            before = pending_path.read_bytes()
            entered = threading.Event()
            release = threading.Event()
            module = __import__(
                "artifact_memory.coordination_sync",
                fromlist=["apply_pull_response"],
            )
            original = module.apply_pull_response
            result: list[dict] = []
            thread_error: list[BaseException] = []

            def blocked_apply(*args, **kwargs):
                entered.set()
                if not release.wait(timeout=5):
                    raise AssertionError("synthetic pull barrier timed out")
                return original(*args, **kwargs)

            def run_pull() -> None:
                try:
                    result.append(
                        pull(
                            vault,
                            hub,
                            session_id=SESSION,
                            completed_at="2026-09-25T20:00:00Z",
                        )
                    )
                except BaseException as exc:  # pragma: no cover - asserted below
                    thread_error.append(exc)

            with patch(
                "artifact_memory.coordination_sync.apply_pull_response",
                side_effect=blocked_apply,
            ):
                worker = threading.Thread(target=run_pull)
                worker.start()
                self.assertTrue(entered.wait(timeout=5))
                with self.assertRaises(SyncFailure) as busy:
                    push(vault, hub, session_id=SESSION)
                self.assertEqual(busy.exception.code, "sync-principal-busy")
                self.assertEqual(pending_path.read_bytes(), before)
                release.set()
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())

            self.assertEqual(thread_error, [])
            self.assertEqual(result[0]["receipt"]["submission_outcomes"], outcomes)
            self.assertFalse(pending_path.exists())

    def test_internal_symlink_cannot_redirect_canonical_storage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vault, outside = root / "vault", root / "outside"
            label = label_for([PROJECT_A])
            task = task_for(label)
            target = claimed_path(vault, task).parent
            target.parent.mkdir(parents=True)
            outside.mkdir()
            os.symlink(outside, target)
            with self.assertRaises(SyncFailure) as raised:
                store_coordination_record(vault, task)
            self.assertEqual(raised.exception.code, "sync-storage-unsafe")
            self.assertEqual(list(outside.iterdir()), [])

    def test_storage_root_symlink_cannot_redirect_writes_or_reads(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside"
            outside.mkdir()
            alias = root / "vault-alias"
            os.symlink(outside, alias)
            label = label_for([PROJECT_A])
            with self.assertRaises(SyncFailure) as write_raised:
                store_coordination_record(alias, task_for(label))
            self.assertEqual(write_raised.exception.code, "sync-storage-unsafe")
            self.assertEqual(list(outside.iterdir()), [])

            real_hub = root / "hub"
            configure(real_hub, label)
            hub_alias = root / "hub-alias"
            os.symlink(real_hub, hub_alias)
            with self.assertRaises(SyncFailure) as read_raised:
                pull(
                    root / "other-vault",
                    hub_alias,
                    session_id=SESSION,
                    completed_at="2026-09-25T20:00:00Z",
                )
            self.assertEqual(read_raised.exception.code, "sync-storage-unsafe")

    def test_continuation_tokens_are_not_persisted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            configure(hub, label)
            store_coordination_record(hub, task_for(label))
            response = build_pull_response(
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T20:00:00Z",
            )
            apply_pull_response(vault, response)
            stored = b"".join(path.read_bytes() for path in vault.rglob("*") if path.is_file())
            self.assertNotIn(b"continuation://", stored)

    def test_cli_acceptance_runs_explicit_push_then_pull(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hub, vault = root / "hub", root / "vault"
            label = label_for([PROJECT_A])
            configure(hub, label)
            store_coordination_record(vault, task_for(label))
            for phase in ("push", "pull"):
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "artifact_memory",
                        "sync",
                        "--vault",
                        str(vault),
                        "--hub",
                        str(hub),
                        "--session-id",
                        SESSION,
                        "--phase",
                        phase,
                        "--completed-at",
                        "2026-09-25T20:00:00Z",
                        "--json",
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
                self.assertEqual(json.loads(completed.stdout)["phase"], phase)
            self.assertEqual(len(load_authorized_projection(vault)), 1)


if __name__ == "__main__":
    unittest.main()
