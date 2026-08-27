import json
import tempfile
import unittest
from pathlib import Path

from artifact_memory.schema_resources import load_schema
from artifact_memory.search_literal_slice import run_search_literal_slice
from artifact_memory.validator import validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "search-literal" / "v1"


class SearchLiteralSliceTests(unittest.TestCase):
    def test_checked_in_receipt_replays_exactly(self):
        with tempfile.TemporaryDirectory() as temporary:
            receipt = run_search_literal_slice(FIXTURE, Path(temporary))
        expected = json.loads((FIXTURE / "expected-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt, expected)
        self.assertEqual(receipt["outcome"], "complete")
        self.assertEqual(receipt["literal_search"]["adjacent_record_ids"], ["record://synthetic/search-literal-0001"])
        validate(receipt, load_schema("core", "search-literal-slice-receipt.v1.schema.json"))


if __name__ == "__main__":
    unittest.main()
