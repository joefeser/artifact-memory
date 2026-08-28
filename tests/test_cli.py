import copy
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from artifact_memory.canonical import receipt_with_digest
from artifact_memory.canonical import sha256_bytes
from artifact_memory.release_preparation import RELEASE_PREPARATION_RECEIPT_PREFIX
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

    def test_search_receipt_pins_digest_through_cli(self):
        from artifact_memory.projection import project_records

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "generated"
            projection_receipt = project_records([FIXTURES / "v0-valid-record.json"], output)
            index = output / "records.sqlite"

            sensitive_query = "synthetic NOT bearer_canary_42"
            result = self.run_cli("search-receipt", str(index), sensitive_query, "--json")
            human_result = self.run_cli("search-receipt", str(index), sensitive_query)
            rejected = self.run_cli("search-receipt", str(index), '"', "--json")

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema_id"], "artifact-memory/search-receipt/v1")
        self.assertNotIn("query", payload)
        self.assertEqual(payload["query_digest"], sha256_bytes(sensitive_query.encode("utf-8")))
        self.assertNotIn(sensitive_query, result.stdout)
        self.assertNotIn(sensitive_query, human_result.stdout)
        self.assertEqual(payload["source_record_set_digest"], projection_receipt["source_record_set_digest"])
        self.assertEqual(payload["record_ids"], ["record://synthetic/record-0001"])
        self.assertEqual(payload["integrity_gate"], "verified")
        self.assertIn("source_record_set_digest: " + projection_receipt["source_record_set_digest"], human_result.stdout)
        self.assertEqual(rejected.returncode, 2)
        self.assertEqual(json.loads(rejected.stdout)["diagnostics"][0]["code"], "query-invalid")

    def test_search_literal_mode_through_cli(self):
        from artifact_memory.projection import project_records

        record = {
            "schema_id": "artifact-memory/knowledge-record/v1",
            "record_id": "record://synthetic/literal-cli-0001",
            "record_type": "note",
            "lifecycle": "accepted",
            "meaning": {"summary": "Synthetic alpha-beta adjacency proves literal quoting."},
            "artifact_refs": [],
            "provenance": [{"kind": "author", "source_ref": "fixture://synthetic/literal/v1"}],
            "sensitivity": "public",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record_path = root / "record.json"
            record_path.write_text(json.dumps(record), encoding="utf-8")
            output = root / "generated"
            project_records([record_path], output)
            index = output / "records.sqlite"

            literal = self.run_cli("search", str(index), "alpha-beta", "--literal", "--json")
            raw = self.run_cli("search", str(index), "alpha-beta", "--json")
            receipt = self.run_cli("search-receipt", str(index), "alpha-beta", "--literal", "--json")

        self.assertEqual(literal.returncode, 0)
        self.assertEqual(json.loads(literal.stdout)["record_ids"], ["record://synthetic/literal-cli-0001"])
        self.assertEqual(raw.returncode, 2)
        self.assertEqual(json.loads(raw.stdout)["diagnostics"][0]["code"], "query-invalid")
        self.assertEqual(receipt.returncode, 0)
        self.assertEqual(json.loads(receipt.stdout)["record_ids"], ["record://synthetic/literal-cli-0001"])

    def test_search_exclude_superseded_through_cli(self):
        from artifact_memory.projection import project_records

        records = []
        for ordinal, lifecycle in enumerate(("accepted", "superseded"), start=1):
            records.append(
                {
                    "schema_id": "artifact-memory/knowledge-record/v1",
                    "record_id": f"record://synthetic/supersession-cli-000{ordinal}",
                    "record_type": "note",
                    "lifecycle": lifecycle,
                    "meaning": {"summary": f"{lifecycle} synthetic ledger note for the CLI filter"},
                    "artifact_refs": [],
                    "provenance": [{"kind": "author", "source_ref": "fixture://synthetic/supersession/v1"}],
                    "sensitivity": "public",
                }
            )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = []
            for ordinal, record in enumerate(records, start=1):
                path = root / f"record-000{ordinal}.json"
                path.write_text(json.dumps(record), encoding="utf-8")
                paths.append(path)
            output = root / "generated"
            project_records(paths, output)
            index = output / "records.sqlite"

            default = self.run_cli("search", str(index), "ledger", "--json")
            filtered = self.run_cli("search", str(index), "ledger", "--exclude-superseded", "--json")
            receipt = self.run_cli("search-receipt", str(index), "ledger", "--exclude-superseded", "--json")

        self.assertEqual(default.returncode, 0)
        self.assertEqual(len(json.loads(default.stdout)["record_ids"]), 2)
        self.assertEqual(filtered.returncode, 0)
        self.assertEqual(json.loads(filtered.stdout)["record_ids"], ["record://synthetic/supersession-cli-0001"])
        self.assertEqual(receipt.returncode, 0)
        payload = json.loads(receipt.stdout)
        self.assertTrue(payload["exclude_superseded"])
        self.assertEqual(payload["record_ids"], ["record://synthetic/supersession-cli-0001"])

    def test_search_ranking_through_cli(self):
        from artifact_memory.projection import project_records

        records = []
        summaries = (
            "beta beta beta beta beta gamma alpha",
            "beta gamma gamma gamma gamma alpha",
        )
        for ordinal, summary in enumerate(summaries, start=1):
            records.append(
                {
                    "schema_id": "artifact-memory/knowledge-record/v1",
                    "record_id": f"record://synthetic/ranking-cli-000{ordinal}",
                    "record_type": "note",
                    "lifecycle": "accepted",
                    "meaning": {"summary": summary},
                    "artifact_refs": [],
                    "provenance": [{"kind": "author", "source_ref": "fixture://synthetic/ranking/v1"}],
                    "sensitivity": "public",
                }
            )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = []
            for ordinal, record in enumerate(records, start=1):
                path = root / f"record-000{ordinal}.json"
                path.write_text(json.dumps(record), encoding="utf-8")
                paths.append(path)
            output = root / "generated"
            project_records(paths, output)
            index = output / "records.sqlite"

            unranked = self.run_cli("search", str(index), "beta gamma", "--json")
            ranked = self.run_cli("search", str(index), "beta gamma", "--rank", "--json")
            receipt = self.run_cli("search-receipt", str(index), "beta gamma", "--rank", "--json")
            human = self.run_cli("search-receipt", str(index), "beta gamma", "--rank")

        self.assertEqual(unranked.returncode, 0)
        self.assertEqual(
            json.loads(unranked.stdout)["record_ids"],
            ["record://synthetic/ranking-cli-0001", "record://synthetic/ranking-cli-0002"],
        )
        self.assertEqual(ranked.returncode, 0)
        self.assertEqual(
            json.loads(ranked.stdout)["record_ids"],
            ["record://synthetic/ranking-cli-0002", "record://synthetic/ranking-cli-0001"],
        )
        payload = json.loads(receipt.stdout)
        self.assertEqual(
            payload["result_order"],
            {"ranking": "bm25", "tiebreak": "record-id", "authoritative": False, "corpus_dependent": True},
        )
        self.assertIn("result_order", human.stdout)
        self.assertIn("'authoritative': False", human.stdout)

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
        self.assertIn("verify authenticity or accept release evidence", result.stdout)

    def test_release_manifest_validation_preserves_v0_result_shape(self):
        for fixture in (
            RELEASE_FIXTURES / "v0-preview-manifest.json",
            RELEASE_FIXTURES / "v0-pending-candidate-manifest.v2.json",
        ):
            with self.subTest(fixture=fixture.name):
                result = self.run_cli("validate", str(fixture), "--json")
                self.assertEqual(result.returncode, 0, result.stderr)
                receipt = json.loads(result.stdout)
                self.assertEqual(
                    set(receipt),
                    {"valid", "outcome", "diagnostics", "schema_id"},
                )
                self.assertTrue(receipt["valid"])
                self.assertEqual(receipt["outcome"], "accepted")

    def test_validate_applies_release_preparation_version_binding(self):
        fixture = json.loads(
            (RELEASE_FIXTURES / "v0-preparation-expected-receipt.json").read_text(
                encoding="utf-8"
            )
        )
        body = {
            key: value
            for key, value in fixture.items()
            if key not in {"schema_id", "receipt_id"}
        }
        body["package_version"] = "0.1.1"
        invalid = receipt_with_digest(
            "artifact-memory/release-preparation-receipt/v1",
            RELEASE_PREPARATION_RECEIPT_PREFIX,
            body,
        )
        with tempfile.TemporaryDirectory() as temporary:
            receipt_path = Path(temporary) / "release-preparation-receipt.json"
            receipt_path.write_text(json.dumps(invalid), encoding="utf-8")
            result = self.run_cli("validate", str(receipt_path), "--json")

        self.assertEqual(result.returncode, 2)
        validation = json.loads(result.stdout)
        self.assertFalse(validation["valid"])
        self.assertEqual(
            validation["diagnostics"][0]["code"],
            "release-preparation-receipt-version-mismatch",
        )

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

    def test_context_command_explicitly_negotiates_lifecycle_aware_v4(self):
        fixture = ROOT / "fixtures/synthetic/record-evolution/v2"
        predecessor = fixture / "superseded-predecessor.json"
        replacement = fixture / "accepted-record.json"
        base_args = (
            "context",
            str(predecessor),
            str(replacement),
            "--selected-at",
            "2026-08-08T00:00:00Z",
            "--freshness-basis",
            "synthetic-cli-lifecycle-test",
            "--json",
        )
        unnegotiated = self.run_cli(*base_args)
        self.assertEqual(unnegotiated.returncode, 2)
        self.assertEqual(json.loads(unnegotiated.stdout)["diagnostics"][0]["code"], "context-schema-unnegotiated")

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "context"
            negotiated = self.run_cli(
                *base_args,
                "--support-context-schema",
                "artifact-memory/context-pack/v4",
                "--out",
                str(output),
            )
            pack = json.loads((output / "context-pack.json").read_text(encoding="utf-8"))
        self.assertEqual(negotiated.returncode, 0, negotiated.stderr)
        self.assertEqual(pack["schema_id"], "artifact-memory/context-pack/v4")
        self.assertEqual(pack["selection_receipt"]["exclusion_counts"]["lifecycle"], 1)

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
