import json
import tempfile
import unittest
from pathlib import Path

from artifact_memory.projection_integrity_slice import run_projection_integrity_slice
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "projection-integrity" / "v1"


class ProjectionIntegritySliceTests(unittest.TestCase):
    def test_checked_in_receipt_replays_exactly(self):
        with tempfile.TemporaryDirectory() as temporary:
            receipt = run_projection_integrity_slice(FIXTURE, Path(temporary))
        expected = json.loads((FIXTURE / "expected-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt, expected)
        self.assertEqual(receipt["outcome"], "complete")
        self.assertEqual(
            set(receipt["integrity_gate"]["gated_surface_outcomes"].values()),
            {"projection-unavailable"},
        )
        validate(receipt, load_schema("core", "projection-integrity-slice-receipt.v1.schema.json"))


if __name__ == "__main__":
    unittest.main()
