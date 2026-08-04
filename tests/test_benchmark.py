import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from artifact_memory.benchmark import (
    DEFAULT_PROFILE,
    MAX_BENCHMARK_BYTES,
    MAX_BENCHMARK_DEPTH,
    MAX_BENCHMARK_FILES,
    MAX_BENCHMARK_RECORDS,
    RECORD_GENERATOR_ID,
    _make_corpus,
    _synthetic_concurrent_change,
    invariant_projection,
    run_baseline,
    run_baseline_v2,
    validate_benchmark_receipt,
    validate_profile,
)
from artifact_memory.canonical import canonical_bytes, receipt_with_digest, sha256_bytes
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
        receipt = run_baseline_v2(self._small_profile())
        validate(receipt, load_schema("core", "benchmark-receipt.v2.schema.json"))
        self.assertEqual(receipt["bounded_outcomes"]["byte_limit"], {"outcome": "partial", "diagnostic": "resource-limit"})
        self.assertEqual(receipt["bounded_outcomes"]["entry_limit"], {"outcome": "partial", "diagnostic": "resource-limit"})
        self.assertEqual(receipt["bounded_outcomes"]["cancellation"], {"outcome": "cancelled", "diagnostic": "cancelled"})
        self.assertEqual(receipt["bounded_outcomes"]["unavailable_root"]["outcome"], "failed")
        self.assertEqual(receipt["bounded_outcomes"]["concurrent_change"]["diagnostic"], "unstable")
        self.assertEqual(receipt["bounded_outcomes"]["nested_archive"]["recursion"], "not-attempted")
        self.assertEqual(receipt["measurements"]["hashing_bytes"], receipt["corpus"]["total_file_bytes"])
        self.assertEqual(receipt["resource_policy"]["large_file_hash_exemption_bytes"], 0)
        self.assertEqual(
            receipt["corpus"]["projection_input"]["kind"], "generated-ephemeral"
        )
        self.assertEqual(
            receipt["corpus"]["projection_input"]["generator_id"],
            RECORD_GENERATOR_ID,
        )

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
            lambda value: value.update(projection_record_generator="unsupported"),
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
        validate_benchmark_receipt(committed, expected_profile=profile)
        replay = run_baseline_v2(profile)
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

        substituted = deepcopy(committed)
        substituted_profile = {**profile, "profile_id": "substituted-profile"}
        substituted_body = {
            key: deepcopy(value)
            for key, value in substituted.items()
            if key not in {"schema_id", "receipt_id"}
        }
        substituted_body["profile_id"] = substituted_profile["profile_id"]
        substituted_body["profile_digest"] = sha256_bytes(
            canonical_bytes(substituted_profile)
        )
        for claim in substituted_body["claims"]:
            claim["provenance_ref"] = substituted_body["profile_digest"]
        substituted = receipt_with_digest(
            committed["schema_id"], "benchmark-receipt://", substituted_body
        )
        validate_benchmark_receipt(substituted)
        with self.assertRaises(ValidationFailure) as failure:
            validate_benchmark_receipt(substituted, expected_profile=profile)
        self.assertEqual(failure.exception.code, "benchmark-profile-mismatch")

    def test_legacy_callable_and_receipt_contract_remain_supported(self):
        receipt = run_baseline(8, 128, 2)
        self.assertEqual(receipt["schema_id"], "artifact-memory/benchmark-receipt/v1")
        self.assertEqual(receipt["corpus"]["file_count"], 8)
        validate_benchmark_receipt(receipt)

        retained = json.loads(
            (ROOT / "fixtures/synthetic/benchmarks/v0-baseline.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            retained["schema_id"], "artifact-memory/benchmark-receipt/v1"
        )
        validate_benchmark_receipt(retained)

    def test_sqlite_measurement_requires_matching_validated_projection(self):
        with (
            patch(
                "artifact_memory.benchmark.projection_metadata",
                return_value={
                    "source_record_set_digest": "sha-256:" + "0" * 64,
                    "record_count": 0,
                },
            ),
            self.assertRaises(ValidationFailure) as failure,
        ):
            run_baseline_v2(self._small_profile())
        self.assertEqual(failure.exception.code, "benchmark-run-failed")

    def test_profile_schema_direct_bounds_match_runtime_constants(self):
        schema = load_schema("core", "benchmark-profile.v1.schema.json")
        properties = schema["properties"]
        self.assertEqual(
            properties["projection_record_generator"]["const"],
            RECORD_GENERATOR_ID,
        )
        self.assertEqual(properties["file_count"]["maximum"], MAX_BENCHMARK_FILES)
        self.assertEqual(
            properties["projection_record_count"]["maximum"],
            MAX_BENCHMARK_RECORDS,
        )
        self.assertEqual(properties["depth"]["maximum"], MAX_BENCHMARK_DEPTH)
        self.assertEqual(
            properties["nested_archive_depth"]["maximum"], MAX_BENCHMARK_DEPTH
        )
        for name in (
            "small_file_size_bytes",
            "large_file_size_bytes",
            "scan_byte_limit",
            "archive_max_uncompressed_bytes",
        ):
            self.assertEqual(properties[name]["maximum"], MAX_BENCHMARK_BYTES)

    def test_check_and_write_modes_are_mutually_exclusive(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/run_benchmark.py"),
                "--check",
                "--write",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("not allowed with argument", result.stderr)

    def test_unsupported_platform_fails_before_benchmark_allocation(self):
        with (
            patch("artifact_memory.benchmark.platform.system", return_value="FreeBSD"),
            patch("artifact_memory.benchmark._make_corpus") as make_corpus,
            self.assertRaises(ValidationFailure) as failure,
        ):
            run_baseline_v2(self._small_profile())
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
