import json
import unittest
from pathlib import Path

from artifact_memory.benchmark import run_baseline
from artifact_memory.validator import validate


class BenchmarkTests(unittest.TestCase):
    def test_synthetic_baseline_is_bounded_and_schema_valid(self):
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root / "schemas/core/benchmark-receipt.v1.schema.json").read_text(encoding="utf-8"))
        receipt = run_baseline(file_count=8, file_size=128, depth=3)
        validate(receipt, schema)
        self.assertEqual(receipt["bounded_outcomes"]["resource_limit"], "partial")
        self.assertEqual(receipt["bounded_outcomes"]["cancelled"], "cancelled")

        committed = json.loads((root / "fixtures/synthetic/benchmarks/v0-baseline.json").read_text(encoding="utf-8"))
        validate(committed, schema)


if __name__ == "__main__":
    unittest.main()
