import tempfile
import unittest
from pathlib import Path
import hashlib
import json

from artifact_memory.scan import ScanLimits, diff_manifests, scan_path, verify_path
from artifact_memory.validator import validate


class ScanTests(unittest.TestCase):
    def test_cross_platform_ordinary_tree_vector_is_path_layout_independent(self):
        vector = json.loads((Path(__file__).resolve().parents[1] / "fixtures/synthetic/manifests/v0-ordinary-tree.json").read_text(encoding="utf-8"))
        lines = "".join(f"file\t{entry['path']}\t{entry['content_digest']}\t{entry['byte_size']}\n" for entry in vector["logical_entries"])
        self.assertEqual("sha-256:" + hashlib.sha256(lines.encode()).hexdigest(), vector["tree_digest"])
        self.assertNotEqual(vector["container_digest"], vector["extracted_tree_digest"])
        self.assertEqual(len(set(vector["platform_layouts"].values())), 3)

    def test_deterministic_scan_and_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            (root / "src" / "orders.txt").write_bytes(b"synthetic orders\n")
            first, receipt = scan_path(root)
            second, _ = scan_path(root)
            self.assertEqual(first, second)
            self.assertEqual(receipt["outcome"], "complete")
            self.assertEqual(verify_path(root, first)["outcome"], "verified")

    def test_diff_reports_content_changes_and_move_candidates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "old.txt").write_text("same", encoding="utf-8")
            before, _ = scan_path(root)
            (root / "old.txt").rename(root / "new.txt")
            (root / "changed.txt").write_text("new", encoding="utf-8")
            after, _ = scan_path(root)
            result = diff_manifests(before, after)
            self.assertEqual(result["added"], ["changed.txt", "new.txt"])
            self.assertEqual(result["removed"], ["old.txt"])
            self.assertEqual(result["changed"], [])
            self.assertEqual(result["moved_candidates"][0]["from"], "old.txt")
            self.assertEqual(result["moved_candidates"][0]["to"], "new.txt")

    def test_symlink_is_explicitly_unsupported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "target").write_text("synthetic", encoding="utf-8")
            try:
                (root / "link").symlink_to(root / "target")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable on this platform")
            _, receipt = scan_path(root)
            self.assertEqual(receipt["outcome"], "partial")
            self.assertEqual(receipt["diagnostics"][0]["code"], "unsupported")

    def test_resource_limit_and_cancellation_are_distinct(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "a.txt").write_bytes(b"1234")
            (root / "b.txt").write_bytes(b"5678")
            _, limited = scan_path(root, ScanLimits(max_bytes=4))
            self.assertEqual(limited["outcome"], "partial")
            self.assertEqual(limited["diagnostics"][0]["code"], "resource-limit")
            _, cancelled = scan_path(root, ScanLimits(cancellation_check=lambda: True))
            self.assertEqual(cancelled["outcome"], "cancelled")
            self.assertEqual(cancelled["diagnostics"][0]["code"], "cancelled")
            schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/core/scan-receipt.v1.schema.json").read_text(encoding="utf-8"))
            validate(limited, schema)
            validate(cancelled, schema)


if __name__ == "__main__":
    unittest.main()
