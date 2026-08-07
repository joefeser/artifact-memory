import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from artifact_memory.projection import (
    logical_projection_snapshot,
    project_records,
    projection_metadata,
    records_with_provenance,
    related_records,
    search_records,
)
from artifact_memory.validator import ValidationFailure


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "contracts" / "v0-valid-record.json"


class ProjectionTests(unittest.TestCase):
    def test_projection_is_rebuildable_and_queryable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_record = json.loads(FIXTURE.read_text(encoding="utf-8"))
            first_record["relationships"] = [{"type": "related-to", "target_ref": "record://synthetic/record-0002"}]
            second_record = {
                "schema_id": "artifact-memory/knowledge-record/v1",
                "record_id": "record://synthetic/record-0002",
                "record_type": "decision",
                "lifecycle": "accepted",
                "meaning": {"summary": "Synthetic projection decision"},
                "artifact_refs": [],
                "provenance": [{"kind": "author", "source_ref": "fixture://synthetic/contracts/v0"}],
                "sensitivity": "public",
            }
            one = root / "one.json"
            two = root / "two.json"
            one.write_text(json.dumps(first_record), encoding="utf-8")
            two.write_text(json.dumps(second_record), encoding="utf-8")
            first_out = root / "first"
            second_out = root / "second"
            first_receipt = project_records([two, one], first_out)
            second_receipt = project_records([one, two], second_out)
            self.assertEqual(first_receipt["source_record_set_digest"], second_receipt["source_record_set_digest"])
            self.assertEqual((first_out / "records.ndjson").read_bytes(), (second_out / "records.ndjson").read_bytes())
            self.assertEqual(search_records(first_out / "records.sqlite", "projection"), ["record://synthetic/record-0002"])
            self.assertEqual(related_records(first_out / "records.sqlite", "record://synthetic/record-0001"), [{"type": "related-to", "target_ref": "record://synthetic/record-0002"}])
            self.assertEqual(
                records_with_provenance(first_out / "records.sqlite", "fixture://synthetic/contracts/v0"),
                [
                    {
                        "record_id": "record://synthetic/record-0001",
                        "kind": "author",
                        "source_ref": "fixture://synthetic/contracts/v0",
                    },
                    {
                        "record_id": "record://synthetic/record-0002",
                        "kind": "author",
                        "source_ref": "fixture://synthetic/contracts/v0",
                    },
                ],
            )
            metadata = projection_metadata(first_out / "records.sqlite")
            self.assertEqual(metadata["projection_schema_id"], "artifact-memory/sqlite-projection/v1")
            self.assertEqual(metadata["user_version"], 1)
            self.assertEqual(metadata["source_record_set_digest"], first_receipt["source_record_set_digest"])
            self.assertEqual(metadata["record_count"], 2)
            self.assertNotIn(str(root).encode("utf-8"), (first_out / "records.sqlite").read_bytes())
            with self.assertRaises(ValidationFailure) as raised:
                search_records(first_out / "records.sqlite", '"')
            self.assertEqual(raised.exception.code, "query-invalid")
            first_snapshot = logical_projection_snapshot(first_out / "records.sqlite")
            for name in ("records.ndjson", "records.sqlite", "projection-receipt.json"):
                (first_out / name).unlink()
            rebuilt_receipt = project_records([one, two], first_out)
            self.assertEqual(rebuilt_receipt, first_receipt)
            self.assertEqual(logical_projection_snapshot(first_out / "records.sqlite"), first_snapshot)
            self.assertEqual(search_records(first_out / "records.sqlite", "projection"), ["record://synthetic/record-0002"])

    def test_projection_rejects_invalid_canonical_record_before_writing_views(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            invalid = root / "invalid.json"
            invalid.write_text('{"schema_id":"artifact-memory/knowledge-record/v1"}', encoding="utf-8")
            output = root / "generated"
            with self.assertRaises(ValidationFailure) as raised:
                project_records([invalid], output)
            self.assertEqual(raised.exception.code, "record-rejected")
            self.assertFalse(output.exists())

    def test_projection_rejects_unknown_required_extensions_before_writing_views(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record = json.loads(FIXTURE.read_text(encoding="utf-8"))
            record["extensions"] = {
                "https://synthetic.example/required": {
                    "version": "v1",
                    "required": True,
                    "value": {"synthetic": True},
                }
            }
            record_path = root / "required.json"
            record_path.write_text(json.dumps(record), encoding="utf-8")
            output = root / "generated"

            with self.assertRaises(ValidationFailure) as raised:
                project_records([record_path], output)

            self.assertEqual(raised.exception.code, "required-extension-unsupported")
            self.assertFalse(output.exists())

    def test_projection_rejects_malformed_non_dict_extension_declarations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record = json.loads(FIXTURE.read_text(encoding="utf-8"))
            record["extensions"] = {"https://synthetic.example/malformed": "not-a-declaration-object"}
            record_path = root / "malformed.json"
            record_path.write_text(json.dumps(record), encoding="utf-8")
            output = root / "generated"

            with self.assertRaises(ValidationFailure) as raised:
                project_records([record_path], output)

            self.assertEqual(raised.exception.code, "type-mismatch")
            self.assertFalse(output.exists())

    def test_projection_preserves_unknown_optional_extensions_in_generated_views(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record = json.loads(FIXTURE.read_text(encoding="utf-8"))
            declaration = {
                "version": "v1",
                "required": False,
                "value": {"synthetic": True},
            }
            record["extensions"] = {"https://synthetic.example/optional": declaration}
            record_path = root / "optional.json"
            record_path.write_text(json.dumps(record), encoding="utf-8")
            output = root / "generated"

            receipt = project_records([record_path], output)
            ndjson_record = json.loads((output / "records.ndjson").read_text(encoding="utf-8"))
            connection = sqlite3.connect(output / "records.sqlite")
            try:
                sqlite_record = json.loads(
                    connection.execute("SELECT record_json FROM records").fetchone()[0]
                )
            finally:
                connection.close()

            self.assertEqual(receipt["outcome"], "complete")
            self.assertEqual(ndjson_record, sqlite_record)
            self.assertEqual(
                ndjson_record["extensions"]["https://synthetic.example/optional"],
                declaration,
            )

    def test_querying_missing_projection_is_read_only_and_typed(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing.sqlite"
            with self.assertRaises(ValidationFailure) as raised:
                search_records(missing, "synthetic")
            self.assertEqual(raised.exception.code, "projection-unavailable")
            self.assertFalse(missing.exists())

    def test_projection_queries_reject_wrong_version_and_malformed_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrong_version_output = root / "wrong-version"
            project_records([FIXTURE], wrong_version_output)
            wrong_version = wrong_version_output / "records.sqlite"
            connection = sqlite3.connect(wrong_version)
            connection.execute("PRAGMA user_version = 999")
            connection.commit()
            connection.close()
            with self.assertRaises(ValidationFailure) as raised:
                search_records(wrong_version, "synthetic")
            self.assertEqual(raised.exception.code, "projection-schema-mismatch")

            malformed = root / "malformed.sqlite"
            connection = sqlite3.connect(malformed)
            connection.execute("PRAGMA user_version = 1")
            connection.execute("CREATE VIRTUAL TABLE records_fts USING fts5(record_id, summary, labels)")
            connection.commit()
            connection.close()
            with self.assertRaises(ValidationFailure) as raised:
                search_records(malformed, "synthetic")
            self.assertEqual(raised.exception.code, "projection-unavailable")

    def test_projection_queries_reject_metadata_and_derived_row_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            schema_output = root / "schema"
            project_records([FIXTURE], schema_output)
            connection = sqlite3.connect(schema_output / "records.sqlite")
            connection.execute("UPDATE projection_metadata SET projection_schema_id = 'artifact-memory/sqlite-projection/v999'")
            connection.commit()
            connection.close()
            with self.assertRaises(ValidationFailure) as raised:
                related_records(schema_output / "records.sqlite", "record://synthetic/record-0001")
            self.assertEqual(raised.exception.code, "projection-schema-mismatch")

            count_output = root / "count"
            project_records([FIXTURE], count_output)
            connection = sqlite3.connect(count_output / "records.sqlite")
            connection.execute("UPDATE projection_metadata SET record_count = 99")
            connection.commit()
            connection.close()
            with self.assertRaises(ValidationFailure) as raised:
                projection_metadata(count_output / "records.sqlite")
            self.assertEqual(raised.exception.code, "projection-unavailable")

            provenance_output = root / "provenance"
            project_records([FIXTURE], provenance_output)
            connection = sqlite3.connect(provenance_output / "records.sqlite")
            connection.execute("PRAGMA ignore_check_constraints = ON")
            connection.execute("UPDATE provenance SET ordinal = -1")
            connection.commit()
            connection.close()
            with self.assertRaises(ValidationFailure) as raised:
                records_with_provenance(provenance_output / "records.sqlite", "fixture://synthetic/contracts/v0")
            self.assertEqual(raised.exception.code, "projection-unavailable")

            search_output = root / "search"
            project_records([FIXTURE], search_output)
            connection = sqlite3.connect(search_output / "records.sqlite")
            connection.execute("UPDATE records_fts SET summary = 'forged stale summary'")
            connection.commit()
            connection.close()
            with self.assertRaises(ValidationFailure) as raised:
                search_records(search_output / "records.sqlite", "forged")
            self.assertEqual(raised.exception.code, "projection-unavailable")


if __name__ == "__main__":
    unittest.main()
