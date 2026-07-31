import json
import unittest
from pathlib import Path

from artifact_memory.context_export_slice import run_context_export_slice
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "context-export" / "v1"


class ContextExportSliceTests(unittest.TestCase):
    def test_checked_in_receipt_replays_exactly(self):
        receipt = run_context_export_slice(FIXTURE)
        expected = json.loads((FIXTURE / "expected-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt, expected)
        self.assertEqual(receipt["outcome"], "complete")
        self.assertEqual(receipt["mutation_authority"], "absent")
        validate(receipt, load_schema("core", "context-export-slice-receipt.v1.schema.json"))


if __name__ == "__main__":
    unittest.main()
