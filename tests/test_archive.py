import tempfile
import unittest
import zipfile
from pathlib import Path

from artifact_memory.archive import inspect_zip
from artifact_memory.validator import validate
import json


ROOT = Path(__file__).resolve().parents[1]


class ArchiveTests(unittest.TestCase):
    def test_safe_archive_keeps_container_and_tree_digests_distinct(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "safe.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("orders.txt", b"synthetic archive\n")
            receipt = inspect_zip(archive_path)
            schema = json.loads((ROOT / "schemas/core/archive-receipt.v1.schema.json").read_text(encoding="utf-8"))
            validate(receipt, schema)
            self.assertEqual(receipt["outcome"], "supported")
            self.assertNotEqual(receipt["container_digest"], receipt["extracted_tree_digest"])

    def test_malicious_paths_and_limits_are_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "unsafe.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../escape.txt", b"bad")
                archive.writestr("Readme.txt", b"one")
                archive.writestr("README.TXT", b"two")
                archive.writestr("large.bin", b"0123456789")
            receipt = inspect_zip(archive_path, max_uncompressed_bytes=5)
            self.assertEqual(receipt["outcome"], "partial")
            codes = {item["code"] for item in receipt["diagnostics"]}
            self.assertIn("path-traversal", codes)
            self.assertIn("decompression-limit", codes)


if __name__ == "__main__":
    unittest.main()
