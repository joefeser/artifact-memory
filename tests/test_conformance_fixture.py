import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from artifact_memory.canonical import sha256_bytes
from artifact_memory.conformance_fixture import _json_pointer, _read_fixture_snapshot, _run_declared_outcome, render_conformance_fixture_receipt, run_conformance_fixture
from artifact_memory.validator import ValidationFailure


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "conformance" / "v1"


class ConformanceFixtureTests(unittest.TestCase):
    def _run(self, manifest: dict | None = None, expected: dict | None = None, repository_root: Path = ROOT):
        if manifest is None:
            manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
        if expected is None:
            expected = json.loads((FIXTURE / "expected-results.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            expected_path = root / "expected-results.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            expected_path.write_text(json.dumps(expected), encoding="utf-8")
            return run_conformance_fixture(manifest_path, expected_path, repository_root)

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

    def test_digest_and_execution_use_the_same_byte_snapshot(self):
        manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
        expected = json.loads((FIXTURE / "expected-results.json").read_text(encoding="utf-8"))
        vector_path = ROOT / manifest["cases"][0]["inputs"][0]["path"]
        vector = json.loads(vector_path.read_text(encoding="utf-8"))
        vector["content_utf8"] = "Atomic synthetic snapshot\n"
        content = vector["content_utf8"].encode("utf-8")
        vector["byte_size"] = len(content)
        vector["content_digest"] = sha256_bytes(content)
        vector["leaf_serialization"] = f"file\t{vector['relative_path']}\t{vector['content_digest']}\t{len(content)}\n"
        vector["tree_digest"] = sha256_bytes(vector["leaf_serialization"].encode("utf-8"))
        snapshot = json.dumps(vector, separators=(",", ":")).encode("utf-8")
        manifest["cases"][0]["inputs"][0]["sha256"] = sha256_bytes(snapshot)
        expected["results"][0]["assertions"][0]["value"] = len(content)
        expected["results"][0]["assertions"][1]["value"] = vector["content_digest"]
        expected["results"][0]["assertions"][2]["value"] = vector["tree_digest"]
        original_reader = _read_fixture_snapshot

        def read_snapshot(path: Path) -> bytes:
            return snapshot if path == vector_path else original_reader(path)

        with patch("artifact_memory.conformance_fixture._read_fixture_snapshot", side_effect=read_snapshot):
            receipt = self._run(manifest=manifest, expected=expected)
        self.assertEqual(receipt["cases"][0]["outcome"], "accepted")

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

    def test_unavailable_fixture_names_the_required_bundle_or_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValidationFailure) as raised:
                self._run(repository_root=Path(temporary))
        self.assertEqual(raised.exception.code, "fixture-unavailable")
        self.assertIn("repository_root", raised.exception.message)

    def test_v1_rejects_multiple_inputs_and_ignored_selectors(self):
        manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
        manifest["cases"][0]["inputs"].append(dict(manifest["cases"][0]["inputs"][0]))
        with self.assertRaises(ValidationFailure):
            self._run(manifest=manifest)

        manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
        manifest["cases"][2]["inputs"][0]["selector"] = "/platforms"
        with self.assertRaises(ValidationFailure):
            self._run(manifest=manifest)

    def test_schema_id_under_test_is_conditioned_on_operation(self):
        manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
        del manifest["cases"][1]["schema_id_under_test"]
        with self.assertRaises(ValidationFailure):
            self._run(manifest=manifest)

        manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
        manifest["cases"][0]["schema_id_under_test"] = "artifact-memory/location-observation/v1"
        with self.assertRaises(ValidationFailure):
            self._run(manifest=manifest)

    def test_pointer_escapes_and_array_indexes_fail_closed(self):
        self.assertEqual(_json_pointer(["zero", "one"], "/0"), "zero")
        self.assertEqual(_json_pointer({"a/b": {"~": "value"}}, "/a~1b/~0"), "value")
        for pointer in ("/00", "/01", "/١", "/bad~2"):
            with self.subTest(pointer=pointer), self.assertRaises(ValidationFailure):
                _json_pointer(["zero", "one"], pointer)

        expected = json.loads((FIXTURE / "expected-results.json").read_text(encoding="utf-8"))
        expected["results"][0]["assertions"][0]["pointer"] = "/bad~2"
        with self.assertRaises(ValidationFailure):
            self._run(expected=expected)

    def test_unhashable_declared_outcome_is_a_typed_failure(self):
        case = {"case_id": "malformed", "class": "collision"}
        for field in ("expected_code", "expected_outcome"):
            declaration = {"expected_code": "collision", "expected_outcome": "partial"}
            declaration[field] = []
            with self.subTest(field=field), self.assertRaises(ValidationFailure) as raised:
                _run_declared_outcome(case, [(Path("synthetic.json"), declaration)])
            self.assertEqual(raised.exception.code, "invalid-vector")

    def test_noncanonical_assertion_and_class_outcome_mismatch_fail_closed(self):
        expected = json.loads((FIXTURE / "expected-results.json").read_text(encoding="utf-8"))
        expected["results"][0]["assertions"][0]["value"] = 1.5
        with self.assertRaises(ValidationFailure) as raised:
            self._run(expected=expected)
        self.assertEqual(raised.exception.code, "invalid-canonical-json")

        manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
        expected = json.loads((FIXTURE / "expected-results.json").read_text(encoding="utf-8"))
        manifest["cases"][0]["class"], manifest["cases"][1]["class"] = manifest["cases"][1]["class"], manifest["cases"][0]["class"]
        expected["results"][0]["class"], expected["results"][1]["class"] = expected["results"][1]["class"], expected["results"][0]["class"]
        with self.assertRaises(ValidationFailure):
            self._run(manifest=manifest, expected=expected)

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
