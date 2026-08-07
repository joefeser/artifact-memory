import json
import subprocess
import unittest
from copy import deepcopy
from pathlib import Path

from artifact_memory.exchange_conformance import (
    OUTCOMES,
    render_exchange_conformance_receipt,
    run_exchange_conformance,
)
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import ValidationFailure, validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "exchange" / "v2"


class ExchangeConformanceTests(unittest.TestCase):
    def test_checked_machine_and_human_receipts_replay(self):
        receipt = run_exchange_conformance(FIXTURE)
        expected = json.loads(
            (FIXTURE / "expected-receipt.json").read_text(encoding="utf-8")
        )
        self.assertEqual(receipt, expected)
        self.assertEqual(
            render_exchange_conformance_receipt(receipt),
            (FIXTURE / "receipt.md").read_text(encoding="utf-8"),
        )

    def test_all_declared_outcomes_are_schema_bound(self):
        receipt = run_exchange_conformance(FIXTURE)
        self.assertEqual(tuple(receipt["cases"]), OUTCOMES)
        self.assertTrue(all(case["passed"] for case in receipt["cases"].values()))
        schema = load_schema("core", "exchange-conformance-receipt.v1.schema.json")
        mismatch = deepcopy(receipt)
        mismatch["cases"]["quarantined"]["observed_outcome"] = "rejected"
        with self.assertRaises(ValidationFailure):
            validate(mismatch, schema)

    def test_vector_requires_exactly_two_schema_valid_records(self):
        vectors = json.loads((FIXTURE / "vectors.json").read_text(encoding="utf-8"))
        vectors["records"] = vectors["records"][:1]
        schema = load_schema("core", "exchange-conformance-vectors.v1.schema.json")
        with self.assertRaises(ValidationFailure):
            validate(vectors, schema)

    def test_checked_cli(self):
        completed = subprocess.run(
            ["python3", "scripts/run_exchange_conformance.py", "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
