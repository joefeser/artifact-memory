import json
import unittest
from pathlib import Path

from artifact_memory.context import AUTHORITY_BOUNDARY, ContextFailure, export_context
from artifact_memory.independent_context_reader import ContextReaderFailure, recall_context
from artifact_memory.validator import ValidationFailure, validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "contracts" / "v0-valid-record.json"
SELECTED_AT = "2026-07-30T00:00:00Z"


def current(*record_ids):
    return {
        record_id: {"status": "current", "assessed_at": SELECTED_AT, "basis": "synthetic-fixture"}
        for record_id in record_ids
    }


def repack(pack):
    import hashlib

    body = {key: value for key, value in pack.items() if key != "pack_id"}
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return {**body, "pack_id": "context-pack://" + hashlib.sha256(canonical).hexdigest()}


class ContextTests(unittest.TestCase):
    def test_pack_is_authorized_bounded_reference_only_and_schema_valid(self):
        public = json.loads(FIXTURE.read_text(encoding="utf-8"))
        private = dict(public)
        private["record_id"] = "record://synthetic/private-0001"
        private["sensitivity"] = "private"
        public["relationships"] = [{"type": "supported-by-external-evidence", "target_ref": "external-evidence-binding://synthetic/status"}]
        evidence = [{"provider_id": "tracemap", "provider_schema_id": "https://tracemap.tools/contracts/code-fact.v1.schema.json", "provider_record_id": "fact-synthetic-status-access", "binding_ref": "external-evidence-binding://synthetic/status", "evidence_packet_ref": "artifact-version://tracemap/evidence/" + "a" * 64 + "/1", "adapter_receipt_digest": "sha-256:" + "b" * 64, "integrity_state": "integrity-verified / issuer-unverified", "rule_id": "csharp.semantic.propertyaccess.v1", "evidence_tier": "Tier1Semantic", "coverage": {"analysis_level": "Level1SemanticAnalysis", "build_status": "Succeeded", "known_gaps": []}, "limitations": ["static evidence only"]}]
        record_ids = [public["record_id"], private["record_id"]]
        pack = export_context(
            [private, public],
            evidence,
            authorized_record_ids=record_ids,
            authorized_evidence=[("tracemap", "fact-synthetic-status-access")],
            freshness_by_record=current(*record_ids),
            selected_at=SELECTED_AT,
        )
        schema = json.loads((ROOT / "artifact_memory/schemas/core/context-pack.v2.schema.json").read_text(encoding="utf-8"))
        validate(pack, schema)
        self.assertEqual(pack["authority_boundary"], AUTHORITY_BOUNDARY)
        self.assertEqual(pack["selection_receipt"]["exclusion_counts"]["sensitivity"], 1)
        self.assertNotIn(private["record_id"], json.dumps(pack))
        self.assertEqual(pack["external_evidence"][0]["provider_id"], "tracemap")
        self.assertEqual(pack["external_evidence"][0]["coverage_details"]["build_status"], "Succeeded")
        self.assertNotIn("facts", json.dumps(pack))

    def test_authorization_and_freshness_fail_closed(self):
        record = json.loads(FIXTURE.read_text(encoding="utf-8"))
        record_id = record["record_id"]
        unauthorized = export_context(
            [record], authorized_record_ids=[], freshness_by_record={}, selected_at=SELECTED_AT
        )
        self.assertEqual(unauthorized["records"], [])
        self.assertEqual(unauthorized["selection_receipt"]["exclusion_counts"]["not-authorized"], 1)
        stale = export_context(
            [record],
            authorized_record_ids=[record_id],
            freshness_by_record={record_id: {"status": "stale", "assessed_at": SELECTED_AT, "basis": "synthetic-fixture"}},
            selected_at=SELECTED_AT,
        )
        self.assertEqual(stale["records"], [])
        self.assertEqual(stale["selection_receipt"]["exclusion_counts"]["freshness"], 1)

    def test_size_bound_is_explicit_and_rejects_boolean(self):
        record = json.loads(FIXTURE.read_text(encoding="utf-8"))
        record_id = record["record_id"]
        kwargs = {"authorized_record_ids": [record_id], "freshness_by_record": current(record_id), "selected_at": SELECTED_AT}
        with self.assertRaisesRegex(ContextFailure, "exceeds"):
            export_context([record], max_bytes=32, **kwargs)
        with self.assertRaises(ContextFailure) as raised:
            export_context([record], max_bytes=True, **kwargs)
        self.assertEqual(raised.exception.code, "size-limit-invalid")

    def test_external_evidence_requires_explicit_authorization(self):
        record = json.loads(FIXTURE.read_text(encoding="utf-8"))
        evidence = [{"provider_id": "legacy", "provider_schema_id": "legacy/v1", "provider_record_id": "row-1", "binding_ref": "external-evidence-binding://synthetic/legacy", "evidence_packet_ref": "artifact-version://legacy/evidence/1", "adapter_receipt_digest": "sha-256:" + "a" * 64, "integrity_state": "unverified", "coverage": "legacy bounded scan", "limitations": []}]
        pack = export_context(
            [record], evidence, authorized_record_ids=[record["record_id"]], freshness_by_record=current(record["record_id"]), selected_at=SELECTED_AT
        )
        self.assertEqual(pack["external_evidence"], [])

    def test_malformed_selection_and_evidence_fail_closed(self):
        record = json.loads(FIXTURE.read_text(encoding="utf-8"))
        record_id = record["record_id"]
        kwargs = {"freshness_by_record": current(record_id), "selected_at": SELECTED_AT}
        with self.assertRaises(ValidationFailure) as record_error:
            export_context([record, "not-an-object"], authorized_record_ids=[record_id], **kwargs)
        self.assertEqual(record_error.exception.code, "invalid-input")
        with self.assertRaises(ContextFailure) as records_error:
            export_context([record], authorized_record_ids=[[]], **kwargs)
        self.assertEqual(records_error.exception.code, "selection-policy-invalid")
        with self.assertRaises(ContextFailure) as evidence_key_error:
            export_context([record], authorized_record_ids=[record_id], authorized_evidence=[["provider", "row"]], **kwargs)
        self.assertEqual(evidence_key_error.exception.code, "authorized-evidence-unavailable")
        malformed = {"provider_id": 1}
        with self.assertRaises(ContextFailure) as evidence_error:
            export_context([record], [malformed], authorized_record_ids=[record_id], **kwargs)
        self.assertEqual(evidence_error.exception.code, "external-evidence-invalid")

    def test_required_extension_negotiation_fails_closed_before_export(self):
        record = json.loads(FIXTURE.read_text(encoding="utf-8"))
        record_id = record["record_id"]
        record["extensions"] = {
            "https://synthetic.example/extensions/required": {"version": "v1", "required": True, "value": {}}
        }
        kwargs = {"authorized_record_ids": [record_id], "freshness_by_record": current(record_id), "selected_at": SELECTED_AT}
        with self.assertRaises(ContextFailure) as raised:
            export_context([record], **kwargs)
        self.assertEqual(raised.exception.code, "required-extension-unsupported")
        admitted = export_context(
            [record],
            supported_required_extensions=[("https://synthetic.example/extensions/required", "v1")],
            **kwargs,
        )
        self.assertEqual(admitted["selection_receipt"]["selected_record_ids"], [record_id])

    def test_independent_reader_recalls_without_authority(self):
        record = json.loads(FIXTURE.read_text(encoding="utf-8"))
        pack = export_context(
            [record], authorized_record_ids=[record["record_id"]], freshness_by_record=current(record["record_id"]), selected_at=SELECTED_AT
        )
        receipt = recall_context(json.dumps(pack, sort_keys=True, separators=(",", ":")).encode())
        validate(receipt, json.loads((ROOT / "artifact_memory/schemas/core/context-recall-receipt.v1.schema.json").read_text()))
        self.assertEqual(receipt["records"][0]["summary"], record["meaning"]["summary"])
        self.assertEqual(receipt["mutation_authority"], "absent")
        self.assertEqual(receipt["artifact_retrieval"], "not-attempted/separately-authorized")
        tampered = dict(pack)
        tampered["records"] = []
        with self.assertRaises(ContextReaderFailure):
            recall_context(json.dumps(tampered).encode())

    def test_independent_reader_rejects_invalid_time_and_evidence_contract(self):
        record = json.loads(FIXTURE.read_text(encoding="utf-8"))
        relationship = {"type": "supported-by-external-evidence", "target_ref": "binding://synthetic/one"}
        record["relationships"] = [relationship, relationship]
        evidence = [{"provider_id": "synthetic", "provider_schema_id": "synthetic/v1", "provider_record_id": "row-1", "binding_ref": "binding://synthetic/one", "evidence_packet_ref": "artifact-version://synthetic/evidence/1", "adapter_receipt_digest": "sha-256:" + "a" * 64, "integrity_state": "unverified", "coverage": "bounded", "limitations": []}]
        pack = export_context(
            [record], evidence,
            authorized_record_ids=[record["record_id"]],
            authorized_evidence=[("synthetic", "row-1")],
            freshness_by_record=current(record["record_id"]),
            selected_at=SELECTED_AT,
        )
        self.assertEqual(pack["records"][0]["external_evidence_bindings"], ["binding://synthetic/one"])
        recall_context(json.dumps(pack).encode())
        later = json.loads(json.dumps(pack))
        later["records"][0]["freshness"]["assessed_at"] = "2026-07-31T00:00:00Z"
        with self.assertRaises(ContextReaderFailure):
            recall_context(json.dumps(repack(later)).encode())
        missing = json.loads(json.dumps(pack))
        del missing["external_evidence"][0]["evidence_packet_ref"]
        with self.assertRaises(ContextReaderFailure):
            recall_context(json.dumps(repack(missing)).encode())
        orphan = json.loads(json.dumps(pack))
        orphan["external_evidence"][0]["binding_ref"] = "binding://synthetic/orphan"
        with self.assertRaises(ContextReaderFailure):
            recall_context(json.dumps(repack(orphan)).encode())
        duplicate = json.loads(json.dumps(pack))
        duplicate["external_evidence"].append(duplicate["external_evidence"][0])
        duplicate["selection_receipt"]["selected_external_evidence"].append(
            duplicate["selection_receipt"]["selected_external_evidence"][0]
        )
        with self.assertRaises(ContextReaderFailure):
            recall_context(json.dumps(repack(duplicate)).encode())
        malformed_artifact = json.loads(json.dumps(pack))
        malformed_artifact["artifact_refs"] = ["artifact://synthetic/invalid ref"]
        with self.assertRaises(ContextReaderFailure):
            recall_context(json.dumps(repack(malformed_artifact)).encode())
        malformed_record_id = json.loads(json.dumps(pack))
        malformed_record_id["records"][0]["record_id"] = "invalid"
        malformed_record_id["selection_receipt"]["selected_record_ids"] = ["invalid"]
        with self.assertRaises(ContextReaderFailure):
            recall_context(json.dumps(repack(malformed_record_id)).encode())
        malformed_source_digest = json.loads(json.dumps(pack))
        malformed_source_digest["selection_receipt"]["source_record_set_digest"] = 1
        with self.assertRaises(ContextReaderFailure):
            recall_context(json.dumps(repack(malformed_source_digest)).encode())
        malformed_revision_digest = json.loads(json.dumps(pack))
        malformed_revision_digest["records"][0]["revision_digest"] = 1
        with self.assertRaises(ContextReaderFailure):
            recall_context(json.dumps(repack(malformed_revision_digest)).encode())
        malformed_adapter_digest = json.loads(json.dumps(pack))
        malformed_adapter_digest["external_evidence"][0]["adapter_receipt_digest"] = 1
        with self.assertRaises(ContextReaderFailure):
            recall_context(json.dumps(repack(malformed_adapter_digest)).encode())


if __name__ == "__main__":
    unittest.main()
