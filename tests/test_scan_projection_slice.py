import json
import tempfile
import unittest
from pathlib import Path

from artifact_memory.scan_projection_slice import run_scan_projection_slice
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "scan-projection" / "v1"


class ScanProjectionSliceTests(unittest.TestCase):
    def test_checked_in_receipt_replays_exactly(self):
        with tempfile.TemporaryDirectory() as temporary:
            receipt = run_scan_projection_slice(FIXTURE, Path(temporary))
        expected = json.loads((FIXTURE / "expected-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt, expected)
        self.assertEqual(receipt["outcome"], "complete")
        self.assertTrue(receipt["projection"]["logical_rebuild_equivalent"])
        validate(receipt, load_schema("core", "scan-projection-slice-receipt.v1.schema.json"))


if __name__ == "__main__":
    unittest.main()
