import json
import tempfile
import unittest
from pathlib import Path

from artifact_memory.projection import project_records, related_records, search_records


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
            rebuilt_receipt = project_records([one, two], first_out)
            self.assertEqual(rebuilt_receipt, first_receipt)
            self.assertEqual(search_records(first_out / "records.sqlite", "projection"), ["record://synthetic/record-0002"])


if __name__ == "__main__":
    unittest.main()
