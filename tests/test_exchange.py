import json
import unittest
from pathlib import Path

from artifact_memory.exchange import AUTHORITY_BOUNDARY, admit, make_envelope
from artifact_memory.independent_reader import ReaderFailure, read_bundle
from artifact_memory.validator import validate


ROOT = Path(__file__).resolve().parents[1]


class ExchangeTests(unittest.TestCase):
    def test_independent_reader_preserves_optional_and_rejects_required_extensions(self):
        record = {"schema_id": "artifact-memory/knowledge-record/v1", "record_id": "record://synthetic/reader-0001", "extensions": {"https://synthetic.example/optional": {"version": "v1", "required": False, "value": {"opaque": True}}}}
        envelope = make_envelope("system://independent-reader", "synthetic-exchange-reader", "2099-01-01T00:00:00Z", [{"record_id": record["record_id"], "revision_digest": "sha-256:" + "a" * 64}], ["artifact://synthetic/order"], record_bundle=[record])
        result = read_bundle(json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode())
        self.assertEqual(result["outcome"], "accepted")
        self.assertEqual(result["artifact_retrieval"], "separately-authorized")
        required = dict(record)
        required["extensions"] = {"https://synthetic.example/required": {"version": "v1", "required": True, "value": {}}}
        required_envelope = make_envelope("system://independent-reader", "synthetic-exchange-required", "2099-01-01T00:00:00Z", [], [], record_bundle=[required])
        with self.assertRaisesRegex(ReaderFailure, "required extension"):
            read_bundle(json.dumps(required_envelope).encode())

    def test_admission_and_replay_are_explicit(self):
        envelope = make_envelope("system://synthetic-reader", "synthetic-exchange-0001", "2099-01-01T00:00:00Z", [{"record_id": "record://synthetic/record-0001", "revision_digest": "sha-256:" + "a" * 64}], ["artifact://synthetic/order-sample"])
        schema = json.loads((ROOT / "schemas/core/exchange-envelope.v1.schema.json").read_text(encoding="utf-8"))
        validate(envelope, schema)
        receipt = admit(envelope, now="2026-07-30T00:00:00Z")
        receipt_schema = json.loads((ROOT / "schemas/core/admission-receipt.v1.schema.json").read_text(encoding="utf-8"))
        validate(receipt, receipt_schema)
        self.assertEqual(receipt["outcome"], "admitted")
        self.assertEqual(receipt["authority_boundary"], AUTHORITY_BOUNDARY)
        replay = admit(envelope, {envelope["envelope_id"]}, now="2026-07-30T00:00:00Z")
        self.assertEqual(replay["outcome"], "duplicate")

    def test_expired_input_rejects_without_authority(self):
        envelope = make_envelope("system://synthetic-reader", "synthetic-exchange-0002", "2020-01-01T00:00:00Z", [{"record_id": "record://synthetic/record-0001", "revision_digest": "sha-256:" + "a" * 64}], [])
        receipt = admit(envelope, now="2026-07-30T00:00:00Z")
        self.assertEqual(receipt["outcome"], "rejected")
        self.assertEqual(receipt["diagnostics"][0]["code"], "expired")


if __name__ == "__main__":
    unittest.main()
