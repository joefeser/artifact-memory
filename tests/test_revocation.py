import copy
import json
import unittest
from pathlib import Path

from artifact_memory.context import export_context
from artifact_memory.independent_context_reader import recall_context
from artifact_memory.projection import project_records
from artifact_memory.revocation import (
    aggregate_revocation,
    acknowledge_revocation,
    build_revocation_envelope,
    filter_revoked_records,
)
from artifact_memory.retention import deletion_receipt, tombstone
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/synthetic/contracts/v0-valid-record.json"
NOW = "2026-08-04T00:00:00Z"


class RevocationTests(unittest.TestCase):
    def _tombstone(self):
        receipt = deletion_receipt(
            "record://synthetic/record-0001",
            "active-vault",
            "removed-observed",
            observed_at=NOW,
            managed_scope=True,
            endpoint_ref="endpoint://synthetic/active-vault",
            evidence_refs=["projection-receipt://synthetic/revocation"],
        )
        return tombstone(
            "record://synthetic/record-0001",
            "owner-approved-deletion",
            "bytes-removed-from-scope",
            receipt["receipt_id"],
            created_at=NOW,
        )

    def test_envelope_acknowledgement_aggregation_and_no_authority(self):
        marker = self._tombstone()
        envelope = build_revocation_envelope(
            marker,
            target_revision_digest="sha-256:" + "a" * 64,
            issuer_ref="actor://synthetic/owner",
            audience_ref="audience://synthetic/agents",
            correlation_id="correlation://synthetic/revocation-0001",
            expires_at="2026-08-05T00:00:00Z",
        )
        validate(envelope, load_schema("core", "revocation-envelope.v1.schema.json"))
        seen = set()
        acknowledged = acknowledge_revocation(
            envelope,
            recipient_ref="agent://synthetic/reader-a",
            outcome="acknowledged",
            suppression_state="applied",
            endpoint_receipt_refs=["deletion-receipt://synthetic/endpoint-a/" + "b" * 64],
            expected_audience_ref="audience://synthetic/agents",
            seen_envelope_ids=seen,
            now=NOW,
        )
        unavailable = acknowledge_revocation(
            envelope,
            recipient_ref="agent://synthetic/reader-b",
            outcome="unavailable",
            suppression_state="unknown",
            expected_audience_ref="audience://synthetic/agents",
            now=NOW,
        )
        aggregate = aggregate_revocation(envelope, [acknowledged, unavailable])
        self.assertEqual(acknowledged["outcome"], "acknowledged")
        self.assertEqual(aggregate["outcome"], "partially-complete")
        self.assertEqual(aggregate["unresolved_recipient_refs"], ["agent://synthetic/reader-b"])
        self.assertEqual(aggregate["authority_boundary"], "revocation propagation grants no execution, disclosure, routing, mutation, or erasure authority")

    def test_duplicate_ack_and_audience_mismatch_are_receipted(self):
        envelope = build_revocation_envelope(
            self._tombstone(),
            target_revision_digest="sha-256:" + "a" * 64,
            issuer_ref="actor://synthetic/owner",
            audience_ref="audience://synthetic/agents",
            correlation_id="correlation://synthetic/revocation-0002",
            expires_at="2026-08-05T00:00:00Z",
        )
        seen = {envelope["envelope_id"]}
        duplicate = acknowledge_revocation(
            envelope,
            recipient_ref="agent://synthetic/reader-a",
            outcome="acknowledged",
            suppression_state="applied",
            seen_envelope_ids=seen,
            now=NOW,
        )
        mismatch = acknowledge_revocation(
            envelope,
            recipient_ref="agent://synthetic/reader-b",
            outcome="acknowledged",
            suppression_state="applied",
            expected_audience_ref="audience://synthetic/other",
            now=NOW,
        )
        self.assertEqual(duplicate["outcome"], "duplicate")
        self.assertEqual(mismatch["outcome"], "rejected")

    def test_tombstone_suppresses_projection_and_context(self):
        record = json.loads(FIXTURE.read_text(encoding="utf-8"))
        with self.subTest("projection"):
            import tempfile
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "record.json"
                path.write_text(json.dumps(record), encoding="utf-8")
                receipt = project_records([path], Path(temporary) / "projection", suppressed_record_ids=[record["record_id"]])
                self.assertEqual(receipt["record_count"], 0)
                self.assertIn("revocation-suppression", json.dumps(receipt))
        with self.subTest("context"):
            pack = export_context(
                [record],
                authorized_record_ids=[record["record_id"]],
                freshness_by_record={record["record_id"]: {"status": "current", "assessed_at": NOW, "basis": "synthetic"}},
                selected_at=NOW,
                revoked_record_ids=[record["record_id"]],
                revocation_receipt_refs=["revocation-receipt://" + "c" * 64],
            )
            self.assertEqual(pack["records"], [])
            self.assertEqual(pack["selection_receipt"]["exclusion_counts"]["revocation"], 1)
            validate(pack, load_schema("core", "context-pack.v2.schema.json"))
            self.assertEqual(recall_context(json.dumps(pack, sort_keys=True, separators=(",", ":")).encode())["records"], [])

    def test_filter_requires_supported_tombstones_and_preserves_history(self):
        record = json.loads(FIXTURE.read_text(encoding="utf-8"))
        retained = copy.deepcopy(record)
        retained["record_id"] = "record://synthetic/record-0002"
        filtered = filter_revoked_records([record, retained], [self._tombstone()])
        self.assertEqual([item["record_id"] for item in filtered], [retained["record_id"]])
        self.assertEqual(self._tombstone()["sensitive_payload_retained"], False)


if __name__ == "__main__":
    unittest.main()
