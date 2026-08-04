import copy
import json
import unittest
from pathlib import Path

from artifact_memory.record_evolution import AUTHORITY_BOUNDARY, admit_candidate, build_candidate, current_records
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
        )
        self.assertEqual(result["receipt"]["outcome"], "accepted")
        self.assertEqual(result["record"]["lifecycle"], "accepted")
        self.assertEqual(result["record"]["relationships"][0]["type"], "supersedes")
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
        malformed["candidate_record"]["relationships"] = [{"type": "contradicts", "target_ref": "record://synthetic/other-0001"}]
        from artifact_memory.canonical import canonical_bytes, sha256_bytes
        body = {key: value for key, value in malformed.items() if key not in {"candidate_id", "candidate_revision_digest"}}
        malformed["candidate_revision_digest"] = sha256_bytes(canonical_bytes(body))
        malformed["candidate_id"] = "candidate://actor/" + malformed["candidate_revision_digest"].removeprefix("sha-256:")
        conflict = admit_candidate(malformed, decision="accepted", decision_ref="decision://synthetic/conflict-0001")
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
        validate(legacy, load_schema("core", "knowledge-record.v3.schema.json"))

    def test_accepted_receipt_requires_a_result_record_reference(self):
        receipt = json.loads((ROOT / "fixtures/synthetic/record-evolution/v1/expected-receipt.json").read_text(encoding="utf-8"))
        receipt["result_record_ref"] = None
        with self.assertRaises(ValidationFailure):
            validate(receipt, load_schema("core", "candidate-admission-receipt.v1.schema.json"))


if __name__ == "__main__":
    unittest.main()
