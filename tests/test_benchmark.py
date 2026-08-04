import json
import unittest
from copy import deepcopy
from pathlib import Path

from artifact_memory.benchmark import DEFAULT_PROFILE, invariant_projection, run_baseline, validate_benchmark_receipt, validate_profile
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
        replay = run_baseline(self._small_profile())
        self.assertEqual(replay["outcome"], "complete")
        self.assertNotIn("measurements", invariant_projection(replay))

        tampered = deepcopy(committed)
        tampered["measurements"]["scan_wall_microseconds"] += 1
        with self.assertRaises(ValidationFailure) as failure:
            validate_benchmark_receipt(tampered)
        self.assertEqual(failure.exception.code, "benchmark-receipt-id-mismatch")


MAX_TOTAL = 513 * 1024 * 1024


if __name__ == "__main__":
    unittest.main()
