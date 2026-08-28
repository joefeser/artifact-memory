import json
import tempfile
import unittest
from pathlib import Path

from artifact_memory.schema_resources import load_schema
from artifact_memory.search_ranking_slice import run_search_ranking_slice
from artifact_memory.validator import validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "search-ranking" / "v1"


class SearchRankingSliceTests(unittest.TestCase):
    def test_checked_in_receipt_replays_exactly(self):
        with tempfile.TemporaryDirectory() as temporary:
            receipt = run_search_ranking_slice(FIXTURE, Path(temporary))
        expected = json.loads((FIXTURE / "expected-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt, expected)
        self.assertEqual(receipt["outcome"], "complete")
        ranked = receipt["ranked_search"]
        self.assertNotEqual(ranked["paired_ranked_record_ids"], ranked["unranked_record_ids"])
        self.assertNotEqual(ranked["full_ranked_record_ids"], ranked["paired_ranked_record_ids"])
        validate(receipt, load_schema("core", "search-ranking-slice-receipt.v1.schema.json"))


if __name__ == "__main__":
    unittest.main()
