import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from artifact_memory.cli import main
from artifact_memory.coordination import revision_digest
from artifact_memory.coordination_context import (
    CONTEXT_PACK_SCHEMA_ID,
    build_coordination_context_pack,
    validate_coordination_context_pack,
)
from artifact_memory.coordination_scope_conformance import (
    CONFORMANCE_SCHEMA_ID,
    exercise,
    render_coordination_access_scope_conformance_receipt,
    run,
)
from artifact_memory.coordination_sync import (
    SyncFailure,
    apply_pull_response,
    build_pull_response,
    configure_local_hub,
    pair_set_digest,
    pull,
    sorted_pairs,
    store_coordination_record,
)
from artifact_memory.schema_resources import core_schemas
from artifact_memory.validator import ValidationFailure, load_json, validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "coordination-access-scope" / "v0"
PROJECT_ID = "11111111-1111-4111-8111-111111111111"
PRINCIPAL_ID = "coordination-principal://synthetic/context-cli"
SESSION_ID = "coordination-session://synthetic/context-cli"


def verified_vault(root: Path) -> tuple[Path, Path, dict, dict]:
    hub = root / "hub"
    vault = root / "vault"
    label = load_json(ROOT / "fixtures" / "coordination" / "access-label.json")
    task = load_json(ROOT / "fixtures" / "coordination" / "task-open.json")
    task["accessLabelRef"] = {
        "record_id": label["record_id"],
        "revision_digest": revision_digest(label),
    }
    configure_local_hub(
        hub,
        hub_id="coordination-hub://synthetic/context-cli",
        scope_generation=1,
        bindings=[
            {
                "session_id": SESSION_ID,
                "principal_id": PRINCIPAL_ID,
                "access_label": label,
            }
        ],
    )
    store_coordination_record(hub, task)
    result = pull(
        vault,
        hub,
        session_id=SESSION_ID,
        completed_at="2026-09-27T18:03:00Z",
    )
    return hub, vault, task, result


