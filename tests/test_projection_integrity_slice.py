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

    def test_projection_creation_failures_propagate_without_slice_receipts(self):
        cases = (
            (projection_integrity_slice, "projection-integrity", "run_projection_integrity_slice"),
            (search_literal_slice, "search-literal", "run_search_literal_slice"),
            (search_ranking_slice, "search-ranking", "run_search_ranking_slice"),
            (search_receipt_slice, "search-receipt", "run_search_receipt_slice"),
            (search_supersession_slice, "search-supersession", "run_search_supersession_slice"),
        )
        for module, fixture_name, runner_name in cases:
            with self.subTest(slice=fixture_name), tempfile.TemporaryDirectory() as temporary:
                fixture = ROOT / "fixtures" / "synthetic" / fixture_name / "v1"
                failure = ValidationFailure("projection-unavailable", "synthetic projection failure")
                with mock.patch.object(module, "project_records", side_effect=failure):
                    with self.assertRaisesRegex(ValidationFailure, "synthetic projection failure"):
                        getattr(module, runner_name)(fixture, Path(temporary))

    def test_post_projection_failures_emit_schema_valid_failed_receipts(self):
        def run(module, fixture_name, runner_name):
            fixture = ROOT / "fixtures" / "synthetic" / fixture_name / "v1"
            with tempfile.TemporaryDirectory() as temporary:
                return getattr(module, runner_name)(fixture, Path(temporary))

        receipts = []

        original_integrity_search = projection_integrity_slice.search_records
        clean_control_reads = 0

        def mismatched_clean_control(*args, **kwargs):
            nonlocal clean_control_reads
            result = original_integrity_search(*args, **kwargs)
            if args[1] == "canonical":
                clean_control_reads += 1
                if clean_control_reads == 2:
                    return []
            return result

        with mock.patch.object(
            projection_integrity_slice,
            "search_records",
            side_effect=mismatched_clean_control,
        ):
            receipts.append(
                (
                    "projection-integrity-slice-receipt.v1.schema.json",
                    run(projection_integrity_slice, "projection-integrity", "run_projection_integrity_slice"),
                )
            )

        original_literal_search = search_literal_slice.search_records
        literal_miss_injected = False

        def miss_first_literal_check(*args, **kwargs):
            nonlocal literal_miss_injected
            if not literal_miss_injected and args[1] == search_literal_slice.HYPHENATED_QUERY and kwargs.get("literal"):
                literal_miss_injected = True
                return []
            return original_literal_search(*args, **kwargs)

        with mock.patch.object(search_literal_slice, "search_records", side_effect=miss_first_literal_check):
            receipts.append(
                (
                    "search-literal-slice-receipt.v1.schema.json",
                    run(search_literal_slice, "search-literal", "run_search_literal_slice"),
                )
            )

        original_ranking_search = search_ranking_slice.search_records
        unranked_miss_injected = False

        def miss_first_unranked_check(*args, **kwargs):
            nonlocal unranked_miss_injected
            if not unranked_miss_injected and args[1] == search_ranking_slice.RANKING_QUERY and not kwargs.get("rank"):
                unranked_miss_injected = True
                return []
            return original_ranking_search(*args, **kwargs)

        with mock.patch.object(search_ranking_slice, "search_records", side_effect=miss_first_unranked_check):
            receipts.append(
                (
                    "search-ranking-slice-receipt.v1.schema.json",
                    run(search_ranking_slice, "search-ranking", "run_search_ranking_slice"),
                )
            )

        original_search_receipt = search_receipt_slice.search_receipt

        def report_wrong_tamper_code(*args, **kwargs):
            if Path(args[0]).name == "tampered.sqlite":
                raise ValidationFailure("query-invalid", "synthetic wrong tamper outcome")
            return original_search_receipt(*args, **kwargs)

        with mock.patch.object(search_receipt_slice, "search_receipt", side_effect=report_wrong_tamper_code):
            receipts.append(
                (
                    "search-receipt-slice-receipt.v1.schema.json",
                    run(search_receipt_slice, "search-receipt", "run_search_receipt_slice"),
                )
            )

        with mock.patch.object(search_supersession_slice, "sha256_bytes", return_value="sha-256:" + "0" * 64):
            receipts.append(
                (
                    "search-supersession-slice-receipt.v1.schema.json",
                    run(search_supersession_slice, "search-supersession", "run_search_supersession_slice"),
                )
            )

        for schema_name, receipt in receipts:
            with self.subTest(schema=schema_name):
                self.assertEqual(receipt["outcome"], "failed")
                self.assertIn("failed", {operation["outcome"] for operation in receipt["operations"]})
                validate(receipt, load_schema("core", schema_name))


if __name__ == "__main__":
    unittest.main()
