import json
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

    def test_querying_missing_projection_is_read_only_and_typed(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing.sqlite"
            with self.assertRaises(ValidationFailure) as raised:
                search_records(missing, "synthetic")
            self.assertEqual(raised.exception.code, "projection-unavailable")
            self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
