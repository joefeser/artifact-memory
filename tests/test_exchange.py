import json
import hashlib
import unittest
from pathlib import Path

from artifact_memory.exchange import AUTHORITY_BOUNDARY, admit, make_envelope
from artifact_memory.independent_reader import ReaderFailure, read_bundle
from artifact_memory.validator import ValidationFailure, validate


ROOT = Path(__file__).resolve().parents[1]


def canonical_record(**overrides):
    record = {
        "schema_id": "artifact-memory/knowledge-record/v1",
        "record_id": "record://synthetic/reader-0001",
        "record_type": "note",
        "lifecycle": "accepted",
        "meaning": {"summary": "Synthetic independent-reader record."},
        "artifact_refs": [],
        "provenance": [{"kind": "author", "source_ref": "actor://synthetic/reader"}],
        "extensions": {},
    }
    record.update(overrides)
    return record


def revision_ref(record):
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"record_id": record["record_id"], "revision_digest": "sha-256:" + hashlib.sha256(encoded).hexdigest()}


class ExchangeTests(unittest.TestCase):
    def test_independent_reader_preserves_optional_and_rejects_required_extensions(self):
        record = canonical_record(extensions={"https://synthetic.example/optional": {"version": "v1", "required": False, "value": {"opaque": True}}})
        envelope = make_envelope("system://independent-reader", "synthetic-exchange-reader", "2099-01-01T00:00:00Z", [revision_ref(record)], ["artifact://synthetic/order"], record_bundle=[record])
        result = read_bundle(json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode())
        self.assertEqual(result["outcome"], "accepted")
        self.assertEqual(result["artifact_retrieval"], "separately-authorized")
        required = dict(record)
        required["extensions"] = {"https://synthetic.example/required": {"version": "v1", "required": True, "value": {}}}
        required_envelope = make_envelope("system://independent-reader", "synthetic-exchange-required", "2099-01-01T00:00:00Z", [revision_ref(required)], [], record_bundle=[required])
        with self.assertRaisesRegex(ReaderFailure, "required extension"):
            read_bundle(json.dumps(required_envelope).encode())
        supported = read_bundle(
            json.dumps(required_envelope).encode(),
            supported_required_extensions={("https://synthetic.example/required", "v1")},
        )
        self.assertEqual(supported["preserved_extensions"], [required["extensions"]])
        with self.assertRaisesRegex(ReaderFailure, "required extension"):
            read_bundle(
                json.dumps(required_envelope).encode(),
                supported_required_extensions={("https://synthetic.example/required", "v2")},
            )

    def test_independent_reader_binds_bundle_ids_and_revision_digests(self):
        record = canonical_record()
        envelope = make_envelope("system://independent-reader", "synthetic-exchange-binding", "2099-01-01T00:00:00Z", [revision_ref(record)], [], record_bundle=[record])

        substituted = {**envelope, "record_bundle": [canonical_record(meaning={"summary": "Substituted record."})]}
        with self.assertRaisesRegex(ReaderFailure, "revision digest"):
            read_bundle(json.dumps(substituted).encode())

        wrong_id = {**envelope, "record_refs": [{**revision_ref(record), "record_id": "record://synthetic/other"}]}
        with self.assertRaisesRegex(ReaderFailure, "does not match"):
            read_bundle(json.dumps(wrong_id).encode())

        extra_ref = revision_ref(canonical_record(record_id="record://synthetic/extra"))
        missing_bundle_entry = {**envelope, "record_refs": [revision_ref(record), extra_ref]}
        with self.assertRaisesRegex(ReaderFailure, "does not match"):
            read_bundle(json.dumps(missing_bundle_entry).encode())

        empty_bundle = {**envelope, "record_bundle": []}
        with self.assertRaisesRegex(ReaderFailure, "does not match"):
            read_bundle(json.dumps(empty_bundle).encode())

    def test_independent_reader_accepts_schema_valid_redacted_derivative(self):
        record = canonical_record(
            schema_id="artifact-memory/knowledge-record/v2",
            record_id="record://synthetic/redacted-reader",
            relationships=[{"type": "redacted-from", "target_ref": "record://synthetic/source-reader"}],
        )
        envelope = make_envelope(
            "system://independent-reader",
            "synthetic-redacted-reader",
            "2099-01-01T00:00:00Z",
            [revision_ref(record)],
            [],
            record_bundle=[record],
        )
        self.assertEqual(read_bundle(json.dumps(envelope).encode())["outcome"], "accepted")
        legacy = {**record, "schema_id": "artifact-memory/knowledge-record/v1"}
        legacy_envelope = make_envelope(
            "system://independent-reader",
            "synthetic-redacted-reader-v1-rejected",
            "2099-01-01T00:00:00Z",
            [revision_ref(legacy)],
            [],
            record_bundle=[legacy],
        )
        with self.assertRaisesRegex(ReaderFailure, "relationship"):
            read_bundle(json.dumps(legacy_envelope).encode())

    def test_admission_and_replay_are_explicit(self):
        envelope = make_envelope("system://synthetic-reader", "synthetic-exchange-0001", "2099-01-01T00:00:00Z", [{"record_id": "record://synthetic/record-0001", "revision_digest": "sha-256:" + "a" * 64}], ["artifact://synthetic/order-sample"])
        schema = json.loads((ROOT / "artifact_memory/schemas/core/exchange-envelope.v1.schema.json").read_text(encoding="utf-8"))
        validate(envelope, schema)
        receipt = admit(envelope, now="2026-07-30T00:00:00Z")
        receipt_schema = json.loads((ROOT / "artifact_memory/schemas/core/admission-receipt.v1.schema.json").read_text(encoding="utf-8"))
        validate(receipt, receipt_schema)
        self.assertEqual(receipt["outcome"], "admitted")
        self.assertEqual(receipt["authority_boundary"], AUTHORITY_BOUNDARY)
        replay = admit(envelope, {envelope["envelope_id"]}, now="2026-07-30T00:00:00Z")
        self.assertEqual(replay["outcome"], "duplicate")
        self.assertEqual(admit(envelope)["outcome"], "admitted")

    def test_expired_input_rejects_without_authority(self):
        envelope = make_envelope("system://synthetic-reader", "synthetic-exchange-0002", "2020-01-01T00:00:00Z", [{"record_id": "record://synthetic/record-0001", "revision_digest": "sha-256:" + "a" * 64}], [])
        receipt = admit(envelope, now="2026-07-30T00:00:00Z")
        self.assertEqual(receipt["outcome"], "rejected")
        self.assertEqual(receipt["diagnostics"][0]["code"], "expired")

    def test_admission_rejects_schema_invalid_envelopes_with_valid_receipts(self):
        receipt_schema = json.loads((ROOT / "artifact_memory/schemas/core/admission-receipt.v1.schema.json").read_text(encoding="utf-8"))
        malformed = {
            "schema_id": "artifact-memory/exchange-envelope/v1",
            "envelope_id": "not-an-envelope-id",
            "record_refs": [{"revision_digest": "sha-256:" + "a" * 64}],
        }
        receipt = admit(malformed)
        validate(receipt, receipt_schema)
        self.assertEqual(receipt["outcome"], "rejected")
        self.assertEqual(receipt["diagnostics"][0]["code"], "invalid-envelope")
        self.assertTrue(receipt["envelope_ref"].startswith("exchange://"))

    def test_admission_rejection_receipt_normalizes_uppercase_claimed_id(self):
        envelope = make_envelope("system://synthetic-reader", "uppercase-id", "2099-01-01T00:00:00Z", [], ["artifact://synthetic/item"])
        uppercase_id = "exchange://" + envelope["envelope_id"].removeprefix("exchange://").upper()
        receipt = admit({**envelope, "envelope_id": uppercase_id})
        receipt_schema = json.loads((ROOT / "artifact_memory/schemas/core/admission-receipt.v1.schema.json").read_text(encoding="utf-8"))
        validate(receipt, receipt_schema)
        self.assertEqual(receipt["outcome"], "rejected")
        self.assertEqual(receipt["envelope_ref"], envelope["envelope_id"])

    def test_admission_rejects_content_identity_mismatch_before_replay(self):
        envelope = make_envelope("system://synthetic-reader", "content-bound", "2099-01-01T00:00:00Z", [], ["artifact://synthetic/item"])
        tampered = {**envelope, "correlation_id": "different-valid-body"}
        receipt = admit(tampered, {envelope["envelope_id"]})
        receipt_schema = json.loads((ROOT / "artifact_memory/schemas/core/admission-receipt.v1.schema.json").read_text(encoding="utf-8"))
        validate(receipt, receipt_schema)
        self.assertEqual(receipt["outcome"], "rejected")
        self.assertEqual(receipt["diagnostics"][0]["code"], "envelope-id-mismatch")
        self.assertNotEqual(receipt["envelope_ref"], envelope["envelope_id"])

    def test_timezone_naive_expiry_is_rejected(self):
        envelope = make_envelope("system://synthetic-reader", "synthetic-exchange-naive", "2099-01-01T00:00:00", [], [])
        schema = json.loads((ROOT / "artifact_memory/schemas/core/exchange-envelope.v1.schema.json").read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ValidationFailure, "timezone offset"):
            validate(envelope, schema)
        self.assertEqual(admit(envelope)["outcome"], "rejected")

    def test_all_date_time_contract_fields_require_offsets(self):
        cases = [
            (
                "retention-policy.v2.schema.json",
                {
                    "schema_id": "artifact-memory/retention-policy/v2",
                    "policy_id": "retention-policy://synthetic/standard",
                    "retention_class": "standard",
                    "owner_ref": "actor://synthetic/owner",
                    "owner_hold": False,
                    "legal_hold": False,
                    "expires_at": "2099-01-01T00:00:00Z",
                    "backup_expiry_behavior": "managed-expiry",
                    "unknown_replica_behavior": "report-scope-unknown",
                    "git_history_behavior": "separate-rewrite-authorization-required",
                    "deletion_authority": "separate-owner-or-legal-authorization-required",
                },
                "expires_at",
            ),
            (
                "location-observation.v1.schema.json",
                {
                    "schema_id": "artifact-memory/location-observation/v1",
                    "observation_id": "location-observation://synthetic/record",
                    "content_ref": "content://synthetic/object",
                    "endpoint_ref": "endpoint://synthetic/store",
                    "relative_path": "records/object.json",
                    "presence": "present",
                    "observed_at": "2099-01-01T00:00:00Z",
                },
                "observed_at",
            ),
        ]
        for schema_name, record, field in cases:
            schema = json.loads((ROOT / "artifact_memory/schemas/core" / schema_name).read_text(encoding="utf-8"))
            validate(record, schema)
            naive = {**record, field: "2099-01-01T00:00:00"}
            with self.assertRaisesRegex(ValidationFailure, "timezone offset"):
                validate(naive, schema)

    def test_independent_reader_rejects_malformed_shapes_at_its_boundary(self):
        for value in ([], 1, "scalar"):
            with self.assertRaises(ReaderFailure):
                read_bundle(json.dumps(value).encode())
        malformed_record = canonical_record(extensions=[])
        malformed = make_envelope("system://independent-reader", "malformed-extensions", "2099-01-01T00:00:00Z", [revision_ref(malformed_record)], [], record_bundle=[malformed_record])
        with self.assertRaisesRegex(ReaderFailure, "extensions"):
            read_bundle(json.dumps(malformed).encode())
        malformed_record = canonical_record(extensions={"https://synthetic.example/extension": []})
        malformed = make_envelope("system://independent-reader", "malformed-declaration", "2099-01-01T00:00:00Z", [revision_ref(malformed_record)], [], record_bundle=[malformed_record])
        with self.assertRaisesRegex(ReaderFailure, "declaration"):
            read_bundle(json.dumps(malformed).encode())
        malformed["record_bundle"][0] = {"schema_id": "artifact-memory/knowledge-record/v1", "record_id": "record://synthetic/incomplete"}
        with self.assertRaisesRegex(ReaderFailure, "fields"):
            read_bundle(json.dumps(malformed).encode())


if __name__ == "__main__":
    unittest.main()
