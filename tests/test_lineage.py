import json
import unittest
from pathlib import Path

from artifact_memory.lineage import SOURCE_REF, observe_legacy_file, validate_legacy_observation
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
        schema = json.loads((root / "artifact_memory/schemas/core/legacy-observation.v2.schema.json").read_text(encoding="utf-8"))
        observation = observe_legacy_file({"path": "synthetic/legacy/file.bin", "size": 1024, "created": "2010", "modified": "2010", "sha1": "NONE"}, SOURCE_REF)
        v2_observation = observe_legacy_file({"path": "synthetic/legacy/file.bin", "size": 1024, "created": "2010", "modified": "2010", "sha1": "NONE"}, SOURCE_REF, schema_version="v2")
        validate(v2_observation, schema)
        self.assertEqual(observation["schema_id"], "artifact-memory/legacy-observation/v1")
        self.assertEqual(observation["historical_fields"]["legacy_hash"]["state"], "none-recorded")
        self.assertEqual(observation["historical_fields"]["legacy_hash"]["value"], "NONE")
        self.assertEqual(observation["artifact_identity"], "not-established")

    def test_v1_schema_remains_compatible_with_existing_observations(self):
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root / "artifact_memory/schemas/core/legacy-observation.v1.schema.json").read_text(encoding="utf-8"))
        observation = json.loads((root / "fixtures/synthetic/lineage/v0-legacy-none-observation.json").read_text(encoding="utf-8"))
        validate(observation, schema)
        self.assertIs(validate_legacy_observation(observation), observation)

        broad_v1 = json.loads(json.dumps(observation))
        broad_v1["source_ref"] = "legacy-source://synthetic/other"
        broad_v1["historical_fields"]["legacy_hash"] = {
            "algorithm": "sha-1",
            "state": "sha-1-observed-not-upgraded",
            "value": "legacy-noncanonical-value",
        }
        self.assertIs(validate_legacy_observation(broad_v1), broad_v1)

    def test_malformed_schema_versions_fail_closed(self):
        row = {"path": "synthetic/file", "size": 1, "created": "2010", "modified": "2010", "sha1": "NONE"}
        for version in ([], {}):
            with self.subTest(version=version), self.assertRaises(ValidationFailure) as failure:
                observe_legacy_file(row, SOURCE_REF, schema_version=version)  # type: ignore[arg-type]
            self.assertEqual(failure.exception.code, "legacy-schema-unsupported")

    def test_malformed_conformance_vectors_fail_closed(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            vector_path = Path(directory) / "vectors.json"
            for malformed in ([], {"synthetic": True, "source_ref": SOURCE_REF}, {"synthetic": True, "source_ref": SOURCE_REF, "source_commit": "3a18550fa52526e1a440a1e9264bd9f17638d89e", "rows": [None]}):
                vector_path.write_text(json.dumps(malformed), encoding="utf-8")
                with self.subTest(malformed=malformed), self.assertRaises(ValidationFailure) as failure:
                    run_legacy_lineage_conformance(vector_path)
                self.assertEqual(failure.exception.code, "invalid-vector")

    def test_wrong_row_count_and_order_fail_as_invalid_vectors(self):
        fixture = Path(__file__).resolve().parents[1] / "fixtures/synthetic/lineage/v1/vectors.json"
        valid = json.loads(fixture.read_text(encoding="utf-8"))
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            vector_path = Path(directory) / "vectors.json"
            for rows in (valid["rows"][:1], list(reversed(valid["rows"]))):
                malformed = {**valid, "rows": rows}
                vector_path.write_text(json.dumps(malformed), encoding="utf-8")
                with self.subTest(rows=rows), self.assertRaises(ValidationFailure) as failure:
                    run_legacy_lineage_conformance(vector_path)
                self.assertEqual(failure.exception.code, "invalid-vector")

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
