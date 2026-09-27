import json
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from unittest import mock

import artifact_memory.coordination_onboarding as onboarding_module
import artifact_memory.coordination_sync as coordination_sync_module
from artifact_memory.coordination import revision_digest
from artifact_memory.coordination_onboarding import (
    BOOTSTRAP_PACK_SCHEMA_ID,
    BOOTSTRAP_RECEIPT_SCHEMA_ID,
    QUEUE_STATE,
    onboard_project,
    require_repo_onboarding,
    validate_bootstrap_pack,
    validate_bootstrap_receipt,
    validate_repo_bound_append,
)
from artifact_memory.coordination_sync import (
    SyncFailure,
    append_local_coordination_record,
    configure_local_hub,
    describe_local_hub_registration,
    directory_digest,
    pull,
    store_coordination_record,
    sync,
)
from artifact_memory.schema_resources import core_schemas, load_schema
from artifact_memory.validator import ValidationFailure, load_json, validate


ROOT = Path(__file__).resolve().parents[1]
COORDINATION = ROOT / "fixtures" / "coordination"
PROJECT_A = "11111111-1111-4111-8111-111111111111"
PROJECT_B = "22222222-2222-4222-8222-222222222222"
HUB_ID = "coordination-hub://synthetic/onboarding"
SESSION = "coordination-session://synthetic/onboarding"
PRINCIPAL = "coordination-principal://synthetic/onboarding"
COMPLETED_AT = "2026-09-26T20:00:00Z"


