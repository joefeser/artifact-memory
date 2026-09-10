import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from artifact_memory import (
    projection_integrity_slice,
    search_literal_slice,
    search_ranking_slice,
    search_receipt_slice,
    search_supersession_slice,
)
from artifact_memory.projection_integrity_slice import run_projection_integrity_slice
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import ValidationFailure, validate


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

    def test_new_slice_schemas_bind_top_level_outcome_to_operation_outcomes(self):
        cases = (
            ("projection-integrity", "projection-integrity-slice-receipt.v1.schema.json"),
            ("search-literal", "search-literal-slice-receipt.v1.schema.json"),
            ("search-ranking", "search-ranking-slice-receipt.v1.schema.json"),
            ("search-receipt", "search-receipt-slice-receipt.v1.schema.json"),
            ("search-supersession", "search-supersession-slice-receipt.v1.schema.json"),
        )
        for fixture_name, schema_name in cases:
            with self.subTest(schema=schema_name):
                fixture = ROOT / "fixtures" / "synthetic" / fixture_name / "v1" / "expected-receipt.json"
                receipt = json.loads(fixture.read_text(encoding="utf-8"))
                schema = load_schema("core", schema_name)

                complete_with_failure = json.loads(json.dumps(receipt))
                complete_with_failure["operations"][0]["outcome"] = "failed"
                with self.assertRaises(ValidationFailure):
                    validate(complete_with_failure, schema)

                failed_without_failure = json.loads(json.dumps(receipt))
                failed_without_failure["outcome"] = "failed"
                with self.assertRaises(ValidationFailure):
                    validate(failed_without_failure, schema)

    def test_slice_runners_emit_schema_valid_failed_receipts(self):
        cases = (
            (
                projection_integrity_slice,
                "projection-integrity",
                "projection-integrity-slice-receipt.v1.schema.json",
                "run_projection_integrity_slice",
            ),
            (
                search_literal_slice,
                "search-literal",
                "search-literal-slice-receipt.v1.schema.json",
                "run_search_literal_slice",
            ),
            (
                search_ranking_slice,
                "search-ranking",
                "search-ranking-slice-receipt.v1.schema.json",
                "run_search_ranking_slice",
            ),
            (
                search_receipt_slice,
                "search-receipt",
                "search-receipt-slice-receipt.v1.schema.json",
                "run_search_receipt_slice",
            ),
            (
                search_supersession_slice,
                "search-supersession",
                "search-supersession-slice-receipt.v1.schema.json",
                "run_search_supersession_slice",
            ),
        )
        for module, fixture_name, schema_name, runner_name in cases:
            with self.subTest(slice=fixture_name), tempfile.TemporaryDirectory() as temporary:
                fixture = ROOT / "fixtures" / "synthetic" / fixture_name / "v1"
                project_records = module.project_records

                def failed_projection(*args, **kwargs):
                    return {**project_records(*args, **kwargs), "outcome": "failed"}

                with mock.patch.object(module, "project_records", side_effect=failed_projection):
                    receipt = getattr(module, runner_name)(fixture, Path(temporary))
                self.assertEqual(receipt["outcome"], "failed")
                self.assertIn("failed", {operation["outcome"] for operation in receipt["operations"]})
                validate(receipt, load_schema("core", schema_name))


if __name__ == "__main__":
    unittest.main()
