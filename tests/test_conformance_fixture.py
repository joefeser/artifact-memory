import json
import tempfile
import unittest
from pathlib import Path

from artifact_memory.conformance_fixture import render_conformance_fixture_receipt, run_conformance_fixture
from artifact_memory.validator import ValidationFailure


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "conformance" / "v1"


class ConformanceFixtureTests(unittest.TestCase):
    def _run(self, manifest: dict | None = None, expected: dict | None = None):
        manifest = manifest or json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
        expected = expected or json.loads((FIXTURE / "expected-results.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            expected_path = root / "expected-results.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            expected_path.write_text(json.dumps(expected), encoding="utf-8")
            return run_conformance_fixture(manifest_path, expected_path, ROOT)

    def test_checked_machine_and_human_receipts_replay(self):
        receipt = run_conformance_fixture(FIXTURE / "manifest.json", FIXTURE / "expected-results.json", ROOT)
        expected = json.loads((FIXTURE / "expected-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt, expected)
        self.assertEqual(render_conformance_fixture_receipt(receipt), (FIXTURE / "receipt.md").read_text(encoding="utf-8"))

    def test_all_required_classes_have_distinct_results(self):
        receipt = self._run()
        self.assertEqual(receipt["case_count"], 5)
        self.assertEqual(receipt["class_counts"], {"valid": 1, "invalid": 1, "equivalent": 1, "collision": 1, "unsupported": 1})
        self.assertEqual({item["outcome"] for item in receipt["cases"]}, {"accepted", "rejected", "equivalent", "collision", "unsupported"})

    def test_unknown_manifest_schema_fails_closed(self):
        manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
        manifest["schema_id"] = "artifact-memory/conformance-fixture-manifest/v2"
        with self.assertRaises(ValidationFailure):
            self._run(manifest=manifest)

    def test_changed_input_digest_fails_closed(self):
        manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
        manifest["cases"][0]["inputs"][0]["sha256"] = "sha-256:" + "0" * 64
        with self.assertRaises(ValidationFailure) as raised:
            self._run(manifest=manifest)
        self.assertEqual(raised.exception.code, "fixture-digest-mismatch")

    def test_path_escape_fails_before_input_read(self):
        manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
        manifest["cases"][0]["inputs"][0]["path"] = "fixtures/synthetic/../private.json"
        with self.assertRaises(ValidationFailure):
            self._run(manifest=manifest)

    def test_non_normalized_fixture_reference_fails_closed(self):
        for path in ("fixtures/synthetic//vectors/v0-vector-0001.json", "fixtures/synthetic/./vectors/v0-vector-0001.json"):
            with self.subTest(path=path):
                manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
                manifest["cases"][0]["inputs"][0]["path"] = path
                with self.assertRaises(ValidationFailure) as raised:
                    self._run(manifest=manifest)
                self.assertEqual(raised.exception.code, "invalid-fixture-reference")

    def test_duplicate_case_identity_and_result_drift_fail_closed(self):
        manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
        manifest["cases"][1]["case_id"] = manifest["cases"][0]["case_id"]
        with self.assertRaises(ValidationFailure) as raised:
            self._run(manifest=manifest)
        self.assertEqual(raised.exception.code, "duplicate-fixture-identity")

        expected = json.loads((FIXTURE / "expected-results.json").read_text(encoding="utf-8"))
        expected["results"][0]["assertions"][0]["value"] = 36
        with self.assertRaises(ValidationFailure) as raised:
            self._run(expected=expected)
        self.assertEqual(raised.exception.code, "expected-result-mismatch")


if __name__ == "__main__":
    unittest.main()
