import json
import unittest
from pathlib import Path

from artifact_memory.wits_adapter import AUTHORITY_BOUNDARY, bind_projection
from artifact_memory.validator import validate


ROOT = Path(__file__).resolve().parents[1]


class WitsAdapterTests(unittest.TestCase):
    def setUp(self):
        self.record = json.loads((ROOT / "fixtures/synthetic/contracts/v0-valid-record.json").read_text(encoding="utf-8"))
        self.response = json.loads((ROOT / "fixtures/synthetic/wits/v1/projection-response.json").read_text(encoding="utf-8"))

    def test_projection_stops_before_authority_and_validates(self):
        projection, receipt = bind_projection([self.record], "owner-meaning", self.response, authorized=True, external_evidence_refs=["artifact-version://tracemap/evidence/" + "a" * 64 + "/1"])
        projection_schema = json.loads((ROOT / "schemas/adapters/wits-projection.v1.schema.json").read_text(encoding="utf-8"))
        receipt_schema = json.loads((ROOT / "schemas/adapters/wits-admission-receipt.v1.schema.json").read_text(encoding="utf-8"))
        validate(projection, projection_schema)
        validate(receipt, receipt_schema)
        self.assertEqual(receipt["outcome"], "admitted")
        self.assertEqual(projection["authority_boundary"], AUTHORITY_BOUNDARY)
        self.assertNotIn("task_packet", json.dumps(projection))

    def test_stale_revision_is_receipted(self):
        projection, receipt = bind_projection([self.record], "readiness", self.response, authorized=True, expected_revisions={self.record["record_id"]: "sha-256:" + "d" * 64})
        self.assertIsNone(projection)
        self.assertEqual(receipt["outcome"], "stale")

    def test_authority_request_is_rejected(self):
        response = {**self.response, "create_task": {"kind": "HACP"}}
        projection, receipt = bind_projection([self.record], "owner-meaning", response, authorized=True)
        self.assertIsNone(projection)
        self.assertEqual(receipt["outcome"], "authority-bearing-request-rejected")


if __name__ == "__main__":
    unittest.main()
