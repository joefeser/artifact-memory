import json
import unittest
from pathlib import Path

from artifact_memory.codex_history_conformance import run_codex_history_conformance


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "codex-history" / "v1"


class CodexHistoryConformanceTests(unittest.TestCase):
    def test_receipt_matches_checked_synthetic_evidence(self):
        expected = json.loads((FIXTURE / "expected-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(run_codex_history_conformance(FIXTURE), expected)


if __name__ == "__main__":
    unittest.main()
