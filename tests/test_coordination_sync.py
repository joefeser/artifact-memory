import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
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


def task_for(label: dict, *, other_origin: bool = False, project_id: str = PROJECT_A) -> dict:
    task = fixture("same-human-id-other-origin.json" if other_origin else "task-open.json")
    task["projectId"] = project_id
    task["projectName"] = "sample-analytics" if project_id == PROJECT_B else "sample-service"
    task["accessLabelRef"] = {
        "record_id": label["record_id"],
        "revision_digest": revision_digest(label),
    }
    return task


def claimed_task_for(label: dict) -> tuple[dict, dict]:
    opened = task_for(label)
    claimed = copy.deepcopy(opened)
    claimed["assignedWriter"] = PRINCIPAL
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

            # Replaying alternate formatting for the same canonical pair is a
            # duplicate admission, never a same-pair collision.
            path.write_text(json.dumps(task, indent=4), encoding="utf-8")
            second = push(vault, hub, session_id=SESSION)
            self.assertEqual(second[0]["code"], "admitted")
            self.assertEqual(list((hub / "quarantine").glob("**/*.json")), [])

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
            narrow = label_for([PROJECT_A])
            configure(hub, narrow, generation=2)
            pull(vault, hub, session_id=SESSION, completed_at="2026-09-25T21:00:00Z")
            generation_two = marker_path.read_bytes()
            configure(hub, broad, generation=1)
            stale = build_pull_response(
                hub,
                session_id=SESSION,
                completed_at="2026-09-25T22:00:00Z",
            )
            with self.assertRaises(SyncFailure) as replayed:
                apply_pull_response(vault, stale)
            self.assertEqual(replayed.exception.code, "sync-generation-stale")
            self.assertEqual(marker_path.read_bytes(), generation_two)

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

    def test_pending_outcomes_are_bound_to_the_authenticated_session(self):
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
