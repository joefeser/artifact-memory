import unittest
import json
from pathlib import Path

from artifact_memory.platform_matrix import probe_platform
from artifact_memory.validator import validate


class PlatformMatrixTests(unittest.TestCase):
    def test_probe_is_sanitized_and_explicit(self):
        receipt = probe_platform()
        self.assertEqual(receipt["schema_id"], "artifact-memory/platform-matrix-receipt/v1")
        self.assertNotIn("/", receipt["runtime"]["family"])
        self.assertIn(receipt["observations"]["symlink_behavior"], {"created-but-v0-scan-unsupported", "creation-unsupported", "probe-failed"})
        self.assertEqual(receipt["observations"]["timestamps"], "ignored-by-v0-profile")
        self.assertEqual(receipt["observations"]["mount_layout"], "logical-relative-paths-only")

    def test_committed_receipts_validate_without_machine_paths(self):
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root / "artifact_memory/schemas/core/platform-matrix-receipt.v1.schema.json").read_text(encoding="utf-8"))
        for path in sorted((root / "fixtures/synthetic/platform/receipts").glob("*.json")):
            receipt = json.loads(path.read_text(encoding="utf-8"))
            validate(receipt, schema)
            self.assertNotIn("/Users/", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
