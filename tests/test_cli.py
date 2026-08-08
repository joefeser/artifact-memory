import copy
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from artifact_memory.scan import ScanLimits, make_scan_policy, scan_path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "synthetic" / "contracts"
RELEASE_FIXTURES = ROOT / "fixtures" / "synthetic" / "release"
ARCHIVE_FIXTURES = ROOT / "fixtures" / "synthetic" / "archives" / "v1"


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "artifact_memory", *args], cwd=ROOT, text=True, capture_output=True)

    def test_version_json(self):
        result = self.run_cli("version", "--json")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["contract_version"], "v0")

    def test_valid_record(self):
        result = self.run_cli("validate", str(FIXTURES / "v0-valid-record.json"), "--json")
        self.assertEqual(result.returncode, 0)
        self.assertTrue(json.loads(result.stdout)["valid"])

    def test_archive_receipt_requires_semantic_validation(self):
        from artifact_memory.archive import inspect_zip

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "synthetic.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("record.txt", b"synthetic\n")
            receipt = inspect_zip(archive_path)
            receipt["entries"][0]["content_digest"] = "sha-256:" + "0" * 64
            receipt_path = root / "receipt.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            result = self.run_cli("validate", str(receipt_path), "--json")
            human_result = self.run_cli("validate", str(receipt_path))

        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            result.stdout,
            (ARCHIVE_FIXTURES / "cli-semantic-rejection.json").read_text(encoding="utf-8"),
        )
        self.assertEqual(human_result.returncode, 2)
        self.assertEqual(
            human_result.stdout,
            (ARCHIVE_FIXTURES / "cli-semantic-rejection.txt").read_text(encoding="utf-8"),
        )

    def test_absolute_path_rejected(self):
        result = self.run_cli("validate", str(FIXTURES / "v0-invalid-absolute-path.json"), "--json")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(json.loads(result.stdout)["valid"])

    def test_release_manifest_validation_applies_semantic_migration_gate(self):
        fixture = RELEASE_FIXTURES / "v0-preview-manifest.v2.json"
        manifest = copy.deepcopy(json.loads(fixture.read_text(encoding="utf-8")))
        manifest["status"] = "release"
        manifest["release_id"] = "artifact-memory/v0.1.0"
        manifest["signature"] = {
            "state": "owner-signed",
            "tag": "v0.1.0",
            "algorithm": "ssh-ed25519",
            "public_key_fingerprint": "SHA256:" + "A" * 20 + "==",
            "key_generation": "legacy-generation",
            "owner_signed_annotated_tag": True,
        }
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = Path(temporary) / "release-manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_cli("validate", str(manifest_path), "--json")
            human_result = self.run_cli("validate", str(manifest_path))

        self.assertEqual(result.returncode, 2)
        receipt = json.loads(result.stdout)
        self.assertFalse(receipt["valid"])
        self.assertEqual(
            receipt["diagnostics"][0]["code"],
            "release-fingerprint-migration-required",
        )
        self.assertEqual(human_result.returncode, 2)
        self.assertEqual(
            human_result.stdout,
            (RELEASE_FIXTURES / "v0-legacy-release-validation-receipt.txt").read_text(
                encoding="utf-8"
            ),
        )

    def test_validate_help_describes_semantic_release_rules(self):
        result = self.run_cli("validate", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("semantic rules", result.stdout)
        self.assertIn("release-manifest releasability", result.stdout)

    def test_pending_candidate_validation_is_explicitly_non_authenticating(self):
        fixture = RELEASE_FIXTURES / "v0-pending-candidate-manifest.v2.json"
        result = self.run_cli("validate", str(fixture), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertTrue(receipt["valid"])
        self.assertEqual(receipt["outcome"], "accepted")
        self.assertEqual(receipt["lifecycle_status"], "release-candidate")
        self.assertEqual(receipt["signature_state"], "pending-owner-signature")
        self.assertEqual(
            receipt["validation_scope"],
            "schema-and-semantic-rules-only",
        )
        self.assertFalse(receipt["owner_signature_verified"])
        self.assertFalse(receipt["release_evidence_accepted"])

    def test_validate_rejects_v1_release_claim_that_requires_migration(self):
        fixture = RELEASE_FIXTURES / "v0-preview-manifest.json"
        manifest = json.loads(fixture.read_text(encoding="utf-8"))
        manifest["status"] = "release"
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = Path(temporary) / "release-manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_cli("validate", str(manifest_path), "--json")

        self.assertEqual(result.returncode, 2)
        receipt = json.loads(result.stdout)
        self.assertEqual(
            receipt["diagnostics"][0]["code"],
            "release-manifest-migration-required",
        )

    def test_inspect_does_not_echo_path(self):
        result = self.run_cli("inspect", str(FIXTURES / "v0-valid-record.json"), "--json")
        self.assertEqual(result.returncode, 0)
        self.assertNotIn(str(ROOT), result.stdout)

    def test_diff_rejects_tampered_manifest_and_marks_partial_input_nonzero(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "value.txt").write_text("synthetic", encoding="utf-8")
            complete, _ = scan_path(source)
            partial, _ = scan_path(source, ScanLimits(max_bytes=0))
            complete_path = root / "complete.json"
            partial_path = root / "partial.json"
            tampered_path = root / "tampered.json"
            complete_path.write_text(json.dumps(complete), encoding="utf-8")
            partial_path.write_text(json.dumps(partial), encoding="utf-8")
            tampered = json.loads(json.dumps(complete))
            tampered["tree_digest"] = "sha-256:" + "0" * 64
            tampered_path.write_text(json.dumps(tampered), encoding="utf-8")

            rejected = self.run_cli("diff", str(complete_path), str(tampered_path), "--json")
            self.assertEqual(rejected.returncode, 2)
            self.assertEqual(json.loads(rejected.stdout)["outcome"], "rejected")
            incomplete = self.run_cli("diff", str(partial_path), str(complete_path), "--json")
            self.assertEqual(incomplete.returncode, 2)
            self.assertEqual(json.loads(incomplete.stdout)["outcome"], "partial")

    def test_verify_requires_and_accepts_exact_custom_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "value.txt").write_text("synthetic", encoding="utf-8")
            policy = make_scan_policy(endpoint_ref="endpoint://synthetic/custom", root_relative_path="records")
            manifest, _ = scan_path(source, policy=policy)
            manifest_path = root / "manifest.json"
            policy_path = root / "policy.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            policy_path.write_text(json.dumps(policy), encoding="utf-8")

            missing = self.run_cli("verify", str(source), str(manifest_path), "--json")
            self.assertEqual(missing.returncode, 3)
            self.assertEqual(json.loads(missing.stdout)["outcome"], "policy-required")
            supplied = self.run_cli("verify", str(source), str(manifest_path), "--policy", str(policy_path), "--json")
            self.assertEqual(supplied.returncode, 0, supplied.stderr)
            self.assertEqual(json.loads(supplied.stdout)["outcome"], "verified")

    def test_missing_generated_index_query_fails_without_creating_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing.sqlite"
            result = self.run_cli("search", str(missing), "synthetic", "--json")
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)["diagnostics"][0]["code"], "projection-unavailable")
            self.assertFalse(missing.exists())

    def test_context_command_records_explicit_selection_and_freshness(self):
        record = FIXTURES / "v0-valid-record.json"
        result = self.run_cli(
            "context",
            str(record),
            "--selected-at",
            "2026-07-30T00:00:00Z",
            "--freshness-basis",
            "synthetic-cli-test",
            "--json",
        )
        self.assertEqual(result.returncode, 0)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["selected_record_count"], 1)
        self.assertEqual(receipt["excluded_record_count"], 0)
        self.assertEqual(receipt["authority_boundary"], "informational-only; no execution, routing, disclosure, or mutation authority")

    def test_context_command_negotiates_required_extensions(self):
        record = json.loads((FIXTURES / "v0-valid-record.json").read_text(encoding="utf-8"))
        identifier = "https://synthetic.example/extensions/cli-required"
        record["extensions"] = {identifier: {"version": "v1", "required": True, "value": {}}}
        with tempfile.TemporaryDirectory() as temporary:
            record_path = Path(temporary) / "record.json"
            record_path.write_text(json.dumps(record), encoding="utf-8")
            rejected = self.run_cli(
                "context",
                str(record_path),
                "--selected-at",
                "2026-07-30T00:00:00Z",
                "--freshness-basis",
                "synthetic-cli-test",
                "--json",
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertEqual(json.loads(rejected.stdout)["diagnostics"][0]["code"], "required-extension-unsupported")
            rejected_human = self.run_cli(
                "context",
                str(record_path),
                "--selected-at",
                "2026-07-30T00:00:00Z",
                "--freshness-basis",
                "synthetic-cli-test",
            )
            self.assertEqual(rejected_human.returncode, 2)
            self.assertIn("required-extension-unsupported", rejected_human.stdout)
            admitted = self.run_cli(
                "context",
                str(record_path),
                "--selected-at",
                "2026-07-30T00:00:00Z",
                "--freshness-basis",
                "synthetic-cli-test",
                "--support-required-extension",
                identifier,
                "v1",
                "--json",
            )
            self.assertEqual(admitted.returncode, 0, admitted.stderr)
            self.assertEqual(json.loads(admitted.stdout)["selected_record_count"], 1)
            admitted_human = self.run_cli(
                "context",
                str(record_path),
                "--selected-at",
                "2026-07-30T00:00:00Z",
                "--freshness-basis",
                "synthetic-cli-test",
                "--support-required-extension",
                identifier,
                "v1",
            )
            self.assertEqual(admitted_human.returncode, 0, admitted_human.stderr)
            self.assertIn("selected_record_count: 1", admitted_human.stdout)

    def test_codex_history_import_writes_only_admitted_derivatives(self):
        fixture = ROOT / "fixtures" / "synthetic" / "codex-history" / "v1"
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "single-task-import"
            result = self.run_cli(
                "import-codex-history",
                str(fixture / "task-export.json"),
                str(fixture / "import-policy.json"),
                "--out",
                str(output),
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["records_written"], 4)
            self.assertTrue(summary["owner_review_required"])
            self.assertNotIn("synthetic-task-0001", result.stdout)
            self.assertNotIn(str(output), result.stdout)
            self.assertEqual(len(list((output / "records").glob("*.json"))), 4)
            self.assertTrue((output / "declassification-receipt.json").is_file())

            repeated = self.run_cli(
                "import-codex-history",
                str(fixture / "task-export.json"),
                str(fixture / "import-policy.json"),
                "--out",
                str(output),
                "--json",
            )
            self.assertEqual(repeated.returncode, 2)
            self.assertEqual(json.loads(repeated.stdout)["outcome"], "rejected")

    def test_dogfood_receipt_command_never_echoes_private_import_identity(self):
        fixture = ROOT / "fixtures" / "synthetic" / "codex-history" / "v1"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = json.loads((fixture / "task-export.json").read_text(encoding="utf-8"))
            policy = json.loads((fixture / "import-policy.json").read_text(encoding="utf-8"))
            policy.update(
                source_scope="local",
                authority_ref="authority://owner/codex-task-selection",
                record_sensitivity="private",
            )
            task_path = root / "task.json"
            policy_path = root / "policy.json"
            task_path.write_text(json.dumps(task), encoding="utf-8")
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            private_output = root / "private-output"
            imported = self.run_cli(
                "import-codex-history",
                str(task_path),
                str(policy_path),
                "--out",
                str(private_output),
                "--json",
            )
            self.assertEqual(imported.returncode, 0, imported.stderr)
            result = self.run_cli(
                "codex-history-dogfood-receipt",
                str(private_output / "declassification-receipt.json"),
                "--performed-at",
                "2026-08-01T00:00:00Z",
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["scope"], "authorized-private-single-task-import")
            self.assertNotIn("synthetic-task-0001", result.stdout)
            self.assertNotIn("source_task_ref", result.stdout)
            self.assertNotIn(str(private_output), result.stdout)


if __name__ == "__main__":
    unittest.main()
