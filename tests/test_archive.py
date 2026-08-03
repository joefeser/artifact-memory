import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import artifact_memory.archive as archive_module
from artifact_memory.archive import inspect_zip, validate_archive_receipt
from artifact_memory.archive_conformance import render_archive_conformance, run_archive_conformance
from artifact_memory.canonical import canonical_bytes, receipt_with_digest, sha256_bytes
from artifact_memory.validator import ValidationFailure


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/synthetic/archives/v1"


def _reseal(receipt):
    body = {key: value for key, value in receipt.items() if key not in {"schema_id", "receipt_id"}}
    return receipt_with_digest(receipt["schema_id"], "archive-inspection-receipt://", body)


class ArchiveTests(unittest.TestCase):
    def test_checked_safe_and_malicious_fixture(self):
        receipt = run_archive_conformance(FIXTURE / "vectors.json")
        expected = json.loads((FIXTURE / "expected-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt, expected)
        self.assertEqual(render_archive_conformance(receipt), (FIXTURE / "receipt.md").read_text(encoding="utf-8"))

    def test_safe_archive_binds_distinct_container_and_tree_identities(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "safe.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("orders.txt", b"synthetic archive\n")
            receipt = inspect_zip(archive_path)
            validate_archive_receipt(receipt)
            self.assertEqual(receipt["outcome"], "supported")
            self.assertNotEqual(receipt["container"]["content_digest"], receipt["extracted_tree_manifest_digest"])
            self.assertEqual(receipt["relationship"]["container_content_digest"], receipt["container"]["content_digest"])
            self.assertEqual(set(Path(temporary).iterdir()), {archive_path})

    def test_partial_result_emits_no_complete_tree_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "unsafe.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("safe.txt", b"safe")
                archive.writestr("../escape.txt", b"bad")
                archive.writestr("large.bin", b"0123456789")
            receipt = inspect_zip(archive_path, max_uncompressed_bytes=5)
            self.assertEqual(receipt["outcome"], "partial")
            self.assertIsNone(receipt["extracted_tree_manifest"])
            self.assertIsNone(receipt["relationship"])
            self.assertEqual([item["code"] for item in receipt["diagnostics"]], ["path-traversal", "decompression-limit"])

    def test_absolute_drive_and_backslash_traversal_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "paths.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("/absolute.txt", b"bad")
                archive.writestr("C:/drive.txt", b"bad")
                archive.writestr("d:relative.txt", b"bad")
                archive.writestr("..\\escape.txt", b"bad")
                archive.writestr("safe.txt", b"safe")
            receipt = inspect_zip(archive_path)
            self.assertEqual([entry["path"] for entry in receipt["entries"]], ["safe.txt"])
            self.assertEqual([item["code"] for item in receipt["diagnostics"]], ["path-traversal"] * 4)

    def test_raw_nul_and_file_descendant_conflicts_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            nul_path = Path(temporary) / "nul.zip"
            with zipfile.ZipFile(nul_path, "w") as archive:
                archive.writestr("safe.txt", b"unsafe-name")
            nul_path.write_bytes(nul_path.read_bytes().replace(b"safe.txt", b"safe\x00txt"))
            nul_receipt = inspect_zip(nul_path)
            self.assertEqual([item["code"] for item in nul_receipt["diagnostics"]], ["path-traversal"])
            self.assertEqual(nul_receipt["entries"], [])

            conflict_path = Path(temporary) / "conflict.zip"
            with zipfile.ZipFile(conflict_path, "w") as archive:
                archive.writestr("node", b"file")
                archive.writestr("node/child.txt", b"child")
            conflict_receipt = inspect_zip(conflict_path)
            self.assertEqual([entry["path"] for entry in conflict_receipt["entries"]], ["node"])
            self.assertEqual([item["code"] for item in conflict_receipt["diagnostics"]], ["path-conflict"])

    def test_corrupt_entries_consume_the_global_decompression_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "budget.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("corrupt.bin", b"MARK")
                archive.writestr("later.bin", b"1234")
            data = bytearray(archive_path.read_bytes())
            position = data.find(b"MARK")
            self.assertGreaterEqual(position, 0)
            data[position] ^= 0x01
            archive_path.write_bytes(data)
            receipt = inspect_zip(archive_path, max_uncompressed_bytes=6)
            self.assertEqual(
                [item["code"] for item in receipt["diagnostics"]],
                ["corrupt-entry", "decompression-limit"],
            )

    def test_entry_count_limit_stops_with_partial_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "count.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("one.txt", b"one")
                archive.writestr("two.txt", b"two")
            receipt = inspect_zip(archive_path, max_entries=1)
            self.assertEqual(receipt["outcome"], "partial")
            self.assertEqual([item["code"] for item in receipt["diagnostics"]], ["entry-count-limit"])
            self.assertIsNone(receipt["relationship"])

    def test_corrupt_container_retains_hash_of_available_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "corrupt.zip"
            archive_path.write_bytes(b"newly authored synthetic invalid ZIP")
            receipt = inspect_zip(archive_path)
            self.assertEqual(receipt["outcome"], "failed")
            self.assertEqual(receipt["container"]["integrity"], "bytes-hashed")
            self.assertIsNotNone(receipt["container"]["content_digest"])
            self.assertEqual(receipt["diagnostics"][0]["code"], "corrupt-container")

    def test_container_change_during_inspection_invalidates_identity_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "changing.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("safe.txt", b"safe")
            original = archive_module._inspect_open_zip

            def inspect_then_change(*args, **kwargs):
                receipt = original(*args, **kwargs)
                archive_path.write_bytes(b"synthetic replacement bytes")
                return receipt

            with patch("artifact_memory.archive._inspect_open_zip", side_effect=inspect_then_change):
                receipt = inspect_zip(archive_path)
            self.assertEqual(receipt["outcome"], "failed")
            self.assertEqual(receipt["diagnostics"][0]["code"], "container-changed-during-inspection")
            self.assertIsNone(receipt["container"]["content_digest"])

    def test_missing_archive_reports_unavailable_without_fabricated_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            receipt = inspect_zip(Path(temporary) / "missing.zip")
            self.assertEqual(receipt["outcome"], "failed")
            self.assertEqual(receipt["container"], {"content_digest": None, "byte_size": None, "integrity": "unavailable"})
            self.assertEqual(receipt["diagnostics"][0]["code"], "container-unavailable")

    def test_invalid_resource_limits_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "unused.zip"
            for kwargs in ({"max_entries": 0}, {"max_entries": True}, {"max_uncompressed_bytes": -1}):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValidationFailure) as failure:
                    inspect_zip(path, **kwargs)
                self.assertEqual(failure.exception.code, "archive-limit-invalid")

    def test_semantic_validator_rejects_resealed_manifest_substitution(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "safe.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("one.txt", b"one")
                archive.writestr("two.txt", b"two")
            receipt = inspect_zip(archive_path)
        substituted = copy.deepcopy(receipt)
        substituted["extracted_tree_manifest"]["entries"] = substituted["entries"][:1]
        substituted["extracted_tree_manifest_digest"] = sha256_bytes(canonical_bytes(substituted["extracted_tree_manifest"]))
        substituted["relationship"]["extracted_tree_manifest_digest"] = substituted["extracted_tree_manifest_digest"]
        substituted = _reseal(substituted)
        with self.assertRaises(ValidationFailure) as failure:
            validate_archive_receipt(substituted)
        self.assertEqual(failure.exception.code, "archive-tree-entry-mismatch")

    def test_semantic_validator_rejects_resealed_unsorted_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "safe.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("a.txt", b"a")
                archive.writestr("b.txt", b"b")
            receipt = inspect_zip(archive_path)
        tampered = copy.deepcopy(receipt)
        tampered["entries"].reverse()
        tampered["observed_entry_set_digest"] = sha256_bytes(canonical_bytes(tampered["entries"]))
        tampered["extracted_tree_manifest"]["entries"] = tampered["entries"]
        tampered["extracted_tree_manifest_digest"] = sha256_bytes(canonical_bytes(tampered["extracted_tree_manifest"]))
        tampered["relationship"]["extracted_tree_manifest_digest"] = tampered["extracted_tree_manifest_digest"]
        tampered = _reseal(tampered)
        with self.assertRaises(ValidationFailure) as failure:
            validate_archive_receipt(tampered)
        self.assertEqual(failure.exception.code, "archive-entry-order-invalid")

    def test_semantic_validator_rejects_unsafe_and_conflicting_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "safe.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("a.txt", b"a")
                archive.writestr("b.txt", b"b")
            receipt = inspect_zip(archive_path)
        for paths, code in ((["../escape", "b.txt"], "archive-entry-path-invalid"), (["node", "node/child"], "archive-entry-path-conflict")):
            tampered = copy.deepcopy(receipt)
            for entry, path in zip(tampered["entries"], paths):
                entry["path"] = path
            tampered["entries"].sort(key=lambda entry: entry["path"])
            tampered["observed_entry_set_digest"] = sha256_bytes(canonical_bytes(tampered["entries"]))
            tampered["extracted_tree_manifest"]["entries"] = tampered["entries"]
            tampered["extracted_tree_manifest_digest"] = sha256_bytes(canonical_bytes(tampered["extracted_tree_manifest"]))
            tampered["relationship"]["extracted_tree_manifest_digest"] = tampered["extracted_tree_manifest_digest"]
            tampered = _reseal(tampered)
            with self.subTest(paths=paths), self.assertRaises(ValidationFailure) as failure:
                validate_archive_receipt(tampered)
            self.assertEqual(failure.exception.code, code)

    def test_malformed_conformance_vectors_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            vector_path = Path(temporary) / "vectors.json"
            malformed_values = (
                [],
                {"schema_id": "artifact-memory/archive-conformance-vectors/v1", "synthetic": True, "cases": [None]},
                {"schema_id": "artifact-memory/archive-conformance-vectors/v1", "synthetic": True, "cases": [{"case_id": "../escape", "entries": [], "expected_outcome": "supported", "expected_diagnostic_codes": []}]},
            )
            for malformed in malformed_values:
                vector_path.write_text(json.dumps(malformed), encoding="utf-8")
                with self.subTest(malformed=malformed), self.assertRaises(ValidationFailure) as failure:
                    run_archive_conformance(vector_path)
                self.assertEqual(failure.exception.code, "invalid-vector")


if __name__ == "__main__":
    unittest.main()
