import json
import unittest
from pathlib import Path

from artifact_memory.authenticity_conformance import render_authenticity_receipt, run_authenticity_conformance
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "security"


class AuthenticityConformanceTests(unittest.TestCase):
    def test_checked_in_machine_and_human_receipts_replay_exactly(self):
        receipt = run_authenticity_conformance(FIXTURE / "authenticity-v0-v2.json")
        expected = json.loads((FIXTURE / "authenticity-v0-v2-expected-receipt.json").read_text(encoding="utf-8"))
        expected_markdown = (FIXTURE / "authenticity-v0-v2-receipt.md").read_text(encoding="utf-8")
        self.assertEqual(receipt, expected)
        self.assertEqual(render_authenticity_receipt(receipt), expected_markdown)
        validate(receipt, load_schema("core", "authenticity-conformance-receipt.v1.schema.json"))


if __name__ == "__main__":
    unittest.main()
