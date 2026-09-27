import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from artifact_memory.coordination_sync import _read_local_regular_file
from artifact_memory.schema_resources import core_schemas
from artifact_memory.session_ledger import (
    CONFORMANCE_SCHEMA_ID,
    exercise_session_ledger_fixture,
    import_session_ledger,
    render_session_ledger_conformance_receipt,
)
from artifact_memory.validator import ValidationFailure, load_json, validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "session-ledger" / "v0"


class SessionLedgerTests(unittest.TestCase):
    def test_checked_synthetic_receipt_matches_evidence(self):
        receipt = exercise_session_ledger_fixture(FIXTURE)
        self.assertEqual(receipt, load_json(FIXTURE / "expected-receipt.json"))
        self.assertIn(CONFORMANCE_SCHEMA_ID, core_schemas())
        validate(receipt, core_schemas()[CONFORMANCE_SCHEMA_ID])
        self.assertEqual(
            render_session_ledger_conformance_receipt(receipt),
            (FIXTURE / "receipt.md").read_text(encoding="utf-8"),
        )

    def test_cli_dry_run_writes_nothing_then_apply_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            base = [
                sys.executable,
                "-m",
                "artifact_memory",
                "import-session-ledger",
                str(FIXTURE / "synthetic-done-log.md"),
                "--vault",
                str(vault),
                "--json",
            ]
            dry = subprocess.run(
                [*base, "--dry-run"],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(dry.returncode, 0, dry.stderr)
            dry_payload = json.loads(dry.stdout)
            self.assertEqual(dry_payload["mode"], "dry-run")
            self.assertEqual(dry_payload["source_entry_count"], 2)
            self.assertFalse(vault.exists())
            self.assertNotIn("Verified synthetic", dry.stdout)
            self.assertNotIn(str(FIXTURE), dry.stdout)

            written = subprocess.run(base, cwd=ROOT, text=True, capture_output=True)
            replay = subprocess.run(base, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(written.returncode, 0, written.stderr)
            self.assertEqual(replay.returncode, 0, replay.stderr)
            self.assertEqual(json.loads(written.stdout)["created_record_count"], 2)
            self.assertEqual(json.loads(replay.stdout)["created_record_count"], 0)
            self.assertEqual(json.loads(replay.stdout)["existing_record_count"], 2)
            paths = sorted((vault / "records" / "session-ledger").glob("*.json"))
            self.assertEqual(len(paths), 2)
            for path in paths:
                record = load_json(path)
                self.assertEqual(
                    record["provenance"],
                    [{"kind": "import", "source_ref": "session-ledger"}],
                )
                self.assertEqual(record["lifecycle"], "draft")
                self.assertEqual(record["sensitivity"], "private")

    def test_rejects_undated_content_and_invalid_calendar_date(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vault = root / "vault"
            for content, code in (
                ("not a dated entry\n", "session-ledger-entry-invalid"),
                ("2026-02-30 impossible date\n", "session-ledger-date-invalid"),
            ):
                source = root / f"{code}.md"
                source.write_text(content, encoding="utf-8")
                with self.subTest(code=code), self.assertRaises(ValidationFailure) as caught:
                    import_session_ledger(source, vault, dry_run=True)
                self.assertEqual(caught.exception.code, code)
            self.assertFalse(vault.exists())

    def test_rejects_credential_like_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            synthetic_value = "synthetic-value"
            cases = (
                "pass" + "word" + "=" + synthetic_value,
                "api" + " key" + ": " + synthetic_value,
                "client" + "_secret" + "=" + synthetic_value,
                "aws" + "_secret_access_key" + "=" + synthetic_value,
                "github" + "_token" + "=" + synthetic_value,
                "session=" + "g" + "hs_" + "syntheticvalue1234",
            )
            for index, fragment in enumerate(cases):
                source = root / f"synthetic-sensitive-{index}.md"
                source.write_text(
                    f"2026-09-27 {fragment}\n",
                    encoding="utf-8",
                )
                with self.subTest(fragment=index), self.assertRaises(
                    ValidationFailure
                ) as caught:
                    import_session_ledger(source, root / "vault", dry_run=True)
                self.assertEqual(
                    caught.exception.code,
                    "session-ledger-sensitive-content",
                )
            self.assertFalse((root / "vault").exists())

    def test_source_reader_stops_after_configured_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "bounded.md"
            source.write_bytes(b"x" * 64)
            observed = _read_local_regular_file(
                root,
                source,
                missing_code="missing",
                missing_message="missing",
                maximum_bytes=8,
            )
            self.assertEqual(observed, b"x" * 9)

    def test_immutable_record_collision_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = FIXTURE / "synthetic-done-log.md"
            vault = root / "vault"
            mapping = import_session_ledger(source, vault, dry_run=True)["mapping"]
            first_digest = mapping[0]["record_id"].rsplit("/", 1)[-1]
            collision_digest = mapping[1]["record_id"].rsplit("/", 1)[-1]
            first_target = (
                vault / "records" / "session-ledger" / f"{first_digest}.json"
            )
            target = (
                vault
                / "records"
                / "session-ledger"
                / f"{collision_digest}.json"
            )
            target.parent.mkdir(parents=True)
            target.write_text("{}\n", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "artifact_memory",
                    "import-session-ledger",
                    str(source),
                    "--vault",
                    str(vault),
                    "--json",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(
                json.loads(completed.stdout)["diagnostics"][0]["code"],
                "immutable-record-collision",
            )
            self.assertFalse(first_target.exists())

    def test_concurrent_first_imports_serialize_without_loss(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vault = root / "vault"
            command = [
                sys.executable,
                "-m",
                "artifact_memory",
                "import-session-ledger",
                str(FIXTURE / "synthetic-done-log.md"),
                "--vault",
                str(vault),
                "--json",
            ]
            processes = [
                subprocess.Popen(
                    command,
                    cwd=ROOT,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                for _ in range(2)
            ]
            results = [process.communicate(timeout=30) for process in processes]
            for process, (_, stderr) in zip(processes, results):
                self.assertEqual(process.returncode, 0, stderr)
            payloads = [json.loads(stdout) for stdout, _ in results]
            self.assertEqual(
                sorted(
                    (item["created_record_count"], item["existing_record_count"])
                    for item in payloads
                ),
                [(0, 2), (2, 0)],
            )
            self.assertEqual(
                len(list((vault / "records" / "session-ledger").glob("*.json"))),
                2,
            )

    @unittest.skipUnless(os.name == "nt", "Windows junction proof runs on Windows")
    def test_windows_junction_vault_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            junction = root / "junction"
            target.mkdir()
            linked = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(linked.returncode, 0, linked.stderr or linked.stdout)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "artifact_memory",
                    "import-session-ledger",
                    str(FIXTURE / "synthetic-done-log.md"),
                    "--vault",
                    str(junction),
                    "--json",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(
                json.loads(completed.stdout)["diagnostics"][0]["code"],
                "sync-storage-unsafe",
            )
            self.assertFalse((target / "records").exists())

    def test_conformance_script_passes(self):
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/run_session_ledger_conformance.py",
                "--check",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
