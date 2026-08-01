import json
import unittest
from pathlib import Path

from artifact_memory.wits_adapter import (
    AUTHORITY_BOUNDARY,
    bind_projection,
    bind_projection_v2,
    build_projection_request,
)
from artifact_memory.validator import validate


ROOT = Path(__file__).resolve().parents[1]


class WitsAdapterTests(unittest.TestCase):
    def setUp(self):
        self.record = json.loads((ROOT / "fixtures/synthetic/contracts/v0-valid-record.json").read_text(encoding="utf-8"))
        self.response = json.loads((ROOT / "fixtures/synthetic/wits/v1/projection-response.json").read_text(encoding="utf-8"))

    def test_projection_stops_before_authority_and_validates(self):
        projection, receipt = bind_projection([self.record], "owner-meaning", self.response, authorized=True, external_evidence_refs=["artifact-version://tracemap/evidence/" + "a" * 64 + "/1"])
        projection_schema = json.loads((ROOT / "artifact_memory/schemas/adapters/wits-projection.v1.schema.json").read_text(encoding="utf-8"))
        receipt_schema = json.loads((ROOT / "artifact_memory/schemas/adapters/wits-admission-receipt.v1.schema.json").read_text(encoding="utf-8"))
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

    def _strict_response(self, records=None, kind="owner-meaning"):
        records = records or [self.record]
        request = build_projection_request(records, kind)
        from artifact_memory.canonical import canonical_bytes
        import hashlib
        return {
            "admission": "admitted",
            "request_digest": "sha-256:" + hashlib.sha256(canonical_bytes(request)).hexdigest(),
            "projection_ref": "wits-projection://synthetic/meaning-0001",
            "projection_schema_ref": "wits-contract://synthetic/opaque-v1",
            "projection_digest": "sha-256:" + "c" * 64,
        }

    def test_v2_binds_exact_request_and_contract_without_authority(self):
        request = build_projection_request([self.record], "owner-meaning")
        validate(request, json.loads((ROOT / "artifact_memory/schemas/adapters/wits-projection-request.v1.schema.json").read_text()))
        response = self._strict_response()
        projection, receipt = bind_projection_v2([self.record], "owner-meaning", response, True)
        validate(projection, json.loads((ROOT / "artifact_memory/schemas/adapters/wits-projection.v2.schema.json").read_text()))
        validate(receipt, json.loads((ROOT / "artifact_memory/schemas/adapters/wits-admission-receipt.v2.schema.json").read_text()))
        self.assertEqual(receipt["outcome"], "admitted")
        self.assertEqual(projection["provider_contract"]["license"], "BSL-1.1")
        self.assertNotIn("task_packet", json.dumps(projection))

    def test_v2_declared_failures_are_explicit(self):
        response = self._strict_response()
        cases = [
            ({"authorized": False}, "rejected"),
            ({"expected_revisions": {}}, "mixed-revision-context"),
            ({"expected_revisions": {self.record["record_id"]: "sha-256:" + "d" * 64}}, "stale"),
            ({"conflict_detected": True}, "conflict"),
            ({"sensitivity_mapping_available": False}, "sensitivity-mapping-unavailable"),
            ({"disclosure_allowed": False}, "disclosure-denied"),
            ({"external_evidence_refs": ["binding://synthetic/evidence"], "unavailable_evidence_refs": ["binding://synthetic/evidence"]}, "evidence-reference-unavailable"),
        ]
        for options, expected in cases:
            authorized = options.pop("authorized", True)
            projection, receipt = bind_projection_v2([self.record], "owner-meaning", response, authorized, **options)
            self.assertIsNone(projection)
            self.assertEqual(receipt["outcome"], expected)
        superseded = {**self.record, "lifecycle": "superseded"}
        response = self._strict_response([superseded])
        projection, receipt = bind_projection_v2([superseded], "owner-meaning", response, True)
        self.assertIsNone(projection)
        self.assertEqual(receipt["outcome"], "superseded")

    def test_v2_rejects_nested_authority_and_unbound_response(self):
        response = self._strict_response()
        response["nested"] = {"task_packet": {"authority": "execute"}}
        projection, receipt = bind_projection_v2([self.record], "owner-meaning", response, True)
        self.assertIsNone(projection)
        self.assertEqual(receipt["outcome"], "authority-bearing-request-rejected")
        response = self._strict_response()
        response["request_digest"] = "sha-256:" + "0" * 64
        projection, receipt = bind_projection_v2([self.record], "owner-meaning", response, True)
        self.assertIsNone(projection)
        self.assertEqual(receipt["outcome"], "unsupported")


if __name__ == "__main__":
    unittest.main()