class CoordinationOnboardingTests(unittest.TestCase):
    def init_repo(self, root: Path, *, identity: dict | None = None) -> Path:
        root.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(
            ["git", "config", "user.name", "Synthetic Fixture"],
            cwd=root,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "fixture@example.invalid"],
            cwd=root,
            check=True,
        )
        (root / "README.md").write_text("# Synthetic repository\n", encoding="utf-8")
        if identity is not None:
            directory = root / ".agent-memory"
            directory.mkdir()
            (directory / "repo.json").write_text(
                json.dumps(identity, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "Synthetic baseline"],
            cwd=root,
            check=True,
        )
        return root

    def label(self, projects: tuple[str, ...] = (PROJECT_A,)) -> dict:
        label = deepcopy(load_json(COORDINATION / "access-label.json"))
        label["projectNames"] = [
            {"projectId": project_id, "projectName": f"synthetic-{index + 1}"}
            for index, project_id in enumerate(projects)
        ]
        for field in label["may"]:
            label["may"][field] = list(projects)
        label["mayNot"]["readProjects"] = []
        return label

    def configure(self, hub: Path, label: dict) -> None:
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

    def task(self, label: dict) -> dict:
        task = deepcopy(load_json(COORDINATION / "task-open.json"))
        task["projectId"] = PROJECT_A
        task["projectName"] = "synthetic-1"
        task["assignedWriter"] = PRINCIPAL
        task["accessLabelRef"] = {
            "record_id": label["record_id"],
            "revision_digest": revision_digest(label),
        }
        return task

    def claimed_task(self, label: dict) -> tuple[dict, dict]:
        opened = self.task(label)
        claimed = deepcopy(opened)
        claimed["status"] = "claimed"
        claimed["predecessor"] = {
            "record_id": opened["record_id"],
            "revision_digest": revision_digest(opened),
        }
        claimed["claims"] = [
            {
                "claimId": "claim_01J00000000000000000000002",
                "principalId": PRINCIPAL,
                "taskRef": deepcopy(claimed["predecessor"]),
                "claimedAt": "2026-09-26T19:05:00Z",
            }
        ]
        return opened, claimed

    def work_receipt(self, label: dict, claimed: dict) -> dict:
        return {
            "schema_id": "artifact-memory/coordination-work-receipt/v0",
            "record_id": (
                "record://coordination/33333333-3333-4333-8333-333333333333/"
                "receipt/rcpt-01J00000000000000000000001"
            ),
            "originId": "33333333-3333-4333-8333-333333333333",
            "receiptId": "rcpt-01J00000000000000000000001",
            "taskRef": {
                "record_id": claimed["record_id"],
                "revision_digest": revision_digest(claimed),
            },
            "writer": PRINCIPAL,
            "machine": "synthetic-client-a",
            "projectId": PROJECT_A,
            "projectName": "synthetic-1",
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
            "recordedAt": "2026-09-26T19:20:00Z",
            "authority_boundary": (
                "informational only; authority requires independently "
                "authenticated WITS enforcement"
            ),
        }

    def test_fresh_repo_bootstraps_without_storing_full_access_label(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo, vault, hub = root / "repo", root / "vault", root / "hub"
            self.init_repo(repo)
            label = self.label()
            self.configure(hub, label)

            receipt = onboard_project(
                repo,
                vault,
                hub,
                session_id=SESSION,
                completed_at=COMPLETED_AT,
                human_name="synthetic-public",
            )

            identity = load_json(repo / ".agent-memory/repo.json")
            self.assertEqual(identity["uuid"], PROJECT_A)
            self.assertEqual(identity["humanName"], "synthetic-public")
            self.assertEqual(receipt["schema_id"], BOOTSTRAP_RECEIPT_SCHEMA_ID)
            self.assertEqual(receipt["repo_identity_state"], "created-pending-commit")
            self.assertEqual(receipt["vault_state"], "created")
            self.assertEqual(receipt["history_import"]["state"], "deferred-to-am-1")
            validate(receipt, core_schemas()[BOOTSTRAP_RECEIPT_SCHEMA_ID])

            pack_path = (
                vault
                / "generated"
                / "coordination-onboarding"
                / PROJECT_A
                / "bootstrap-kickoff.json"
            )
            pack = load_json(pack_path)
            self.assertEqual(pack["schema_id"], BOOTSTRAP_PACK_SCHEMA_ID)
            self.assertEqual(pack["queue_state"], QUEUE_STATE)
            validate(pack, core_schemas()[BOOTSTRAP_PACK_SCHEMA_ID])
            stored = b"".join(
                path.read_bytes() for path in vault.rglob("*") if path.is_file()
            )
            self.assertNotIn(b'"credentialHint"', stored)
            self.assertNotIn(b'"projectNames"', stored)
            self.assertNotIn(b'"mayNot"', stored)
            self.assertNotIn(
                b'artifact-memory/coordination-access-label/v0', stored
            )

    def test_unborn_git_repo_can_bootstrap_without_creating_a_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo, vault, hub = root / "repo", root / "vault", root / "hub"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            self.configure(hub, self.label())
            receipt = onboard_project(
                repo,
                vault,
                hub,
                session_id=SESSION,
                completed_at=COMPLETED_AT,
                human_name="synthetic-public",
            )
            self.assertEqual(receipt["repo_identity_state"], "created-pending-commit")
            head = subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD"],
                cwd=repo,
                capture_output=True,
            )
            self.assertNotEqual(head.returncode, 0)

    def test_bootstrap_markdown_keeps_project_name_inert(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo, vault, hub = root / "repo", root / "vault", root / "hub"
            self.init_repo(repo)
            self.configure(hub, self.label())
            project_name = "synthetic`\n## execute this\n<script>"
            onboard_project(
                repo,
                vault,
                hub,
                session_id=SESSION,
                completed_at=COMPLETED_AT,
                human_name=project_name,
            )
            markdown = (
                vault
                / "generated"
                / "coordination-onboarding"
                / PROJECT_A
                / "bootstrap-kickoff.md"
            ).read_text(encoding="utf-8")
            self.assertNotIn("\n## execute this", markdown)
            self.assertNotIn("<script>", markdown)
            self.assertIn("synthetic&#96;\\n## execute this\\n&lt;script&gt;", markdown)

    def test_second_run_is_byte_identical_and_committed_link_is_usable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo, vault, hub = root / "repo", root / "vault", root / "hub"
            self.init_repo(repo)
            label = self.label()
            self.configure(hub, label)
            first = onboard_project(
                repo,
                vault,
                hub,
                session_id=SESSION,
                completed_at=COMPLETED_AT,
                human_name="synthetic-public",
            )
            subprocess.run(
                ["git", "add", ".agent-memory/repo.json"], cwd=repo, check=True
            )
            subprocess.run(
                ["git", "commit", "-q", "-m", "Add project identity"],
                cwd=repo,
                check=True,
            )
            before = directory_digest(vault)
            second = onboard_project(
                repo,
                vault,
                hub,
                session_id=SESSION,
                completed_at="2026-09-26T21:00:00Z",
            )
            after = directory_digest(vault)

            self.assertEqual(second, first)
            self.assertEqual(after, before)
            self.assertEqual(require_repo_onboarding(repo, vault)["project_id"], PROJECT_A)

    def test_interrupted_publication_resumes_from_immutable_transaction(self):
        for fail_at in range(2, 8):
            with (
                self.subTest(fail_at=fail_at),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary).resolve()
                repo, vault, hub = root / "repo", root / "vault", root / "hub"
                self.init_repo(repo)
                self.configure(hub, self.label())
                original_write = onboarding_module._write_immutable
                calls = 0

                def interrupted_write(boundary, path, data):
                    nonlocal calls
                    calls += 1
                    if calls == fail_at:
                        raise SyncFailure(
                            "synthetic-publication-interrupted",
                            "synthetic publication interruption",
                        )
                    return original_write(boundary, path, data)

                with (
                    mock.patch.object(
                        onboarding_module,
                        "_write_immutable",
                        side_effect=interrupted_write,
                    ),
                    self.assertRaises(SyncFailure) as interrupted,
                ):
                    onboard_project(
                        repo,
                        vault,
                        hub,
                        session_id=SESSION,
                        completed_at=COMPLETED_AT,
                        human_name="synthetic-public",
                    )
                self.assertEqual(
                    interrupted.exception.code,
                    "synthetic-publication-interrupted",
                )
                publication = (
                    vault
                    / "transactions"
                    / "coordination-onboarding"
                    / f"{PROJECT_A}.json"
                )
                self.assertEqual(publication.is_file(), fail_at > 3)

                receipt = onboard_project(
                    repo,
                    vault,
                    hub,
                    session_id=SESSION,
                    completed_at="2026-09-26T21:00:00Z",
                )
                validate_bootstrap_receipt(receipt)
                subprocess.run(
                    ["git", "add", ".agent-memory/repo.json"],
                    cwd=repo,
                    check=True,
                )
                subprocess.run(
                    ["git", "commit", "-q", "-m", "Add project identity"],
                    cwd=repo,
                    check=True,
                )
                self.assertEqual(
                    require_repo_onboarding(repo, vault)["project_id"],
                    PROJECT_A,
                )

    def test_transaction_write_interruption_reuses_exact_sync_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo, vault, hub = root / "repo", root / "vault", root / "hub"
            self.init_repo(repo)
            label = self.label()
            self.configure(hub, label)
            append_local_coordination_record(vault, self.task(label))
            publication_path = (
                vault
                / "transactions"
                / "coordination-onboarding"
                / f"{PROJECT_A}.json"
            )
            original_write = onboarding_module._write_immutable

            def interrupt_transaction(boundary, path, data):
                if path == publication_path:
                    raise SyncFailure(
                        "synthetic-transaction-interrupted",
                        "synthetic transaction interruption",
                    )
                return original_write(boundary, path, data)

            with (
                mock.patch.object(
                    onboarding_module,
                    "_write_immutable",
                    side_effect=interrupt_transaction,
                ),
                self.assertRaises(SyncFailure) as interrupted,
            ):
                onboard_project(
                    repo,
                    vault,
                    hub,
                    session_id=SESSION,
                    completed_at=COMPLETED_AT,
                    human_name="synthetic-public",
                )
            self.assertEqual(
                interrupted.exception.code,
                "synthetic-transaction-interrupted",
            )
            attempt_path = publication_path.with_name(f"{PROJECT_A}.attempt.json")
            self.assertTrue(attempt_path.is_file())
            self.assertFalse(publication_path.exists())
            marker = load_json(
                vault
                / "generated"
                / "coordination-sync"
                / "last-successful.json"
            )
            receipt_id = marker["receipt_ref"]
            sync_receipt = load_json(
                vault
                / "generated"
                / "coordination-sync"
                / "projections"
                / receipt_id.rsplit("/", 1)[-1]
                / "receipt.json"
            )
            self.assertEqual(
                [
                    outcome["outcome"]
                    for outcome in sync_receipt["submission_outcomes"]
                ],
                ["admitted"],
            )

            later_task = self.task(label)
            later_task_id = "task_" + "2" * 26
            later_task["taskId"] = later_task_id
            later_task["record_id"] = (
                f"record://coordination/{later_task['originId']}/task/"
                f"{later_task_id}"
            )
            store_coordination_record(hub, later_task)
            later = pull(
                vault,
                hub,
                session_id=SESSION,
                completed_at="2026-09-26T21:00:00Z",
            )
            self.assertNotEqual(later["receipt"]["receipt_id"], receipt_id)

            receipt = onboard_project(
                repo,
                vault,
                hub,
                session_id=SESSION,
                completed_at=COMPLETED_AT,
                human_name="synthetic-public",
            )
            self.assertEqual(receipt["sync_receipt_ref"]["receipt_id"], receipt_id)
            self.assertTrue(publication_path.is_file())
            self.assertEqual(
                load_json(
                    vault
                    / "generated"
                    / "coordination-sync"
                    / "last-successful.json"
                )["receipt_ref"],
                later["receipt"]["receipt_id"],
            )

    def test_retry_pulls_pending_outcomes_before_attempting_another_push(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo, vault, hub = root / "repo", root / "vault", root / "hub"
            self.init_repo(repo)
            label = self.label()
            self.configure(hub, label)
            append_local_coordination_record(vault, self.task(label))

            with (
                mock.patch.object(
                    coordination_sync_module,
                    "_pull_bound",
                    side_effect=SyncFailure(
                        "synthetic-before-pull-interruption",
                        "synthetic interruption after push",
                    ),
                ),
                self.assertRaises(SyncFailure) as interrupted,
            ):
                onboard_project(
                    repo,
                    vault,
                    hub,
                    session_id=SESSION,
                    completed_at=COMPLETED_AT,
                    human_name="synthetic-public",
                )
            self.assertEqual(
                interrupted.exception.code,
                "synthetic-before-pull-interruption",
            )
            pending = (
                vault
                / "generated"
                / "coordination-sync"
                / "pending-submission-outcomes.json"
            )
            self.assertTrue(pending.is_file())
            self.assertFalse(
                (vault / "generated" / "coordination-sync" / "last-successful.json").exists()
            )

            receipt = onboard_project(
                repo,
                vault,
                hub,
                session_id=SESSION,
                completed_at=COMPLETED_AT,
                human_name="synthetic-public",
            )
            self.assertFalse(pending.exists())
            sync_receipt_id = receipt["sync_receipt_ref"]["receipt_id"]
            retained = load_json(
                vault
                / "generated"
                / "coordination-sync"
                / "projections"
                / sync_receipt_id.rsplit("/", 1)[-1]
                / "receipt.json"
            )
            self.assertEqual(
                [item["outcome"] for item in retained["submission_outcomes"]],
                ["admitted"],
            )

    def test_recovery_consumes_matching_pending_outcomes_after_marker_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo, vault, hub = root / "repo", root / "vault", root / "hub"
            self.init_repo(repo)
            label = self.label()
            self.configure(hub, label)
            append_local_coordination_record(vault, self.task(label))

            with (
                mock.patch.object(
                    coordination_sync_module,
                    "_consume_pending_outcomes",
                    side_effect=SyncFailure(
                        "synthetic-after-marker-interruption",
                        "synthetic interruption before pending consumption",
                    ),
                ),
                self.assertRaises(SyncFailure) as interrupted,
            ):
                onboard_project(
                    repo,
                    vault,
                    hub,
                    session_id=SESSION,
                    completed_at=COMPLETED_AT,
                    human_name="synthetic-public",
                )
            self.assertEqual(
                interrupted.exception.code,
                "synthetic-after-marker-interruption",
            )
            pending = (
                vault
                / "generated"
                / "coordination-sync"
                / "pending-submission-outcomes.json"
            )
            self.assertTrue(pending.is_file())
            self.assertTrue(
                (vault / "generated" / "coordination-sync" / "last-successful.json").is_file()
            )

            receipt = onboard_project(
                repo,
                vault,
                hub,
                session_id=SESSION,
                completed_at=COMPLETED_AT,
                human_name="synthetic-public",
            )
            self.assertFalse(pending.exists())
            self.assertEqual(
                sync(
                    vault,
                    hub,
                    session_id=SESSION,
                    completed_at="2026-09-26T21:00:00Z",
                )["outcome"],
                "no-op",
            )
            validate_bootstrap_receipt(receipt)

    def test_rejected_sync_is_archived_and_a_fresh_attempt_can_succeed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo, vault, hub = root / "repo", root / "vault", root / "hub"
            self.init_repo(repo)
            label = self.label()
            self.configure(hub, label)
            opened, claimed = self.claimed_task(label)
            append_local_coordination_record(
                vault,
                self.work_receipt(label, claimed),
            )

            with self.assertRaises(ValidationFailure) as rejected:
                onboard_project(
                    repo,
                    vault,
                    hub,
                    session_id=SESSION,
                    completed_at=COMPLETED_AT,
                    human_name="synthetic-public",
                )
            self.assertEqual(
                rejected.exception.code,
                "onboard-sync-submission-rejected",
            )
            transaction_root = vault / "transactions" / "coordination-onboarding"
            self.assertFalse((transaction_root / f"{PROJECT_A}.attempt.json").exists())
            self.assertFalse((transaction_root / f"{PROJECT_A}.sync.json").exists())
            failed_attempts = list((transaction_root / "failed" / PROJECT_A).iterdir())
            self.assertEqual(len(failed_attempts), 1)
            archived_attempt = load_json(failed_attempts[0] / "attempt.json")
            archived_checkpoint = load_json(failed_attempts[0] / "sync.json")
            self.assertEqual(
                archived_checkpoint["attempt_ref"],
                archived_attempt["attempt_id"],
            )
            self.assertEqual(
                [
                    item["outcome"]
                    for item in archived_checkpoint["sync_response"]["receipt"][
                        "submission_outcomes"
                    ]
                ],
                ["rejected"],
            )

            store_coordination_record(hub, opened)
            store_coordination_record(hub, claimed)
            receipt = onboard_project(
                repo,
                vault,
                hub,
                session_id=SESSION,
                completed_at="2026-09-26T21:00:00Z",
                human_name="synthetic-public",
            )
            validate_bootstrap_receipt(receipt)
            self.assertNotEqual(
                load_json(transaction_root / f"{PROJECT_A}.attempt.json")[
                    "attempt_id"
                ],
                archived_attempt["attempt_id"],
            )
            self.assertTrue((failed_attempts[0] / "sync.json").is_file())

    def test_retry_finishes_an_interrupted_failed_attempt_retirement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo, vault, hub = root / "repo", root / "vault", root / "hub"
            self.init_repo(repo)
            label = self.label()
            self.configure(hub, label)
            opened, claimed = self.claimed_task(label)
            append_local_coordination_record(
                vault,
                self.work_receipt(label, claimed),
            )

            with (
                mock.patch.object(
                    onboarding_module,
                    "_remove_exact_active_evidence",
                    side_effect=ValidationFailure(
                        "synthetic-retirement-interruption",
                        "synthetic interruption after archive publication",
                    ),
                ),
                self.assertRaises(ValidationFailure) as interrupted,
            ):
                onboard_project(
                    repo,
                    vault,
                    hub,
                    session_id=SESSION,
                    completed_at=COMPLETED_AT,
                    human_name="synthetic-public",
                )
            self.assertEqual(
                interrupted.exception.code,
                "synthetic-retirement-interruption",
            )
            transaction_root = vault / "transactions" / "coordination-onboarding"
            self.assertTrue((transaction_root / f"{PROJECT_A}.attempt.json").is_file())
            self.assertTrue((transaction_root / f"{PROJECT_A}.sync.json").is_file())

            store_coordination_record(hub, opened)
            store_coordination_record(hub, claimed)
            receipt = onboard_project(
                repo,
                vault,
                hub,
                session_id=SESSION,
                completed_at="2026-09-26T21:00:00Z",
                human_name="synthetic-public",
            )
            validate_bootstrap_receipt(receipt)
            failed_attempts = list((transaction_root / "failed" / PROJECT_A).iterdir())
            self.assertEqual(len(failed_attempts), 1)
            self.assertTrue((failed_attempts[0] / "attempt.json").is_file())
            self.assertTrue((failed_attempts[0] / "sync.json").is_file())

    def test_concurrent_onboarding_serializes_and_replays_first_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo, vault, hub = root / "repo", root / "vault", root / "hub"
            self.init_repo(repo)
            self.configure(hub, self.label())
            entered_sync = threading.Event()
            release_sync = threading.Event()
            count_guard = threading.Lock()
            sync_calls = 0
            original_sync = onboarding_module.sync

            def delayed_sync(*args, **kwargs):
                nonlocal sync_calls
                with count_guard:
                    sync_calls += 1
                    first = sync_calls == 1
                if first:
                    entered_sync.set()
                    if not release_sync.wait(timeout=10):
                        raise RuntimeError("synthetic onboarding lock test timed out")
                return original_sync(*args, **kwargs)

            with mock.patch.object(
                onboarding_module, "sync", side_effect=delayed_sync
            ):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    first = executor.submit(
                        onboard_project,
                        repo,
                        vault,
                        hub,
                        session_id=SESSION,
                        completed_at=COMPLETED_AT,
                        human_name="synthetic-public",
                    )
                    self.assertTrue(entered_sync.wait(timeout=10))
                    second = executor.submit(
                        onboard_project,
                        repo,
                        vault,
                        hub,
                        session_id=SESSION,
                        completed_at="2026-09-26T21:00:00Z",
                        human_name="synthetic-public",
                    )
                    self.assertFalse(second.done())
                    release_sync.set()
                    first_receipt = first.result(timeout=10)
                    second_receipt = second.result(timeout=10)
            self.assertEqual(sync_calls, 1)
            self.assertEqual(second_receipt, first_receipt)

    def test_project_link_alone_does_not_satisfy_onboarding_precondition(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo, vault, hub = root / "repo", root / "vault", root / "hub"
            self.init_repo(repo)
            self.configure(hub, self.label())
            onboard_project(
                repo,
                vault,
                hub,
                session_id=SESSION,
                completed_at=COMPLETED_AT,
                human_name="synthetic-public",
            )
            subprocess.run(
                ["git", "add", ".agent-memory/repo.json"], cwd=repo, check=True
            )
            subprocess.run(
                ["git", "commit", "-q", "-m", "Add project identity"],
                cwd=repo,
                check=True,
            )
            (vault / "receipts" / "coordination-onboarding" / f"{PROJECT_A}.json").unlink()
            bootstrap = (
                vault / "generated" / "coordination-onboarding" / PROJECT_A
            )
            (bootstrap / "bootstrap-kickoff.json").unlink()
            (bootstrap / "bootstrap-kickoff.md").unlink()

            with self.assertRaises(ValidationFailure) as caught:
                require_repo_onboarding(repo, vault)
            self.assertEqual(caught.exception.code, "onboard-state-incomplete")

    def test_persisted_project_link_rejects_missing_and_unknown_fields(self):
        required = (
            "schema_id",
            "project_id",
            "project_name",
            "hub_id",
            "access_label_ref",
            "authority_boundary",
        )
        for field in (*required, "unknown"):
            with (
                self.subTest(field=field),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary).resolve()
                repo, vault, hub = root / "repo", root / "vault", root / "hub"
                self.init_repo(repo)
                self.configure(hub, self.label())
                onboard_project(
                    repo,
                    vault,
                    hub,
                    session_id=SESSION,
                    completed_at=COMPLETED_AT,
                    human_name="synthetic-public",
                )
                subprocess.run(
                    ["git", "add", ".agent-memory/repo.json"],
                    cwd=repo,
                    check=True,
                )
                subprocess.run(
                    ["git", "commit", "-q", "-m", "Add project identity"],
                    cwd=repo,
                    check=True,
                )
                link_path = (
                    vault
                    / "config"
                    / "coordination"
                    / "projects"
                    / f"{PROJECT_A}.json"
                )
                link = load_json(link_path)
                if field == "unknown":
                    link["unexpected"] = "synthetic"
                    expected_code = "unknown-field"
                else:
                    del link[field]
                    expected_code = "required-field-missing"
                link_path.write_text(
                    json.dumps(link, sort_keys=True, separators=(",", ":")),
                    encoding="utf-8",
                )

                with self.assertRaises(ValidationFailure) as caught:
                    require_repo_onboarding(repo, vault)
                self.assertEqual(caught.exception.code, expected_code)

    def test_existing_repo_and_prior_pair_are_not_duplicated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo, vault, hub = root / "repo", root / "vault", root / "hub"
            self.init_repo(repo)
            label = self.label()
            self.configure(hub, label)
            store_coordination_record(vault, self.task(label))
            source_note = repo / "synthetic-done-log.md"
            source_note.write_text("2026-09-26 synthetic prior work\n", encoding="utf-8")
            before_source = source_note.read_bytes()

            receipt = onboard_project(
                repo,
                vault,
                hub,
                session_id=SESSION,
                completed_at=COMPLETED_AT,
                human_name="synthetic-public",
            )

            self.assertEqual(receipt["record_state"]["pair_count_before"], 1)
            self.assertEqual(receipt["record_state"]["pair_count_after"], 1)
            self.assertEqual(receipt["record_state"]["duplicate_pair_count"], 0)
            self.assertEqual(source_note.read_bytes(), before_source)
            self.assertEqual(receipt["history_import"]["records_imported"], 0)

    def test_unonboarded_repo_bound_sync_fails_typed_and_names_onboard(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo, vault, hub = root / "repo", root / "vault", root / "hub"
            identity = {"uuid": PROJECT_A, "humanName": "synthetic-1"}
            self.init_repo(repo, identity=identity)
            self.configure(hub, self.label())
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "artifact_memory",
                    "sync",
                    "--repo",
                    str(repo),
                    "--vault",
                    str(vault),
                    "--hub",
                    str(hub),
                    "--session-id",
                    SESSION,
                    "--completed-at",
                    COMPLETED_AT,
                    "--json",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            payload = json.loads(completed.stdout)
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(
                payload["diagnostics"][0]["code"],
                "coordination-onboarding-required",
            )
            self.assertIn("artifact-memory onboard", payload["diagnostics"][0]["message"])
            append = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "artifact_memory",
                    "record",
                    "append",
                    str(COORDINATION / "task-open.json"),
                    "--repo",
                    str(repo),
                    "--vault",
                    str(vault),
                    "--json",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            append_payload = json.loads(append.stdout)
            self.assertEqual(append.returncode, 2)
            self.assertEqual(
                append_payload["diagnostics"][0]["code"],
                "coordination-onboarding-required",
            )
            self.assertIn(
                "artifact-memory onboard",
                append_payload["diagnostics"][0]["message"],
            )

    def test_multiple_authorized_projects_require_explicit_project_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo, vault, hub = root / "repo", root / "vault", root / "hub"
            self.init_repo(repo)
            self.configure(hub, self.label((PROJECT_A, PROJECT_B)))
            with self.assertRaises(ValidationFailure) as caught:
                onboard_project(
                    repo,
                    vault,
                    hub,
                    session_id=SESSION,
                    completed_at=COMPLETED_AT,
                )
            self.assertEqual(caught.exception.code, "onboard-project-ambiguous")
            self.assertFalse((repo / ".agent-memory/repo.json").exists())

    def test_new_public_manifest_requires_explicit_human_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo, vault, hub = root / "repo", root / "vault", root / "hub"
            self.init_repo(repo)
            self.configure(hub, self.label())
            with self.assertRaises(ValidationFailure) as caught:
                onboard_project(
                    repo,
                    vault,
                    hub,
                    session_id=SESSION,
                    completed_at=COMPLETED_AT,
                )
            self.assertEqual(caught.exception.code, "onboard-human-name-required")
            self.assertFalse((repo / ".agent-memory/repo.json").exists())

    def test_registration_description_never_exposes_denied_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            hub = root / "hub"
            label = self.label((PROJECT_A, PROJECT_B))
            label["may"]["readProjects"] = [PROJECT_A]
            label["mayNot"]["readProjects"] = [PROJECT_B]
            self.configure(hub, label)
            registration = describe_local_hub_registration(
                hub, session_id=SESSION
            )
            self.assertEqual(
                registration["projects"],
                [{"project_id": PROJECT_A, "project_name": "synthetic-1"}],
            )
            self.assertNotIn(PROJECT_B, json.dumps(registration))

    def test_binding_rotation_fails_before_first_sync_mutates_the_vault(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo, vault, hub = root / "repo", root / "vault", root / "hub"
            self.init_repo(repo)
            original_label = self.label()
            self.configure(hub, original_label)
            original_registration = describe_local_hub_registration(
                hub, session_id=SESSION
            )
            rotated_label = self.label()
            rotated_label["labelId"] = "rotated-label"
            rotated_label["record_id"] = (
                "record://coordination/33333333-3333-4333-8333-333333333333/"
                "label/rotated-label"
            )
            self.configure(hub, rotated_label)

            with (
                mock.patch(
                    "artifact_memory.coordination_onboarding."
                    "describe_local_hub_registration",
                    return_value=original_registration,
                ),
                self.assertRaises(SyncFailure) as caught,
            ):
                onboard_project(
                    repo,
                    vault,
                    hub,
                    session_id=SESSION,
                    completed_at=COMPLETED_AT,
                    human_name="synthetic-public",
                )
            self.assertEqual(caught.exception.code, "onboard-label-mismatch")
            self.assertFalse((vault / "canonical").exists())
            self.assertFalse((vault / "generated").exists())
            self.assertFalse((vault / "transactions").exists())

    def test_bootstrap_identity_tampering_fails_semantic_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo, vault, hub = root / "repo", root / "vault", root / "hub"
            self.init_repo(repo)
            self.configure(hub, self.label())
            receipt = onboard_project(
                repo,
                vault,
                hub,
                session_id=SESSION,
                completed_at=COMPLETED_AT,
                human_name="synthetic-public",
            )
            pack = load_json(
                vault
                / "generated"
                / "coordination-onboarding"
                / PROJECT_A
                / "bootstrap-kickoff.json"
            )
            receipt["record_state"]["pair_count_after"] += 1
            pack["sync_observation"]["project_record_count"] += 1
            with self.assertRaises(ValidationFailure) as receipt_error:
                validate_bootstrap_receipt(receipt)
            with self.assertRaises(ValidationFailure) as pack_error:
                validate_bootstrap_pack(pack)
            self.assertEqual(
                receipt_error.exception.code, "onboard-receipt-id-mismatch"
            )
            self.assertEqual(pack_error.exception.code, "onboard-pack-id-mismatch")

    def test_repo_bound_append_rejects_project_label_and_label_bodies(self):
        label = self.label()
        link = {
            "project_id": PROJECT_A,
            "access_label_ref": {
                "record_id": label["record_id"],
                "revision_digest": revision_digest(label),
            },
        }
        wrong_project = self.task(label)
        wrong_project["projectId"] = PROJECT_B
        wrong_label = self.task(label)
        wrong_label["accessLabelRef"]["revision_digest"] = "sha-256:" + "0" * 64
        with self.assertRaises(ValidationFailure) as project_error:
            validate_repo_bound_append(link, wrong_project)
        with self.assertRaises(ValidationFailure) as label_error:
            validate_repo_bound_append(link, wrong_label)
        with self.assertRaises(ValidationFailure) as body_error:
            validate_repo_bound_append(link, label)
        self.assertEqual(project_error.exception.code, "onboard-project-mismatch")
        self.assertEqual(label_error.exception.code, "onboard-label-mismatch")
        self.assertEqual(
            body_error.exception.code, "coordination-record-type-unauthorized"
        )

    def test_repo_bound_sync_rejects_different_logical_hub(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo, vault = root / "repo", root / "vault"
            first_hub, second_hub = root / "hub-a", root / "hub-b"
            self.init_repo(repo)
            label = self.label()
            self.configure(first_hub, label)
            onboard_project(
                repo,
                vault,
                first_hub,
                session_id=SESSION,
                completed_at=COMPLETED_AT,
                human_name="synthetic-public",
            )
            subprocess.run(
                ["git", "add", ".agent-memory/repo.json"], cwd=repo, check=True
            )
            subprocess.run(
                ["git", "commit", "-q", "-m", "Add project identity"],
                cwd=repo,
                check=True,
            )
            configure_local_hub(
                second_hub,
                hub_id="coordination-hub://synthetic/other",
                scope_generation=1,
                bindings=[
                    {
                        "session_id": SESSION,
                        "principal_id": PRINCIPAL,
                        "access_label": label,
                    }
                ],
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "artifact_memory",
                    "sync",
                    "--repo",
                    str(repo),
                    "--vault",
                    str(vault),
                    "--hub",
                    str(second_hub),
                    "--session-id",
                    SESSION,
                    "--completed-at",
                    "2026-09-26T21:00:00Z",
                    "--json",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(
                json.loads(completed.stdout)["diagnostics"][0]["code"],
                "onboard-hub-mismatch",
            )

    def test_project_link_schema_is_packaged(self):
        schema = load_schema("coordination", "project-link.v0.schema.json")
        self.assertEqual(
            schema["properties"]["schema_id"]["const"],
            "artifact-memory/local-coordination-project-link/v0",
        )
        publication = load_schema(
            "coordination", "onboarding-publication.v0.schema.json"
        )
        self.assertEqual(
            publication["properties"]["schema_id"]["const"],
            "artifact-memory/local-coordination-onboarding-publication/v0",
        )
        attempt = load_schema(
            "coordination", "onboarding-attempt.v0.schema.json"
        )
        self.assertEqual(
            attempt["properties"]["schema_id"]["const"],
            "artifact-memory/local-coordination-onboarding-attempt/v0",
        )
        checkpoint = load_schema(
            "coordination", "onboarding-sync-checkpoint.v0.schema.json"
        )
        self.assertEqual(
            checkpoint["properties"]["schema_id"]["const"],
            "artifact-memory/local-coordination-onboarding-sync-checkpoint/v0",
        )


if __name__ == "__main__":
    unittest.main()
