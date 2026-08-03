import json
import unittest
from pathlib import Path

from artifact_memory.lineage import SOURCE_REF, observe_legacy_file
from artifact_memory.legacy_lineage_conformance import render_legacy_lineage_receipt, run_legacy_lineage_conformance
from artifact_memory.validator import ValidationFailure, validate


class LineageTests(unittest.TestCase):
    def test_checked_legacy_lineage_fixture(self):
        fixture = Path(__file__).resolve().parents[1] / "fixtures/synthetic/lineage/v1"
        receipt = run_legacy_lineage_conformance(fixture / "vectors.json")
        expected = json.loads((fixture / "expected-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt, expected)
        self.assertEqual(render_legacy_lineage_receipt(receipt), (fixture / "receipt.md").read_text(encoding="utf-8"))

    def test_none_hash_is_observed_without_identity_upgrade(self):
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root / "artifact_memory/schemas/core/legacy-observation.v1.schema.json").read_text(encoding="utf-8"))
        observation = observe_legacy_file({"path": "synthetic/legacy/file.bin", "size": 1024, "created": "2010", "modified": "2010", "sha1": "NONE"}, SOURCE_REF)
        validate(observation, schema)
        self.assertEqual(observation["historical_fields"]["legacy_hash"]["state"], "none-recorded")
        self.assertEqual(observation["historical_fields"]["legacy_hash"]["value"], "NONE")
        self.assertEqual(observation["artifact_identity"], "not-established")

    def test_sha1_remains_historical_and_establishes_no_identity(self):
        observation = observe_legacy_file(
            {"path": "synthetic/legacy/file.bin", "size": 1024, "created": "2010", "modified": "2010", "sha1": "0123456789abcdef0123456789abcdef01234567"},
            SOURCE_REF,
        )
        self.assertEqual(observation["historical_fields"]["legacy_hash"]["state"], "sha-1-observed-not-upgraded")
        self.assertEqual(observation["content_identity"], "not-established")
        self.assertNotIn("sha-256", json.dumps(observation))

    def test_missing_or_malformed_hash_fails_closed(self):
        base = {"path": "synthetic/legacy/file.bin", "size": 1024, "created": "2010", "modified": "2010"}
        for value in (None, "none", "short"):
            row = dict(base)
            if value is not None:
                row["sha1"] = value
            with self.subTest(value=value), self.assertRaises(ValidationFailure) as failure:
                observe_legacy_file(row, SOURCE_REF)
            self.assertEqual(failure.exception.code, "legacy-evidence-insufficient")

    def test_unattributed_source_fails_closed(self):
        with self.assertRaises(ValidationFailure) as failure:
            observe_legacy_file({"path": "synthetic/file", "size": 1, "created": "2010", "modified": "2010", "sha1": "NONE"}, "https://example.invalid/source")
        self.assertEqual(failure.exception.code, "legacy-source-unsupported")


if __name__ == "__main__":
    unittest.main()
