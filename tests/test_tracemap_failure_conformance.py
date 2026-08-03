import json
import subprocess
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from artifact_memory.schema_resources import load_schema
from artifact_memory.tracemap_adapter import (
    DECLARED_OUTCOMES,
    bind_trace_map_evidence_receipted,
)
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
        self.assertEqual(set(cases), set(DECLARED_OUTCOMES))
        self.assertEqual(
            {case["observed_outcome"] for case in cases.values()},
            set(DECLARED_OUTCOMES),
        )
        self.assertEqual(len(cases), len(DECLARED_OUTCOMES))
        self.assertTrue(all(case["passed"] for case in cases.values()))
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

    def test_outcome_catalogs_and_normative_cases_stay_in_sync(self):
        adapter_schema = load_schema("adapters", "tracemap-adapter-receipt.v1.schema.json")
        conformance_schema = load_schema(
            "adapters", "tracemap-failure-conformance-receipt.v1.schema.json"
        )
        self.assertEqual(
            set(adapter_schema["properties"]["outcome"]["enum"]),
            set(DECLARED_OUTCOMES),
        )
        cases_schema = conformance_schema["properties"]["cases"]
        self.assertEqual(set(cases_schema["required"]), set(DECLARED_OUTCOMES))
        self.assertEqual(set(cases_schema["properties"]), set(DECLARED_OUTCOMES))
        self.assertEqual(
            set(conformance_schema["properties"]["declared_outcomes"]["const"]),
            set(DECLARED_OUTCOMES),
        )

    def test_conformance_schema_rejects_unknown_and_mismatched_cases(self):
        receipt = run_tracemap_failure_conformance(FIXTURE)
        schema = load_schema(
            "adapters", "tracemap-failure-conformance-receipt.v1.schema.json"
        )
        mutations = []
        unknown_case = deepcopy(receipt)
        unknown_case["cases"]["unknown-outcome"] = unknown_case["cases"].pop(
            "adapter-failed"
        )
        mutations.append(unknown_case)
        unknown_outcome = deepcopy(receipt)
        unknown_outcome["cases"]["adapter-failed"]["observed_outcome"] = "unknown"
        mutations.append(unknown_outcome)
        mismatch = deepcopy(receipt)
        mismatch["cases"]["adapter-failed"]["observed_outcome"] = "complete"
        mutations.append(mismatch)
        for mutation in mutations:
            with self.subTest(mutation=mutation["cases"]), self.assertRaises(
                ValidationFailure
            ):
                validate(mutation, schema)

    def test_receipted_api_contains_schema_validation_failure(self):
        with patch(
            "artifact_memory.tracemap_adapter.validate",
            side_effect=ValidationFailure("synthetic-schema-failure", "synthetic"),
        ):
            binding, receipt = bind_trace_map_evidence_receipted(
                "invalid-source-ref",
                FIXTURE,
                "SyntheticOrders",
                "1" * 40,
                tool_source_commit="2" * 40,
                configuration_digest="sha-256:" + "3" * 64,
            )
        self.assertIsNone(binding)
        self.assertEqual(receipt["outcome"], "adapter-failed")
        self.assertEqual(receipt["validation_state"], "not-validated-runtime-failure")
        self.assertFalse(receipt["protected_input_echoed"])
        self.assertFalse(receipt["local_path_echoed"])
        validate(
            receipt,
            load_schema("adapters", "tracemap-adapter-receipt.v1.schema.json"),
        )

    def test_receipted_api_contains_receipt_construction_failure(self):
        with patch(
            "artifact_memory.tracemap_adapter.receipt_with_digest",
            side_effect=RuntimeError("synthetic construction failure"),
        ):
            binding, receipt = bind_trace_map_evidence_receipted(
                "invalid-source-ref",
                FIXTURE,
                "SyntheticOrders",
                "1" * 40,
                tool_source_commit="2" * 40,
                configuration_digest="sha-256:" + "3" * 64,
            )
        self.assertIsNone(binding)
        self.assertEqual(receipt["outcome"], "adapter-failed")
        self.assertEqual(receipt["validation_state"], "not-validated-runtime-failure")
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
