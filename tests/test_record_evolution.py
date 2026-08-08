import copy
import json
import unittest
from pathlib import Path

from artifact_memory.context import export_context, render_context_selection_receipt
from artifact_memory.independent_context_reader import recall_context
from artifact_memory.record_evolution import (
    AUTHORITY_BOUNDARY,
    admit_candidate,
    build_candidate,
    current_records,
    render_candidate_admission_receipt,
)
from artifact_memory.independent_reader import ReaderFailure, _validate_record
from artifact_memory.independent_reader import admit_bundle_v2
from artifact_memory.conformance_helpers import SyntheticReplayLedger
from artifact_memory.exchange import admit_v2, make_envelope_v2
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import ValidationFailure, validate


ROOT = Path(__file__).resolve().parents[1]


def source_record():
    return {
        "schema_id": "artifact-memory/knowledge-record/v2",
        "record_id": "record://synthetic/decision-0001",
        "record_type": "decision",
        "lifecycle": "accepted",
        "meaning": {"summary": "Use the synthetic canonical profile.", "labels": ["synthetic"]},
        "artifact_refs": [],
        "provenance": [{"kind": "author", "source_ref": "actor://synthetic/owner"}],
        "sensitivity": "public",
    }


class RecordEvolutionTests(unittest.TestCase):
    def test_candidate_admission_binds_source_and_new_revision(self):
        source = source_record()
        from artifact_memory.record_evolution import _record_digest

        candidate_record = copy.deepcopy(source)
        candidate_record["schema_id"] = "artifact-memory/knowledge-record/v3"
        candidate_record["lifecycle"] = "draft"
        candidate_record["meaning"] = {"summary": "Use the updated synthetic canonical profile.", "labels": ["synthetic", "corrected"]}
        candidate_record["relationships"] = [{"type": "supersedes", "target_ref": source["record_id"]}]
        candidate = build_candidate(
            candidate_record,
            [{"record_id": source["record_id"], "revision_digest": _record_digest(source)}],
            [{"kind": "agent", "source_ref": "actor://synthetic/agent-b"}, {"kind": "derivation", "source_ref": "fixture://synthetic/record-evolution/v1"}],
            sensitivity="public",
        )
        validate(candidate, load_schema("core", "knowledge-candidate.v1.schema.json"))
        result = admit_candidate(
            candidate,
            decision="accepted",
            decision_ref="decision://synthetic/wits-owner-0001",
            current_source_revisions={source["record_id"]: _record_digest(source)},
            supported_result_schema_ids={"artifact-memory/knowledge-record/v3"},
        )
        self.assertEqual(result["receipt"]["outcome"], "accepted")
        self.assertEqual(result["record"]["lifecycle"], "accepted")
        self.assertEqual(result["record"]["relationships"][0]["type"], "supersedes")
        self.assertEqual(result["record"]["relationships"][0]["target_revision_digest"], _record_digest(source))
        self.assertEqual(result["receipt"]["authority_boundary"], AUTHORITY_BOUNDARY)
        self.assertNotEqual(result["receipt"]["result_record_ref"]["revision_digest"], candidate["candidate_revision_digest"])
        validate(result["receipt"], load_schema("core", "candidate-admission-receipt.v1.schema.json"))
        superseded = copy.deepcopy(source)
        superseded["lifecycle"] = "superseded"
        self.assertEqual(current_records([superseded, result["record"]]), [result["record"]])

    def test_rejected_stale_duplicate_and_unbound_relationships_are_typed(self):
        source = source_record()
        from artifact_memory.record_evolution import _record_digest

        candidate_record = copy.deepcopy(source)
        candidate_record["schema_id"] = "artifact-memory/knowledge-record/v3"
        candidate_record["lifecycle"] = "draft"
        candidate_record["meaning"] = {"summary": "Synthetic rejected proposal.", "labels": ["synthetic"]}
        candidate = build_candidate(
            candidate_record,
            [{"record_id": source["record_id"], "revision_digest": _record_digest(source)}],
            [{"kind": "agent", "source_ref": "actor://synthetic/agent-b"}],
            sensitivity="public",
        )
        rejected = admit_candidate(candidate, decision="rejected", decision_ref="decision://synthetic/reject-0001")
        self.assertEqual(rejected["receipt"]["outcome"], "rejected")
        stale = admit_candidate(candidate, decision="accepted", decision_ref="decision://synthetic/stale-0001", current_source_revisions={source["record_id"]: "sha-256:" + "f" * 64})
        self.assertEqual(stale["receipt"]["outcome"], "stale")
        duplicate = admit_candidate(candidate, decision="accepted", decision_ref="decision://synthetic/duplicate-0001", seen_candidate_ids=[candidate["candidate_id"]])
        self.assertEqual(duplicate["receipt"]["outcome"], "duplicate")
        malformed = copy.deepcopy(candidate)
        malformed["candidate_record"]["relationships"] = [{"type": "contradicts", "target_ref": source["record_id"], "target_revision_digest": "sha-256:" + "f" * 64}]
        from artifact_memory.canonical import canonical_bytes, sha256_bytes
        body = {key: value for key, value in malformed.items() if key not in {"candidate_id", "candidate_revision_digest"}}
        malformed["candidate_revision_digest"] = sha256_bytes(canonical_bytes(body))
        malformed["candidate_id"] = "candidate://actor/" + malformed["candidate_revision_digest"].removeprefix("sha-256:")
        conflict = admit_candidate(
            malformed,
            decision="accepted",
            decision_ref="decision://synthetic/conflict-0001",
            supported_result_schema_ids={"artifact-memory/knowledge-record/v3"},
        )
        self.assertEqual(conflict["receipt"]["outcome"], "conflict")

    def test_candidate_identity_tampering_fails_closed(self):
        source = source_record()
        from artifact_memory.record_evolution import _record_digest

        candidate_record = copy.deepcopy(source)
        candidate_record["schema_id"] = "artifact-memory/knowledge-record/v3"
        candidate_record["lifecycle"] = "draft"
        candidate = build_candidate(
            candidate_record,
            [{"record_id": source["record_id"], "revision_digest": _record_digest(source)}],
            [{"kind": "adapter", "source_ref": "adapter://synthetic/candidate"}],
            sensitivity="public",
        )
        candidate["candidate_revision_digest"] = "sha-256:" + "0" * 64
        with self.assertRaises(ValidationFailure):
            admit_candidate(candidate, decision="accepted", decision_ref="decision://synthetic/tampered-0001")

    def test_fixture_receipt_is_present_and_public_safe(self):
        fixture = ROOT / "fixtures/synthetic/record-evolution/v1"
        source = json.loads((fixture / "source-record.json").read_text(encoding="utf-8"))
        candidate = json.loads((fixture / "candidate.json").read_text(encoding="utf-8"))
        accepted = json.loads((fixture / "accepted-record.json").read_text(encoding="utf-8"))
        expected = json.loads((fixture / "expected-receipt.json").read_text(encoding="utf-8"))
        from artifact_memory.record_evolution import _record_digest

        validate(candidate, load_schema("core", "knowledge-candidate.v1.schema.json"))
        replay = admit_candidate(
            candidate,
            decision="accepted",
            decision_ref="decision://synthetic/wits-owner-0001",
            current_source_revisions={source["record_id"]: _record_digest(source)},
            supported_result_schema_ids={"artifact-memory/knowledge-record/v3"},
        )
        self.assertEqual(replay, {"record": accepted, "receipt": expected})
        validate(expected, load_schema("core", "candidate-admission-receipt.v1.schema.json"))
        self.assertNotIn("transcript", json.dumps(expected).lower())

    def test_v2_remains_compatible_and_v3_owns_evolution_relationships(self):
        legacy = source_record()
        legacy["relationships"] = [{"type": "supersedes", "target_ref": legacy["record_id"]}]
        with self.assertRaises(ValidationFailure):
            validate(legacy, load_schema("core", "knowledge-record.v2.schema.json"))
        legacy["schema_id"] = "artifact-memory/knowledge-record/v3"
        legacy["relationships"][0]["target_revision_digest"] = "sha-256:" + "0" * 64
        validate(legacy, load_schema("core", "knowledge-record.v3.schema.json"))

    def test_accepted_receipt_requires_a_result_record_reference(self):
        receipt = json.loads((ROOT / "fixtures/synthetic/record-evolution/v1/expected-receipt.json").read_text(encoding="utf-8"))
        receipt["result_record_ref"] = None
        with self.assertRaises(ValidationFailure):
            validate(receipt, load_schema("core", "candidate-admission-receipt.v1.schema.json"))

    def test_result_schema_requires_explicit_consumer_negotiation(self):
        candidate = json.loads((ROOT / "fixtures/synthetic/record-evolution/v1/candidate.json").read_text(encoding="utf-8"))
        result = admit_candidate(candidate, decision="accepted", decision_ref="decision://synthetic/unnegotiated")
        self.assertIsNone(result["record"])
        self.assertEqual(result["receipt"]["outcome"], "unsupported")

    def test_malformed_embedded_relationship_is_rejected_not_a_crash(self):
        """A relationship dict missing 'type' or 'target_ref' must not raise KeyError."""
        from artifact_memory.canonical import canonical_bytes, sha256_bytes

        candidate = copy.deepcopy(json.loads((ROOT / "fixtures/synthetic/record-evolution/v1/candidate.json").read_text(encoding="utf-8")))
        candidate["candidate_record"]["relationships"] = [{"target_ref": "record://synthetic/decision-0001"}]
        body = {key: value for key, value in candidate.items() if key not in {"candidate_id", "candidate_revision_digest"}}
        candidate["candidate_revision_digest"] = sha256_bytes(canonical_bytes(body))
        candidate["candidate_id"] = candidate["candidate_id"].rsplit("/", 1)[0] + "/" + candidate["candidate_revision_digest"].removeprefix("sha-256:")
        validate(candidate, load_schema("core", "knowledge-candidate.v1.schema.json"))
        result = admit_candidate(
            candidate,
            decision="accepted",
            decision_ref="decision://synthetic/malformed-relationship",
            supported_result_schema_ids={"artifact-memory/knowledge-record/v3"},
        )
        self.assertIsNone(result["record"])
        self.assertEqual(result["receipt"]["outcome"], "rejected")
        self.assertEqual(result["receipt"]["diagnostics"][0]["code"], "candidate-record-invalid")

    def test_unhashable_relationship_type_is_rejected_not_a_crash(self):
        """A relationship with a non-string, unhashable 'type' or 'target_ref' must not raise TypeError."""
        from artifact_memory.canonical import canonical_bytes, sha256_bytes

        base_candidate = json.loads((ROOT / "fixtures/synthetic/record-evolution/v1/candidate.json").read_text(encoding="utf-8"))
        malformed_relationships = [
            [{"type": [], "target_ref": "record://synthetic/decision-0001"}],
            [{"type": "supersedes", "target_ref": []}],
            [{"type": {}, "target_ref": "record://synthetic/decision-0001"}],
        ]
        for relationships in malformed_relationships:
            with self.subTest(relationships=relationships):
                candidate = copy.deepcopy(base_candidate)
                candidate["candidate_record"]["relationships"] = relationships
                body = {key: value for key, value in candidate.items() if key not in {"candidate_id", "candidate_revision_digest"}}
                candidate["candidate_revision_digest"] = sha256_bytes(canonical_bytes(body))
                candidate["candidate_id"] = candidate["candidate_id"].rsplit("/", 1)[0] + "/" + candidate["candidate_revision_digest"].removeprefix("sha-256:")
                validate(candidate, load_schema("core", "knowledge-candidate.v1.schema.json"))
                result = admit_candidate(
                    candidate,
                    decision="accepted",
                    decision_ref="decision://synthetic/unhashable-relationship",
                    supported_result_schema_ids={"artifact-memory/knowledge-record/v3"},
                )
                self.assertIsNone(result["record"])
                self.assertEqual(result["receipt"]["outcome"], "rejected")
                self.assertEqual(result["receipt"]["diagnostics"][0]["code"], "candidate-record-invalid")

    def test_empty_embedded_candidate_record_is_rejected_not_a_crash(self):
        """A schema-valid but empty candidate_record ({}) must not raise KeyError."""
        from artifact_memory.canonical import canonical_bytes, sha256_bytes

        candidate = copy.deepcopy(json.loads((ROOT / "fixtures/synthetic/record-evolution/v1/candidate.json").read_text(encoding="utf-8")))
        candidate["candidate_record"] = {}
        body = {key: value for key, value in candidate.items() if key not in {"candidate_id", "candidate_revision_digest"}}
        candidate["candidate_revision_digest"] = sha256_bytes(canonical_bytes(body))
        candidate["candidate_id"] = candidate["candidate_id"].rsplit("/", 1)[0] + "/" + candidate["candidate_revision_digest"].removeprefix("sha-256:")
        validate(candidate, load_schema("core", "knowledge-candidate.v1.schema.json"))
        result = admit_candidate(
            candidate,
            decision="accepted",
            decision_ref="decision://synthetic/empty-candidate-record",
            supported_result_schema_ids={"artifact-memory/knowledge-record/v3"},
        )
        self.assertIsNone(result["record"])
        self.assertEqual(result["receipt"]["outcome"], "rejected")
        self.assertEqual(result["receipt"]["diagnostics"][0]["code"], "candidate-record-invalid")

    def test_result_schema_negotiation_rejects_malformed_inputs(self):
        candidate = json.loads((ROOT / "fixtures/synthetic/record-evolution/v1/candidate.json").read_text(encoding="utf-8"))
        for malformed in ("artifact-memory/knowledge-record/v3", None, 7, [""]):
            with self.subTest(malformed=malformed):
                with self.assertRaisesRegex(ValidationFailure, "supported result schemas must be non-empty strings"):
                    admit_candidate(
                        candidate,
                        decision="accepted",
                        decision_ref="decision://synthetic/malformed-negotiation",
                        supported_result_schema_ids=malformed,
                    )

    def test_independent_v3_reader_covers_relationships_and_optional_shapes(self):
        base = json.loads((ROOT / "fixtures/synthetic/record-evolution/v1/accepted-record.json").read_text(encoding="utf-8"))
        for relationship_type in ("supersedes", "disputes", "contradicts"):
            with self.subTest(relationship_type=relationship_type):
                record = copy.deepcopy(base)
                record["relationships"] = [{"type": relationship_type, "target_ref": "record://synthetic/decision-0001", "target_revision_digest": "sha-256:" + "0" * 64}]
                _validate_record(record)
                record["relationships"][0]["target_ref"] = "artifact://synthetic/not-a-record"
                with self.assertRaises(ReaderFailure):
                    _validate_record(record)
                record = copy.deepcopy(base)
                del record["relationships"][0]["target_revision_digest"]
                with self.assertRaises(ReaderFailure):
                    _validate_record(record)
        invalid_values = {
            "extensions": [],
            "derivative": {"source_task_ref": "task://synthetic/one"},
            "sensitivity": 7,
        }
        for field, value in invalid_values.items():
            with self.subTest(field=field):
                record = copy.deepcopy(base)
                record[field] = value
                with self.assertRaises(ReaderFailure):
                    _validate_record(record)

    def test_negotiated_v3_record_crosses_reference_and_independent_exchange(self):
        record = json.loads((ROOT / "fixtures/synthetic/record-evolution/v1/accepted-record.json").read_text(encoding="utf-8"))
        from artifact_memory.canonical import canonical_bytes, sha256_bytes

        envelope = make_envelope_v2(
            audience_ref="audience://synthetic/v3-consumer",
            correlation_id="synthetic-v3-exchange",
            expires_at="2026-08-06T00:00:00Z",
            record_refs=[{"record_id": record["record_id"], "revision_digest": sha256_bytes(canonical_bytes(record))}],
            artifact_refs=[],
            record_bundle=[record],
        )
        expected = admit_v2(
            envelope,
            SyntheticReplayLedger(),
            expected_audience_ref="audience://synthetic/v3-consumer",
            now="2026-08-05T00:00:00Z",
            supported_record_schema_ids={"artifact-memory/knowledge-record/v1", "artifact-memory/knowledge-record/v2", "artifact-memory/knowledge-record/v3"},
        )
        independent = admit_bundle_v2(
            canonical_bytes(envelope),
            expected_audience_ref="audience://synthetic/v3-consumer",
            now="2026-08-05T00:00:00Z",
            supported_record_schema_ids={"artifact-memory/knowledge-record/v1", "artifact-memory/knowledge-record/v2", "artifact-memory/knowledge-record/v3"},
        )
        self.assertEqual(expected["outcome"], "admitted")
        self.assertEqual(independent, expected)

        unnegotiated = admit_v2(
            envelope,
            SyntheticReplayLedger(),
            expected_audience_ref="audience://synthetic/v3-consumer",
            now="2026-08-05T00:00:00Z",
        )
        independent_unnegotiated = admit_bundle_v2(
            canonical_bytes(envelope),
            expected_audience_ref="audience://synthetic/v3-consumer",
            now="2026-08-05T00:00:00Z",
        )
        self.assertEqual(unnegotiated["outcome"], "quarantined")
        self.assertIn("unsupported-record", unnegotiated["diagnostics"][0]["message"])
        self.assertEqual(independent_unnegotiated, unnegotiated)

    def test_v2_fixtures_replay_candidates_outcomes_and_context_in_full(self):
        fixture = ROOT / "fixtures/synthetic/record-evolution/v2"
        load = lambda name: json.loads((fixture / name).read_text(encoding="utf-8"))
        source = load("source-record.json")
        accepted_candidate = load("accepted-candidate.json")
        accepted = admit_candidate(
            accepted_candidate,
            decision="accepted",
            decision_ref="decision://synthetic/wits-owner-v2-accepted",
            current_source_revisions={source["record_id"]: accepted_candidate["source_record_refs"][0]["revision_digest"]},
            supported_result_schema_ids={"artifact-memory/knowledge-record/v3"},
            source_records=[source],
        )
        self.assertEqual(accepted["record"], load("accepted-record.json"))
        self.assertEqual(accepted["predecessor_records"], [load("superseded-predecessor.json")])
        self.assertEqual(accepted["receipt"], load("accepted-receipt.json"))
        self.assertEqual(
            render_candidate_admission_receipt(accepted["receipt"]),
            (fixture / "accepted-receipt.md").read_text(encoding="utf-8"),
        )

        rejected = admit_candidate(
            load("rejected-candidate.json"),
            decision="rejected",
            decision_ref="decision://synthetic/wits-owner-v2-rejected",
        )
        self.assertEqual(rejected, {
            "record": None,
            "receipt": load("rejected-receipt.json"),
            "predecessor_records": [],
        })
        self.assertEqual(
            render_candidate_admission_receipt(rejected["receipt"]),
            (fixture / "rejected-receipt.md").read_text(encoding="utf-8"),
        )

        dispute = admit_candidate(
            load("disputes-candidate.json"),
            decision="accepted",
            decision_ref="decision://synthetic/wits-owner-v2-dispute",
            current_source_revisions={source["record_id"]: accepted_candidate["source_record_refs"][0]["revision_digest"]},
            supported_result_schema_ids={"artifact-memory/knowledge-record/v3"},
        )
        self.assertEqual(dispute["record"], load("disputes-record.json"))
        self.assertEqual(dispute["predecessor_records"], [])
        self.assertEqual(dispute["receipt"], load("disputes-receipt.json"))
        self.assertEqual(
            render_candidate_admission_receipt(dispute["receipt"]),
            (fixture / "disputes-receipt.md").read_text(encoding="utf-8"),
        )

        context = export_context(
            accepted["predecessor_records"] + [accepted["record"]],
            authorized_record_ids=[source["record_id"]],
            freshness_by_record={source["record_id"]: {
                "status": "current",
                "assessed_at": "2026-08-08T00:00:00Z",
                "basis": "synthetic-admission-receipt",
            }},
            selected_at="2026-08-08T00:00:00Z",
            supported_context_schema_ids={"artifact-memory/context-pack/v4"},
        )
        self.assertEqual(context, load("current-context-pack.json"))
        self.assertEqual(context["selection_receipt"]["exclusion_counts"]["lifecycle"], 1)
        self.assertEqual(
            render_context_selection_receipt(context),
            (fixture / "current-context-receipt.md").read_text(encoding="utf-8"),
        )
        recalled = recall_context(json.dumps(context, sort_keys=True, separators=(",", ":")).encode())
        self.assertEqual(recalled["records"][0]["revision_digest"], accepted["receipt"]["result_record_ref"]["revision_digest"])

    def test_v2_identity_is_explicit_and_uncertainty_is_not_derivative(self):
        fixture = ROOT / "fixtures/synthetic/record-evolution/v2"
        expected = json.loads((fixture / "accepted-candidate.json").read_text(encoding="utf-8"))
        rebuilt = build_candidate(
            expected["candidate_record"],
            reversed(expected["source_record_refs"]),
            reversed(expected["candidate_provenance"]),
            sensitivity="public",
            candidate_namespace="synthetic-evolution",
            bounded_input_refs=reversed(expected["candidate_scope"]["bounded_input_refs"]),
            uncertainty="Owner confirmation remains required.",
        )
        self.assertEqual(rebuilt, expected)
        self.assertNotIn("derivative", rebuilt["candidate_record"])
        self.assertEqual(rebuilt["uncertainty"], "Owner confirmation remains required.")
        unsorted = copy.deepcopy(expected)
        unsorted["candidate_scope"]["bounded_input_refs"].reverse()
        with self.assertRaisesRegex(ValidationFailure, "canonical order"):
            admit_candidate(
                unsorted,
                decision="rejected",
                decision_ref="decision://synthetic/unsorted",
            )
        for malformed in ("plain text", "https://contains space", "//missing-scheme"):
            with self.subTest(malformed=malformed):
                provenance = copy.deepcopy(expected["candidate_provenance"])
                provenance[0]["source_ref"] = malformed
                with self.assertRaises(ValidationFailure):
                    build_candidate(
                        expected["candidate_record"],
                        expected["source_record_refs"],
                        provenance,
                        candidate_namespace="synthetic-evolution",
                        bounded_input_refs=expected["candidate_scope"]["bounded_input_refs"],
                    )

    def test_v2_supersession_requires_exact_current_predecessor(self):
        fixture = ROOT / "fixtures/synthetic/record-evolution/v2"
        candidate = json.loads((fixture / "accepted-candidate.json").read_text(encoding="utf-8"))
        result = admit_candidate(
            candidate,
            decision="accepted",
            decision_ref="decision://synthetic/missing-predecessor",
            supported_result_schema_ids={"artifact-memory/knowledge-record/v3"},
        )
        self.assertIsNone(result["record"])
        self.assertEqual(result["receipt"]["outcome"], "conflict")
        self.assertEqual(result["receipt"]["diagnostics"][0]["code"], "predecessor-transition-unproven")


if __name__ == "__main__":
    unittest.main()
