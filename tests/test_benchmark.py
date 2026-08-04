import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from artifact_memory.benchmark import (
    DEFAULT_PROFILE,
    _make_corpus,
    _synthetic_concurrent_change,
    invariant_projection,
    run_baseline,
    validate_benchmark_receipt,
    validate_profile,
)
from artifact_memory.canonical import receipt_with_digest
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import ValidationFailure, validate


ROOT = Path(__file__).resolve().parents[1]


class BenchmarkTests(unittest.TestCase):
    def _small_profile(self):
        return {
            **DEFAULT_PROFILE,
            "profile_id": "synthetic-unit-resource-baseline",
            "file_count": 12,
            "small_file_size_bytes": 128,
            "large_file_size_bytes": 2 * 1024 * 1024,
            "depth": 3,
            "projection_record_count": 12,
            "scan_byte_limit": 256,
            "scan_entry_limit": 2,
            "nested_archive_depth": 3,
        }

    def test_synthetic_baseline_covers_resource_and_failure_outcomes(self):
        receipt = run_baseline(self._small_profile())
        validate(receipt, load_schema("core", "benchmark-receipt.v2.schema.json"))
        self.assertEqual(receipt["bounded_outcomes"]["byte_limit"], {"outcome": "partial", "diagnostic": "resource-limit"})
        self.assertEqual(receipt["bounded_outcomes"]["entry_limit"], {"outcome": "partial", "diagnostic": "resource-limit"})
        self.assertEqual(receipt["bounded_outcomes"]["cancellation"], {"outcome": "cancelled", "diagnostic": "cancelled"})
        self.assertEqual(receipt["bounded_outcomes"]["unavailable_root"]["outcome"], "failed")
        self.assertEqual(receipt["bounded_outcomes"]["concurrent_change"]["diagnostic"], "unstable")
        self.assertEqual(receipt["bounded_outcomes"]["nested_archive"]["recursion"], "not-attempted")
        self.assertEqual(receipt["measurements"]["hashing_bytes"], receipt["corpus"]["total_file_bytes"])
        self.assertEqual(receipt["resource_policy"]["large_file_hash_exemption_bytes"], 0)

    def test_profile_is_exact_and_bounded_before_allocating(self):
        for mutation in (
            lambda value: value.update(extra=True),
            lambda value: value.update(file_count=True),
            lambda value: value.update(depth=65),
            lambda value: value.update(large_file_size_bytes=513 * 1024 * 1024),
            lambda value: value.update(scan_byte_limit=MAX_TOTAL),
            lambda value: value.update(scan_entry_limit=value["file_count"]),
            lambda value: value.update(
                file_count=60_000, projection_record_count=60_000
            ),
            lambda value: value.update(archive_max_uncompressed_bytes=1),
        ):
            profile = deepcopy(self._small_profile())
            mutation(profile)
            with self.subTest(profile=profile), self.assertRaises(ValidationFailure) as failure:
                validate_profile(profile)
            self.assertEqual(failure.exception.code, "benchmark-profile-invalid")

    def test_checked_baseline_contract_and_cross_run_invariants(self):
        profile = json.loads((ROOT / "fixtures/synthetic/benchmarks/v1/profile.json").read_text(encoding="utf-8"))
        committed = json.loads((ROOT / "fixtures/synthetic/benchmarks/v1/expected-receipt.json").read_text(encoding="utf-8"))
        validate_profile(profile)
        validate_benchmark_receipt(committed)
        replay = run_baseline(profile)
        self.assertEqual(replay["outcome"], "complete")
        self.assertEqual(invariant_projection(replay), invariant_projection(committed))

        tampered = deepcopy(committed)
        tampered["measurements"]["scan_wall_microseconds"] += 1
        with self.assertRaises(ValidationFailure) as failure:
            validate_benchmark_receipt(tampered)
        self.assertEqual(failure.exception.code, "benchmark-receipt-id-mismatch")

        forged_body = {
            key: deepcopy(value)
            for key, value in committed.items()
            if key not in {"schema_id", "receipt_id"}
        }
        forged_body["claims"][0]["summary"] = "unsupported replacement claim"
        forged = receipt_with_digest(
            committed["schema_id"], "benchmark-receipt://", forged_body
        )
        with self.assertRaises(ValidationFailure) as failure:
            validate_benchmark_receipt(forged)
        self.assertEqual(failure.exception.code, "benchmark-claim-binding-invalid")

    def test_unsupported_platform_fails_before_benchmark_allocation(self):
        with (
            patch("artifact_memory.benchmark.platform.system", return_value="FreeBSD"),
            patch("artifact_memory.benchmark._make_corpus") as make_corpus,
            self.assertRaises(ValidationFailure) as failure,
        ):
            run_baseline(self._small_profile())
        self.assertEqual(failure.exception.code, "benchmark-unsupported-platform")
        make_corpus.assert_not_called()

    def test_single_file_corpus_skips_unused_small_payload_allocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            written = _make_corpus(
                Path(temporary),
                file_count=1,
                small_file_size=MAX_TOTAL,
                large_file_size=1,
                depth=1,
            )
        self.assertEqual(written, 1)

    def test_missing_concurrent_case_has_typed_failure(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "artifact_memory.benchmark.run_scan_conformance",
                return_value={"cases": []},
            ),
            self.assertRaises(ValidationFailure) as failure,
        ):
            _synthetic_concurrent_change(Path(temporary))
        self.assertEqual(
            failure.exception.code, "benchmark-conformance-case-missing"
        )


MAX_TOTAL = 513 * 1024 * 1024


if __name__ == "__main__":
    unittest.main()
