import copy
import json
import tempfile
import unittest
from pathlib import Path

from artifact_memory.context import export_context
from artifact_memory.independent_context_reader import recall_context
from artifact_memory.projection import project_records
from artifact_memory.revocation import (
    SQLiteRevocationReplayLedger,
    aggregate_revocation,
    acknowledge_revocation,
    build_revocation_envelope,
    filter_revoked_records,
)
from artifact_memory.retention import deletion_receipt, tombstone
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import validate
from artifact_memory.validator import ValidationFailure


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/synthetic/contracts/v0-valid-record.json"
REVOCATION_FIXTURE = ROOT / "fixtures/synthetic/revocation-propagation/v1"
NOW = "2026-08-04T00:00:00Z"


class RevocationTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self._ledger_count = 0

    def tearDown(self):
        self._temporary.cleanup()

    def _ledger(self, path=None):
        if path is None:
            self._ledger_count += 1
            path = Path(self._temporary.name) / f"revocation-{self._ledger_count}.sqlite"
        return SQLiteRevocationReplayLedger(path)

    def _record(self):
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

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

    def _envelope(self, correlation_id="correlation://synthetic/revocation-0001"):
        return build_revocation_envelope(
            self._tombstone(),
            target_record=self._record(),
            issuer_ref="actor://synthetic/owner",
            audience_ref="audience://synthetic/agents",
            correlation_id=correlation_id,
            expires_at="2026-08-05T00:00:00Z",
        )

    def _acknowledged(self, envelope=None, recipient_ref="agent://synthetic/reader-a"):
        envelope = envelope or self._envelope()
        return acknowledge_revocation(
            envelope,
            recipient_ref=recipient_ref,
            replay_ledger=self._ledger(),
            outcome="acknowledged",
            suppression_state="applied",
            endpoint_receipt_refs=["deletion-receipt://synthetic/endpoint-a/" + "b" * 64],
            expected_audience_ref="audience://synthetic/agents",
            now=NOW,
        )

    def test_envelope_acknowledgement_aggregation_and_no_authority(self):
        marker = self._tombstone()
        envelope = build_revocation_envelope(
            marker,
            target_record=self._record(),
            issuer_ref="actor://synthetic/owner",
            audience_ref="audience://synthetic/agents",
            correlation_id="correlation://synthetic/revocation-0001",
            expires_at="2026-08-05T00:00:00Z",
        )
        validate(envelope, load_schema("core", "revocation-envelope.v1.schema.json"))
        ledger = self._ledger()
        acknowledged = acknowledge_revocation(
            envelope,
            recipient_ref="agent://synthetic/reader-a",
            replay_ledger=ledger,
            outcome="acknowledged",
            suppression_state="applied",
            endpoint_receipt_refs=["deletion-receipt://synthetic/endpoint-a/" + "b" * 64],
            expected_audience_ref="audience://synthetic/agents",
            now=NOW,
        )
        unavailable = acknowledge_revocation(
            envelope,
            recipient_ref="agent://synthetic/reader-b",
            replay_ledger=ledger,
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
        self.assertEqual(envelope, json.loads((REVOCATION_FIXTURE / "envelope.json").read_text(encoding="utf-8")))
        self.assertEqual(acknowledged, json.loads((REVOCATION_FIXTURE / "acknowledged.json").read_text(encoding="utf-8")))
        self.assertEqual(unavailable, json.loads((REVOCATION_FIXTURE / "unavailable.json").read_text(encoding="utf-8")))
        self.assertEqual(aggregate, json.loads((REVOCATION_FIXTURE / "expected-receipt.json").read_text(encoding="utf-8")))

    def test_duplicate_ack_and_audience_mismatch_are_receipted(self):
        envelope = self._envelope("correlation://synthetic/revocation-0002")
        ledger = self._ledger()
        first = acknowledge_revocation(
            envelope,
            recipient_ref="agent://synthetic/reader-a",
            replay_ledger=ledger,
            outcome="acknowledged",
            suppression_state="applied",
            now=NOW,
        )
        replay = acknowledge_revocation(
            envelope,
            recipient_ref="agent://synthetic/reader-a",
            replay_ledger=ledger,
            outcome="acknowledged",
            suppression_state="applied",
            now=NOW,
        )
        mismatch = acknowledge_revocation(
            envelope,
            recipient_ref="agent://synthetic/reader-b",
            replay_ledger=ledger,
            outcome="acknowledged",
            suppression_state="applied",
            expected_audience_ref="audience://synthetic/other",
            now=NOW,
        )
        self.assertEqual(replay, first)
        self.assertEqual(replay["outcome"], "acknowledged")
        self.assertEqual(mismatch["outcome"], "rejected")

    def test_replay_ledger_is_required_atomic_and_fails_closed(self):
        envelope = self._envelope("correlation://synthetic/revocation-ledger")

        class NoOpLedger:
            def retain(self, acknowledgement_key, receipt):
                return receipt

        class OverwritingLedger(SQLiteRevocationReplayLedger):
            def retain(self, acknowledgement_key, receipt):
                return receipt

        unapproved_ledgers = [
            NoOpLedger(),
            OverwritingLedger(Path(self._temporary.name) / "overwriting.sqlite"),
        ]
        for ledger in unapproved_ledgers:
            with self.subTest(ledger=type(ledger).__name__):
                unavailable = acknowledge_revocation(
                    envelope,
                    recipient_ref="agent://synthetic/reader-a",
                    replay_ledger=ledger,
                    outcome="acknowledged",
                    suppression_state="applied",
                    now=NOW,
                )
                self.assertEqual(unavailable["outcome"], "unavailable")
                self.assertEqual(unavailable["diagnostics"][0]["code"], "replay-ledger-unapproved")
        missing = acknowledge_revocation(
            envelope,
            recipient_ref="agent://synthetic/reader-a",
            outcome="acknowledged",
            suppression_state="applied",
            now=NOW,
        )
        self.assertEqual(missing["outcome"], "unavailable")
        self.assertEqual(missing["diagnostics"][0]["code"], "replay-ledger-unavailable")

    def test_retain_validates_and_binds_receipt_before_inserting(self):
        """A malformed or mismatched receipt must not be persisted, even via direct retain()."""
        ledger = self._ledger()
        with self.assertRaises(ValidationFailure):
            ledger.retain("envelope://x\x00agent://synthetic/reader-a", {"not": "a-valid-receipt"})
        envelope = self._envelope("correlation://synthetic/revocation-retain-binding")
        valid_receipt = acknowledge_revocation(
            envelope,
            recipient_ref="agent://synthetic/reader-a",
            replay_ledger=self._ledger(),
            outcome="acknowledged",
            suppression_state="applied",
            now=NOW,
        )
        with self.assertRaises(ValidationFailure):
            ledger.retain(envelope["envelope_id"] + "\x00agent://synthetic/wrong-recipient", valid_receipt)

    def test_durable_replay_survives_restart_and_preserves_first_writer(self):
        envelope = self._envelope("correlation://synthetic/revocation-restart")
        path = Path(self._temporary.name) / "restart.sqlite"
        first = acknowledge_revocation(
            envelope,
            recipient_ref="agent://synthetic/reader-a",
            replay_ledger=self._ledger(path),
            outcome="acknowledged",
            suppression_state="applied",
            endpoint_receipt_refs=["deletion-receipt://synthetic/endpoint-a/" + "a" * 64],
            now=NOW,
        )
        replay = acknowledge_revocation(
            envelope,
            recipient_ref="agent://synthetic/reader-a",
            replay_ledger=self._ledger(path),
            outcome="acknowledged",
            suppression_state="applied",
            endpoint_receipt_refs=["deletion-receipt://synthetic/endpoint-a/" + "b" * 64],
            now=NOW,
        )
        self.assertEqual(replay, first)
        self.assertEqual(replay["endpoint_receipt_refs"], ["deletion-receipt://synthetic/endpoint-a/" + "a" * 64])

    def test_non_terminal_and_invalid_acknowledgements_do_not_consume_replay_claim(self):
        envelope = self._envelope("correlation://synthetic/revocation-retry")
        ledger = self._ledger()
        unavailable = acknowledge_revocation(
            envelope,
            recipient_ref="agent://synthetic/reader-a",
            replay_ledger=ledger,
            outcome="unavailable",
            suppression_state="unknown",
            now=NOW,
        )
        self.assertEqual(unavailable["outcome"], "unavailable")
        with self.assertRaises(ValidationFailure):
            acknowledge_revocation(
                envelope,
                recipient_ref="agent://synthetic/reader-a",
                replay_ledger=ledger,
                outcome="acknowledged",
                suppression_state="applied",
                endpoint_receipt_refs=[[]],
                now=NOW,
            )
        acknowledged = acknowledge_revocation(
            envelope,
            recipient_ref="agent://synthetic/reader-a",
            replay_ledger=ledger,
            outcome="acknowledged",
            suppression_state="applied",
            now=NOW,
        )
        self.assertEqual(acknowledged["outcome"], "acknowledged")
        replay = acknowledge_revocation(
            envelope,
            recipient_ref="agent://synthetic/reader-a",
            replay_ledger=ledger,
            outcome="acknowledged",
            suppression_state="applied",
            now=NOW,
        )
        self.assertEqual(replay, acknowledged)

    def test_tombstone_suppresses_projection_and_context(self):
        record = self._record()
        acknowledgement = self._acknowledged()
        with self.subTest("projection"):
            import tempfile
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "record.json"
                path.write_text(json.dumps(record), encoding="utf-8")
                receipt = project_records([path], Path(temporary) / "projection", revocation_receipts=[acknowledgement])
                self.assertEqual(receipt["record_count"], 0)
                self.assertIn("revocation-suppression", json.dumps(receipt))
                malformed_receipt = copy.deepcopy(receipt)
                malformed_receipt["extensions"]["https://artifact-memory.dev/extensions/revocation-suppression/v1"]["suppressed_record_count"] = 0
                with self.assertRaises(ValidationFailure):
                    validate(malformed_receipt, load_schema("core", "projection-receipt.v1.schema.json"))
        with self.subTest("context"):
            pack = export_context(
                [record],
                authorized_record_ids=[record["record_id"]],
                freshness_by_record={record["record_id"]: {"status": "current", "assessed_at": NOW, "basis": "synthetic"}},
                selected_at=NOW,
                revocation_receipts=[acknowledgement],
            )
            self.assertEqual(pack["records"], [])
            self.assertEqual(pack["selection_receipt"]["exclusion_counts"]["revocation"], 1)
            self.assertEqual(pack["schema_id"], "artifact-memory/context-pack/v3")
            validate(pack, load_schema("core", "context-pack.v3.schema.json"))
            self.assertEqual(recall_context(json.dumps(pack, sort_keys=True, separators=(",", ":")).encode())["records"], [])
            incomplete = copy.deepcopy(pack)
            del incomplete["selection_receipt"]["revocation_receipt_refs"]
            from artifact_memory.canonical import canonical_bytes, sha256_bytes
            body = {key: value for key, value in incomplete.items() if key != "pack_id"}
            incomplete["pack_id"] = "context-pack://" + sha256_bytes(canonical_bytes(body)).removeprefix("sha-256:")
            from artifact_memory.independent_context_reader import ContextReaderFailure
            with self.assertRaises(ContextReaderFailure):
                recall_context(json.dumps(incomplete, sort_keys=True, separators=(",", ":")).encode())
            opaque = copy.deepcopy(pack)
            opaque["selection_receipt"]["revocation_receipt_refs"] = ["not-a-receipt"]
            body = {key: value for key, value in opaque.items() if key != "pack_id"}
            opaque["pack_id"] = "context-pack://" + sha256_bytes(canonical_bytes(body)).removeprefix("sha-256:")
            with self.assertRaises(ValidationFailure):
                validate(opaque, load_schema("core", "context-pack.v3.schema.json"))
            with self.assertRaises(ContextReaderFailure):
                recall_context(json.dumps(opaque, sort_keys=True, separators=(",", ":")).encode())

    def test_filter_requires_supported_tombstones_and_preserves_history(self):
        record = self._record()
        retained = copy.deepcopy(record)
        retained["record_id"] = "record://synthetic/record-0002"
        filtered = filter_revoked_records([record, retained], [self._acknowledged()])
        self.assertEqual([item["record_id"] for item in filtered], [retained["record_id"]])
        self.assertEqual(self._tombstone()["sensitive_payload_retained"], False)

    def test_fixture_inputs_are_canonical_and_replayable(self):
        record = json.loads((REVOCATION_FIXTURE / "source-record.json").read_text(encoding="utf-8"))
        marker = json.loads((REVOCATION_FIXTURE / "tombstone.json").read_text(encoding="utf-8"))
        envelope = build_revocation_envelope(
            marker, target_record=record, issuer_ref="actor://synthetic/owner",
            audience_ref="audience://synthetic/agents", correlation_id="correlation://synthetic/revocation-0001",
            expires_at="2026-08-05T00:00:00Z",
        )
        acknowledged = acknowledge_revocation(
            envelope, recipient_ref="agent://synthetic/reader-a", replay_ledger=self._ledger(), outcome="acknowledged",
            suppression_state="applied", endpoint_receipt_refs=["deletion-receipt://synthetic/endpoint-a/" + "b" * 64],
            expected_audience_ref="audience://synthetic/agents", now=NOW,
        )
        unavailable = acknowledge_revocation(
            envelope, recipient_ref="agent://synthetic/reader-b", replay_ledger=self._ledger(), outcome="unavailable",
            suppression_state="unknown", expected_audience_ref="audience://synthetic/agents", now=NOW,
        )
        self.assertEqual(aggregate_revocation(envelope, [acknowledged, unavailable]), json.loads((REVOCATION_FIXTURE / "expected-receipt.json").read_text(encoding="utf-8")))

    def test_revision_binding_replay_and_malformed_inputs_fail_closed(self):
        record = self._record()
        mismatched = copy.deepcopy(record)
        mismatched["record_id"] = "record://synthetic/record-0002"
        with self.assertRaises(ValidationFailure) as target_error:
            build_revocation_envelope(
                self._tombstone(), target_record=mismatched,
                issuer_ref="actor://synthetic/owner", audience_ref="audience://synthetic/agents",
                correlation_id="correlation://synthetic/mismatch", expires_at="2026-08-05T00:00:00Z",
            )
        self.assertEqual(target_error.exception.code, "revocation-target-mismatch")

        envelope = self._envelope()
        for endpoint_refs, diagnostics, code in [
            ([[]], [], "endpoint-receipt-invalid"),
            ([], [{"code": "bad"}], "revocation-diagnostic-invalid"),
        ]:
            with self.subTest(code=code), self.assertRaises(ValidationFailure) as raised:
                acknowledge_revocation(
                    envelope, recipient_ref="agent://synthetic/reader-a", replay_ledger=self._ledger(), outcome="acknowledged",
                    suppression_state="applied", endpoint_receipt_refs=endpoint_refs,
                    diagnostics=diagnostics, now=NOW,
                )
            self.assertEqual(raised.exception.code, code)

        ledger = self._ledger()
        first = acknowledge_revocation(
            envelope, recipient_ref="agent://synthetic/reader-a", replay_ledger=ledger, outcome="acknowledged",
            suppression_state="applied", now=NOW,
        )
        second_recipient = acknowledge_revocation(
            envelope, recipient_ref="agent://synthetic/reader-b", replay_ledger=ledger, outcome="acknowledged",
            suppression_state="applied", now=NOW,
        )
        self.assertEqual(second_recipient["outcome"], "acknowledged")
        replay = acknowledge_revocation(
            envelope, recipient_ref="agent://synthetic/reader-a", replay_ledger=ledger, outcome="acknowledged",
            suppression_state="applied", now=NOW,
        )
        self.assertEqual(replay, first)
        self.assertEqual(aggregate_revocation(envelope, [replay])["outcome"], "acknowledged")
        aggregate = aggregate_revocation(envelope, [first, second_recipient])
        self.assertEqual(aggregate["outcome"], "acknowledged")

        forged = copy.deepcopy(first)
        forged["target_revision_digest"] = "sha-256:" + "f" * 64
        from artifact_memory.canonical import expected_receipt_id
        forged["receipt_id"] = expected_receipt_id(forged, "revocation-receipt://")
        with self.assertRaises(ValidationFailure) as aggregate_error:
            aggregate_revocation(envelope, [forged])
        self.assertEqual(aggregate_error.exception.code, "revocation-receipt-mismatch")
        with self.assertRaises(ValidationFailure):
            filter_revoked_records([None], [first])

    def test_revocation_only_exempts_evidence_bound_to_the_revoked_record(self):
        record = self._record()
        record["relationships"] = [{"type": "supported-by-external-evidence", "target_ref": "binding://synthetic/revoked"}]
        marker = self._tombstone()
        envelope = build_revocation_envelope(
            marker, target_record=record, issuer_ref="actor://synthetic/owner",
            audience_ref="audience://synthetic/agents", correlation_id="correlation://synthetic/evidence",
            expires_at="2026-08-05T00:00:00Z",
        )
        acknowledgement = acknowledge_revocation(
            envelope, recipient_ref="agent://synthetic/reader-a", replay_ledger=self._ledger(), outcome="acknowledged",
            suppression_state="applied", now=NOW,
        )
        evidence = [
            {"provider_id": "synthetic", "provider_schema_id": "synthetic/v1", "provider_record_id": "revoked", "binding_ref": "binding://synthetic/revoked", "evidence_packet_ref": "artifact-version://synthetic/evidence/1", "adapter_receipt_digest": "sha-256:" + "a" * 64, "integrity_state": "unverified", "coverage": "bounded", "limitations": []},
            {"provider_id": "synthetic", "provider_schema_id": "synthetic/v1", "provider_record_id": "unrelated", "binding_ref": "binding://synthetic/unrelated", "evidence_packet_ref": "artifact-version://synthetic/evidence/2", "adapter_receipt_digest": "sha-256:" + "b" * 64, "integrity_state": "unverified", "coverage": "bounded", "limitations": []},
        ]
        from artifact_memory.context import ContextFailure
        with self.assertRaises(ContextFailure) as raised:
            export_context(
                [record], evidence, authorized_record_ids=[record["record_id"]],
                authorized_evidence=[("synthetic", "revoked"), ("synthetic", "unrelated")],
                freshness_by_record={record["record_id"]: {"status": "current", "assessed_at": NOW, "basis": "synthetic"}},
                selected_at=NOW, revocation_receipts=[acknowledgement],
            )
        self.assertEqual(raised.exception.code, "external-evidence-unbound")

    def test_context_ignores_valid_revocation_for_lifecycle_excluded_revision(self):
        record = self._record()
        record["lifecycle"] = "superseded"
        envelope = build_revocation_envelope(
            self._tombstone(), target_record=record, issuer_ref="actor://synthetic/owner",
            audience_ref="audience://synthetic/agents", correlation_id="correlation://synthetic/lifecycle-excluded",
            expires_at="2026-08-05T00:00:00Z",
        )
        acknowledgement = acknowledge_revocation(
            envelope, recipient_ref="agent://synthetic/reader-a", replay_ledger=self._ledger(), outcome="acknowledged",
            suppression_state="applied", now=NOW,
        )
        pack = export_context(
            [record], authorized_record_ids=[record["record_id"]],
            freshness_by_record={record["record_id"]: {"status": "current", "assessed_at": NOW, "basis": "synthetic"}},
            selected_at=NOW, revocation_receipts=[acknowledgement],
            supported_context_schema_ids={"artifact-memory/context-pack/v4"},
        )
        self.assertEqual(pack["records"], [])
        self.assertEqual(pack["selection_receipt"]["exclusion_counts"]["lifecycle"], 1)
        self.assertEqual(pack["selection_receipt"]["exclusion_counts"]["revocation"], 0)
        self.assertNotIn("revocation_receipt_refs", pack["selection_receipt"])


if __name__ == "__main__":
    unittest.main()
