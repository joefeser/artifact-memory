import json
import unittest
from pathlib import Path

from artifact_memory.codex_history_conformance import run_codex_history_conformance


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "codex-history" / "v2"


class CodexHistoryConformanceTests(unittest.TestCase):
    def test_receipt_matches_checked_synthetic_evidence(self):
        expected = json.loads((FIXTURE / "expected-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(run_codex_history_conformance(FIXTURE), expected)

    def test_released_v1_receipt_remains_unchanged_and_schema_valid(self):
        legacy = ROOT / "fixtures" / "synthetic" / "codex-history" / "v1"
        receipt = json.loads((legacy / "expected-receipt.json").read_text(encoding="utf-8"))
        schema = json.loads(
            (ROOT / "artifact_memory/schemas/core/codex-history-conformance-receipt.v1.schema.json").read_text(encoding="utf-8")
        )
        from artifact_memory.validator import validate

        validate(receipt, schema)
        self.assertEqual(receipt["context_record_count"], 4)


if __name__ == "__main__":
    unittest.main()
