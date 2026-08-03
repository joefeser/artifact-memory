import json
import subprocess
import unittest
from pathlib import Path

from artifact_memory.schema_resources import load_schema
from artifact_memory.tracemap_adapter import DECLARED_OUTCOMES
from artifact_memory.tracemap_failure_conformance import (
    render_tracemap_failure_conformance,
    run_tracemap_failure_conformance,
)
from artifact_memory.validator import ValidationFailure, validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "tracemap-evidence" / "v1"


class TraceMapFailureConformanceTests(unittest.TestCase):
    def test_checked_machine_and_human_receipts_replay(self):
        receipt = run_tracemap_failure_conformance(FIXTURE)
        expected = json.loads(
            (FIXTURE / "expected-failure-receipt.json").read_text(encoding="utf-8")
        )
        self.assertEqual(receipt, expected)
        self.assertEqual(
            render_tracemap_failure_conformance(receipt),
            (FIXTURE / "failure-receipt.md").read_text(encoding="utf-8"),
        )
        validate(
            receipt,
            load_schema("adapters", "tracemap-failure-conformance-receipt.v1.schema.json"),
        )

    def test_every_declared_outcome_has_one_passing_case(self):
        receipt = run_tracemap_failure_conformance(FIXTURE)
        cases = receipt["cases"]
        self.assertEqual({case["observed_outcome"] for case in cases}, set(DECLARED_OUTCOMES))
        self.assertEqual(len(cases), len(DECLARED_OUTCOMES))
        self.assertTrue(all(case["passed"] for case in cases))
        self.assertFalse(receipt["protected_input_echoed"])
        self.assertFalse(receipt["local_path_echoed"])

    def test_adapter_receipt_schema_binds_diagnostic_to_outcome(self):
        from artifact_memory.tracemap_adapter import _adapter_receipt

        receipt = _adapter_receipt("digest-mismatch")
        receipt["diagnostics"][0]["code"] = "trace-output-invalid"
        with self.assertRaises(ValidationFailure):
            validate(
                receipt,
                load_schema("adapters", "tracemap-adapter-receipt.v1.schema.json"),
            )

    def test_checked_cli(self):
        completed = subprocess.run(
            ["python3", "scripts/run_tracemap_failure_conformance.py", "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
