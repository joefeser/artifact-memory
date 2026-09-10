import json
import tempfile
import unittest
from pathlib import Path

from artifact_memory.schema_resources import load_schema
from artifact_memory.search_supersession_slice import run_search_supersession_slice
from artifact_memory.validator import validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "search-supersession" / "v1"


class SearchSupersessionSliceTests(unittest.TestCase):
    def test_checked_in_receipt_replays_exactly(self):
        with tempfile.TemporaryDirectory() as temporary:
            receipt = run_search_supersession_slice(FIXTURE, Path(temporary))
        expected = json.loads((FIXTURE / "expected-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt, expected)
        self.assertEqual(receipt["outcome"], "complete")
        filter_state = receipt["supersession_filter"]
        self.assertEqual(len(filter_state["default_record_ids"]), 2)
        self.assertEqual(len(filter_state["filtered_record_ids"]), 1)
        validate(receipt, load_schema("core", "search-supersession-slice-receipt.v1.schema.json"))


if __name__ == "__main__":
    unittest.main()
