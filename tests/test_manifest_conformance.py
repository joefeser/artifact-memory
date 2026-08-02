import json
import tempfile
import unittest
from pathlib import Path

from artifact_memory.manifest_conformance import render_manifest_conformance_receipt, run_manifest_conformance
from artifact_memory.validator import ValidationFailure


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "manifests" / "v1"


class ManifestConformanceTests(unittest.TestCase):
    def _run_changed(self, change):
        vectors = json.loads((FIXTURE / "vectors.json").read_text(encoding="utf-8"))
        change(vectors)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "vectors.json"
            path.write_text(json.dumps(vectors), encoding="utf-8")
            return run_manifest_conformance(path)

    def test_checked_machine_and_human_receipts_replay(self):
        receipt = run_manifest_conformance(FIXTURE / "vectors.json")
        expected = json.loads((FIXTURE / "expected-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt, expected)
        self.assertEqual(render_manifest_conformance_receipt(receipt), (FIXTURE / "receipt.md").read_text(encoding="utf-8"))

    def test_layout_order_and_mount_roots_do_not_change_tree_identity(self):
        receipt = run_manifest_conformance(FIXTURE / "vectors.json")
        for case_index, case in enumerate(receipt["positive_cases"]):
            observed = {receipt["platform_tree_digests"][platform][case_index] for platform in receipt["platforms"]}
            self.assertEqual(observed, {case["tree_digest"]})

    def test_tree_digest_drift_fails_closed(self):
        with self.assertRaises(ValidationFailure) as raised:
            self._run_changed(lambda vectors: vectors["positive_cases"][0].update(expected_tree_digest="sha-256:" + "0" * 64))
        self.assertEqual(raised.exception.code, "vector-mismatch")

    def test_layout_content_drift_breaks_equivalence(self):
        def change(vectors):
            vectors["positive_cases"][0]["layouts"][0]["entries"][0]["content_utf8"] = "different\n"

        with self.assertRaises(ValidationFailure) as raised:
            self._run_changed(change)
        self.assertEqual(raised.exception.code, "vector-mismatch")

    def test_negative_outcome_labels_cannot_be_swapped(self):
        def change(vectors):
            vectors["negative_cases"][0]["expected_outcome"] = "unsupported"

        with self.assertRaises(ValidationFailure) as raised:
            self._run_changed(change)
        self.assertEqual(raised.exception.code, "vector-mismatch")

    def test_duplicate_case_identity_and_exact_duplicate_paths_fail_closed(self):
        def duplicate_case(vectors):
            vectors["negative_cases"][0]["case_id"] = vectors["positive_cases"][0]["case_id"]

        with self.assertRaises(ValidationFailure) as raised:
            self._run_changed(duplicate_case)
        self.assertEqual(raised.exception.code, "duplicate-vector-identity")

        def duplicate_path(vectors):
            vectors["negative_cases"][0]["observations"][1]["path"] = vectors["negative_cases"][0]["observations"][0]["path"]

        with self.assertRaises(ValidationFailure) as raised:
            self._run_changed(duplicate_path)
        self.assertEqual(raised.exception.code, "invalid-vector")

    def test_equivalence_cases_require_distinct_mount_roots(self):
        def duplicate_root(vectors):
            layouts = vectors["positive_cases"][0]["layouts"]
            layouts[1]["mount_root"] = layouts[0]["mount_root"]

        with self.assertRaises(ValidationFailure) as raised:
            self._run_changed(duplicate_root)
        self.assertEqual(raised.exception.code, "invalid-vector")

    def test_ambiguous_and_parentless_paths_fail_closed(self):
        for path in (".", "folder\\file", "folder/file\nname", "report:final.txt", "CON.txt", "folder/NUL.json", "trailing.", "trailing "):
            with self.subTest(path=path), self.assertRaises(ValidationFailure):
                self._run_changed(lambda vectors, path=path: vectors["positive_cases"][0]["layouts"][0]["entries"][0].update(path=path))

        def remove_parent(vectors):
            entries = vectors["positive_cases"][0]["layouts"][0]["entries"]
            vectors["positive_cases"][0]["layouts"][0]["entries"] = [entry for entry in entries if entry["path"] != "docs"]

        with self.assertRaises(ValidationFailure):
            self._run_changed(remove_parent)

    def test_vector_schema_matches_runner_entry_and_observation_contracts(self):
        def add_positive_field(vectors):
            vectors["positive_cases"][0]["layouts"][0]["entries"][0]["unexpected"] = True

        with self.assertRaises(ValidationFailure) as raised:
            self._run_changed(add_positive_field)
        self.assertEqual(raised.exception.code, "unknown-field")

        def unknown_observation_kind(vectors):
            vectors["negative_cases"][1]["observations"][0]["kind"] = "synthetic-unknown-kind"

        with self.assertRaises(ValidationFailure) as raised:
            self._run_changed(unknown_observation_kind)
        self.assertEqual(raised.exception.code, "constraint-failed")


if __name__ == "__main__":
    unittest.main()