class CoordinationAccessScopeConformanceTests(unittest.TestCase):
    def test_checked_receipt_proves_scoped_sync_context_and_narrowing(self):
        pack, receipt = exercise(ROOT / "fixtures")
        self.assertEqual(receipt, load_json(FIXTURE / "expected-receipt.json"))
        validate_coordination_context_pack(pack)
        self.assertIn(CONTEXT_PACK_SCHEMA_ID, core_schemas())
        self.assertIn(CONFORMANCE_SCHEMA_ID, core_schemas())
        validate(receipt, core_schemas()[CONFORMANCE_SCHEMA_ID])
        rendered = render_coordination_access_scope_conformance_receipt(receipt)
        self.assertEqual(
            rendered,
            (FIXTURE / "receipt.md").read_text(encoding="utf-8"),
        )
        self.assertFalse(receipt["restricted_sync"]["denied_identity_present"])
        self.assertFalse(receipt["context_pack"]["denied_identity_present"])

    def test_context_pack_validation_binds_records_membership_and_identity(self):
        pack, _ = exercise(ROOT / "fixtures")
        changed = deepcopy(pack)
        changed["records"][0]["title"] = "Changed after export"
        with self.assertRaises(ValidationFailure) as raised:
            validate_coordination_context_pack(changed)
        self.assertEqual(
            raised.exception.code,
            "coordination-context-membership-mismatch",
        )

        changed = deepcopy(pack)
        changed["sync_observation"]["excluded_count"] += 1
        with self.assertRaises(ValidationFailure) as raised:
            validate_coordination_context_pack(changed)
        self.assertEqual(
            raised.exception.code,
            "coordination-context-pack-id-mismatch",
        )

        changed = deepcopy(pack)
        changed["sync_observation"]["transport_state"] = "unauthenticated"
        with self.assertRaises(ValidationFailure) as raised:
            validate_coordination_context_pack(changed)
        self.assertEqual(raised.exception.code, "constraint-failed")

    def test_context_pack_rejects_noninteroperable_integer_fields(self):
        pack, _ = exercise(ROOT / "fixtures")
        paths = (
            ("record_count",),
            ("sync_observation", "scope_generation"),
            ("sync_observation", "authorized_pair_count"),
            ("sync_observation", "excluded_count"),
        )
        for path in paths:
            with self.subTest(path=path):
                changed = deepcopy(pack)
                target = changed
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = 9_007_199_254_740_992
                with self.assertRaises(ValidationFailure) as raised:
                    validate_coordination_context_pack(changed)
                self.assertEqual(raised.exception.code, "constraint-failed")

    def test_cli_returns_structured_rejection_for_noninteroperable_integer(self):
        pack, _ = exercise(ROOT / "fixtures")
        pack["sync_observation"]["excluded_count"] = 9_007_199_254_740_992
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "context-pack.json"
            path.write_text(json.dumps(pack), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(["validate", str(path), "--json"])
        self.assertEqual(exit_code, 2)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["outcome"], "rejected")
        self.assertEqual(result["diagnostics"][0]["code"], "constraint-failed")

    def test_context_builder_supports_multi_page_membership_totals(self):
        pack, _ = exercise(ROOT / "fixtures")
        base = pack["records"][0]
        records = []
        for ordinal in range(1001):
            task = deepcopy(base)
            task_id = "task_" + f"{ordinal:026d}"
            task["taskId"] = task_id
            task["record_id"] = (
                f"record://coordination/{task['originId']}/task/{task_id}"
            )
            task["title"] = f"Synthetic multi-page task {ordinal}"
            records.append(task)
        records.sort(key=lambda record: (record["record_id"], revision_digest(record)))
        pairs = sorted_pairs(
            [
                {
                    "record_id": record["record_id"],
                    "revision_digest": revision_digest(record),
                }
                for record in records
            ]
        )
        observation = pack["sync_observation"]
        snapshot = {
            "receipt": {
                "receipt_id": observation["receipt_id"],
                "completed_at": observation["completed_at"],
                "scope_generation": observation["scope_generation"],
                "access_label_ref": observation["access_label_ref"],
                "authorized_membership": {
                    "pair_count": len(pairs),
                    "pair_set_digest": pair_set_digest(pairs),
                },
                "excluded_count": observation["excluded_count"],
                "transport_state": observation["transport_state"],
                "issuer_state": observation["issuer_state"],
            },
            "records": records,
        }
        @contextlib.contextmanager
        def synthetic_snapshot(_vault):
            yield snapshot

        with patch(
            "artifact_memory.coordination_context.authorized_coordination_snapshot",
            new=synthetic_snapshot,
        ):
            large = build_coordination_context_pack(Path("synthetic-unused-vault"))
        self.assertEqual(large["record_count"], 1001)
        self.assertEqual(large["sync_observation"]["authorized_pair_count"], 1001)

    def test_cli_exports_verified_context_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            _hub, vault, task, sync_result = verified_vault(Path(temporary))
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(
                    [
                        "coordination-context",
                        "--vault",
                        str(vault),
                        "--json",
                    ]
                )
        self.assertEqual(exit_code, 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["record_count"], 1)
        self.assertEqual(result["records"], [task])
        self.assertEqual(
            result["sync_observation"]["receipt_id"],
            sync_result["receipt"]["receipt_id"],
        )
        self.assertEqual(
            result["sync_observation"]["excluded_count"],
            sync_result["receipt"]["excluded_count"],
        )

    def test_cli_holds_scope_stable_through_context_emission(self):
        with tempfile.TemporaryDirectory() as temporary:
            hub, vault, task, _sync_result = verified_vault(Path(temporary))
            narrow = load_json(
                ROOT / "fixtures" / "coordination" / "access-label.json"
            )
            narrow["may"]["readProjects"] = []
            narrow["may"]["syncTaskPackets"] = []
            narrow["may"]["syncWorkReceipts"] = []
            narrow["may"]["postReceipts"] = []
            narrow["mayNot"]["readProjects"] = [
                project["projectId"] for project in narrow["projectNames"]
            ]
            configure_local_hub(
                hub,
                hub_id="coordination-hub://synthetic/context-cli",
                scope_generation=2,
                bindings=[
                    {
                        "session_id": SESSION_ID,
                        "principal_id": PRINCIPAL_ID,
                        "access_label": narrow,
                    }
                ],
            )
            narrowed_response = build_pull_response(
                hub,
                session_id=SESSION_ID,
                completed_at="2026-09-27T18:04:00Z",
            )

            entered = threading.Event()
            release = threading.Event()
            stdout = io.StringIO()
            exit_codes: list[int] = []
            thread_error: list[BaseException] = []
            from artifact_memory import cli as cli_module

            original_receipt = cli_module._receipt

            def blocked_receipt(payload, as_json):
                entered.set()
                if not release.wait(timeout=5):
                    raise AssertionError("synthetic context emission barrier timed out")
                original_receipt(payload, as_json)

            def run_cli() -> None:
                try:
                    with contextlib.redirect_stdout(stdout):
                        exit_codes.append(
                            main(
                                [
                                    "coordination-context",
                                    "--vault",
                                    str(vault),
                                    "--json",
                                ]
                            )
                        )
                except BaseException as exc:  # pragma: no cover - asserted below
                    thread_error.append(exc)

            with patch("artifact_memory.cli._receipt", side_effect=blocked_receipt):
                worker = threading.Thread(target=run_cli)
                worker.start()
                self.assertTrue(entered.wait(timeout=5))
                with self.assertRaises(SyncFailure) as busy:
                    apply_pull_response(vault, narrowed_response)
                self.assertEqual(busy.exception.code, "sync-local-apply-busy")
                release.set()
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())

            self.assertEqual(thread_error, [])
            self.assertEqual(exit_codes, [0])
            broad_pack = json.loads(stdout.getvalue())
            self.assertEqual(broad_pack["record_count"], 1)
            self.assertEqual(broad_pack["records"][0]["record_id"], task["record_id"])

            applied = apply_pull_response(vault, narrowed_response)
            self.assertEqual(applied["outcome"], "complete")
            narrowed_pack = build_coordination_context_pack(vault)
            self.assertEqual(narrowed_pack["record_count"], 0)
            self.assertEqual(narrowed_pack["sync_observation"]["scope_generation"], 2)

    def test_generic_cli_validation_runs_context_pack_semantics(self):
        pack, _ = exercise(ROOT / "fixtures")
        pack["records"][0]["title"] = "Changed after export"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "context-pack.json"
            path.write_text(json.dumps(pack), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(["validate", str(path), "--json"])
        self.assertEqual(exit_code, 2)
        result = json.loads(stdout.getvalue())
        self.assertEqual(
            result["diagnostics"][0]["code"],
            "coordination-context-membership-mismatch",
        )

    def test_generic_cli_cannot_verify_detached_sync_provenance(self):
        pack, _ = exercise(ROOT / "fixtures")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "context-pack.json"
            path.write_text(json.dumps(pack), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(["validate", str(path), "--json"])
        self.assertEqual(exit_code, 2)
        result = json.loads(stdout.getvalue())
        self.assertEqual(
            result["diagnostics"][0]["code"],
            "coordination-context-policy-evidence-required",
        )

    def test_cli_denies_without_a_verified_policy_projection(self):
        with tempfile.TemporaryDirectory() as temporary:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(
                    [
                        "coordination-context",
                        "--vault",
                        str(Path(temporary) / "vault"),
                        "--json",
                    ]
                )
        self.assertEqual(exit_code, 2)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["diagnostics"][0]["code"], "sync-marker-missing")

    def test_check_rejects_receipt_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "fixture"
            shutil.copytree(FIXTURE, fixture)
            receipt = load_json(fixture / "expected-receipt.json")
            receipt["restricted_sync"]["denied_identity_present"] = True
            (fixture / "expected-receipt.json").write_text(
                json.dumps(receipt, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_coordination_access_scope_conformance.py",
                    "--fixture",
                    str(fixture),
                    "--check",
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "coordination access-scope conformance receipt does not match checked evidence",
            completed.stderr,
        )

    def test_script_check_passes(self):
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/run_coordination_access_scope_conformance.py",
                "--check",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            run(ROOT / "fixtures", FIXTURE),
            load_json(FIXTURE / "expected-receipt.json"),
        )


if __name__ == "__main__":
    unittest.main()
