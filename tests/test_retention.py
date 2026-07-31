import json
import unittest
from pathlib import Path

from artifact_memory.retention import content_retrievability, deletion_receipt, deletion_request, overall_deletion_status, retention_disposition, tombstone
from artifact_memory.validator import ValidationFailure, validate


ROOT = Path(__file__).resolve().parents[1]


class RetentionTests(unittest.TestCase):
    def test_unauthorized_request_does_not_mutate_and_tombstone_is_minimal(self):
        receipt = deletion_request("content://synthetic/order-sample/sha256", "managed-backup", authorized=False, endpoint_ref="endpoint://synthetic/backup", generation_ref="generation-0001", observed_at="2026-07-31T00:00:00Z")
        schema = json.loads((ROOT / "artifact_memory/schemas/core/deletion-receipt.v2.schema.json").read_text(encoding="utf-8"))
        validate(receipt, schema)
        self.assertEqual(receipt["outcome"], "not-authorized")
        self.assertFalse(receipt["global_erasure_claim"])
        marker = tombstone(receipt["target_ref"], "accidental-ingestion", "bytes-location-unknown", receipt["receipt_id"], created_at="2026-07-31T00:00:00Z")
        tombstone_schema = json.loads((ROOT / "artifact_memory/schemas/core/tombstone.v2.schema.json").read_text(encoding="utf-8"))
        validate(marker, tombstone_schema)
        self.assertNotIn("byte_payload", marker)
        self.assertFalse(marker["sensitive_payload_retained"])

    def test_backup_retention_keeps_status_partial(self):
        receipts = [
            deletion_request("content://synthetic/order-sample/sha256", "active-vault", authorized=True, observed_at="2026-07-31T00:00:00Z"),
            {"outcome": "retained-until-expiry"},
        ]
        self.assertEqual(overall_deletion_status(receipts), "partially-complete")

    def test_endpoint_outcomes_are_scoped_and_unknown_replicas_keep_result_partial(self):
        receipt = deletion_receipt(
            "content://synthetic/order-sample/sha256",
            "active-vault",
            "verified-absent-at-endpoint",
            observed_at="2026-07-31T00:00:00Z",
            managed_scope=True,
            endpoint_ref="endpoint://synthetic/active-vault",
            evidence_refs=["projection-receipt://synthetic/rebuild"],
        )
        schema = json.loads((ROOT / "artifact_memory/schemas/core/deletion-receipt.v2.schema.json").read_text(encoding="utf-8"))
        validate(receipt, schema)
        self.assertFalse(receipt["global_erasure_claim"])
        self.assertEqual(overall_deletion_status([receipt]), "partially-complete")
        self.assertEqual(overall_deletion_status([receipt], unknown_replicas=False), "verified-absent-at-endpoint")

    def test_endpoint_outcome_requires_named_endpoint(self):
        with self.assertRaisesRegex(ValueError, "endpoint_ref"):
            deletion_receipt(
                "content://synthetic/order-sample/sha256",
                "managed-backup",
                "retained-until-expiry",
                observed_at="2026-07-31T00:00:00Z",
                managed_scope=True,
            )

    def test_managed_backup_receipt_requires_named_generation(self):
        with self.assertRaisesRegex(ValueError, "generation_ref"):
            deletion_receipt(
                "content://synthetic/order-sample/sha256",
                "managed-backup",
                "endpoint-unavailable",
                observed_at="2026-07-31T00:00:00Z",
                managed_scope=True,
                endpoint_ref="endpoint://synthetic/backup",
            )

    def test_owner_and_legal_holds_defer_deletion(self):
        policy = {
            "schema_id": "artifact-memory/retention-policy/v2",
            "policy_id": "retention-policy://synthetic/hold",
            "retention_class": "standard",
            "owner_ref": "actor://synthetic/owner",
            "owner_hold": True,
            "legal_hold": False,
            "expires_at": "2026-01-01T00:00:00Z",
            "backup_expiry_behavior": "managed-expiry",
            "unknown_replica_behavior": "report-scope-unknown",
            "git_history_behavior": "separate-rewrite-authorization-required",
            "deletion_authority": "separate-owner-or-legal-authorization-required",
        }
        self.assertEqual(retention_disposition(policy, now="2026-07-31T00:00:00Z"), "retained-under-hold")
        legal = {**policy, "retention_class": "legal-hold", "owner_hold": False, "legal_hold": True}
        self.assertEqual(retention_disposition(legal, now="2026-07-31T00:00:00Z"), "retained-under-hold")

    def test_expiry_only_makes_content_eligible_for_separate_authorization(self):
        policy = {
            "schema_id": "artifact-memory/retention-policy/v2",
            "policy_id": "retention-policy://synthetic/expiry",
            "retention_class": "deferred-expiry",
            "owner_ref": "actor://synthetic/owner",
            "owner_hold": False,
            "legal_hold": False,
            "expires_at": "2026-08-31T00:00:00Z",
            "backup_expiry_behavior": "managed-expiry",
            "unknown_replica_behavior": "report-scope-unknown",
            "git_history_behavior": "separate-rewrite-authorization-required",
            "deletion_authority": "separate-owner-or-legal-authorization-required",
        }
        self.assertEqual(retention_disposition(policy, now="2026-07-31T00:00:00Z"), "retained-until-expiry")
        self.assertEqual(retention_disposition(policy, now="2026-09-01T00:00:00Z"), "eligible-for-separately-authorized-deletion")

    def test_zero_verified_locations_remains_explicit(self):
        base = {
            "schema_id": "artifact-memory/location-observation/v1",
            "content_ref": "content://synthetic/object",
            "relative_path": "objects/object.bin",
            "observed_at": "2026-07-31T00:00:00Z",
        }
        absent = {
            **base,
            "observation_id": "location-observation://synthetic/absent",
            "endpoint_ref": "endpoint://synthetic/active-vault",
            "presence": "verified-absent-at-endpoint",
        }
        unavailable = {
            **base,
            "observation_id": "location-observation://synthetic/unavailable",
            "endpoint_ref": "endpoint://synthetic/backup",
            "presence": "unavailable",
        }
        self.assertEqual(content_retrievability([absent, unavailable]), "zero-currently-verified-retrievable-locations")
        present = {**absent, "observation_id": "location-observation://synthetic/present", "presence": "present"}
        self.assertEqual(content_retrievability([absent, present]), "verified-retrievable-location-observed")

    def test_unknown_replica_scope_rejects_contradictory_outcomes_and_locations(self):
        with self.assertRaisesRegex(ValueError, "scope-unknown"):
            deletion_receipt(
                "content://synthetic/order-sample/sha256",
                "unknown-replica",
                "requested",
                observed_at="2026-07-31T00:00:00Z",
                managed_scope=False,
            )
        with self.assertRaisesRegex(ValueError, "cannot name"):
            deletion_receipt(
                "content://synthetic/order-sample/sha256",
                "unknown-replica",
                "scope-unknown",
                observed_at="2026-07-31T00:00:00Z",
                managed_scope=False,
                endpoint_ref="endpoint://synthetic/unknown",
            )

    def test_observed_outcomes_require_evidence(self):
        with self.assertRaisesRegex(ValueError, "evidence_refs"):
            deletion_receipt(
                "content://synthetic/order-sample/sha256",
                "active-vault",
                "verified-absent-at-endpoint",
                observed_at="2026-07-31T00:00:00Z",
                managed_scope=True,
                endpoint_ref="endpoint://synthetic/active-vault",
            )

    def test_v2_schemas_enforce_cross_field_invariants_without_builder(self):
        deletion_schema = json.loads((ROOT / "artifact_memory/schemas/core/deletion-receipt.v2.schema.json").read_text(encoding="utf-8"))
        valid = deletion_receipt(
            "content://synthetic/order-sample/sha256",
            "active-vault",
            "verified-absent-at-endpoint",
            observed_at="2026-07-31T00:00:00Z",
            managed_scope=True,
            endpoint_ref="endpoint://synthetic/active-vault",
            evidence_refs=["observation://synthetic/absence"],
        )
        for malformed in (
            {key: value for key, value in valid.items() if key != "endpoint_ref"},
            {key: value for key, value in valid.items() if key != "evidence_refs"},
            {**valid, "scope": "managed-backup"},
        ):
            with self.assertRaises(ValidationFailure):
                validate(malformed, deletion_schema)

        policy_schema = json.loads((ROOT / "artifact_memory/schemas/core/retention-policy.v2.schema.json").read_text(encoding="utf-8"))
        deferred = {
            "schema_id": "artifact-memory/retention-policy/v2",
            "policy_id": "retention-policy://synthetic/malformed",
            "retention_class": "deferred-expiry",
            "owner_ref": "actor://synthetic/owner",
            "owner_hold": False,
            "legal_hold": False,
            "backup_expiry_behavior": "managed-expiry",
            "unknown_replica_behavior": "report-scope-unknown",
            "git_history_behavior": "separate-rewrite-authorization-required",
            "deletion_authority": "separate-owner-or-legal-authorization-required",
        }
        with self.assertRaises(ValidationFailure):
            validate(deferred, policy_schema)
        with self.assertRaises(ValidationFailure):
            validate({**deferred, "retention_class": "legal-hold"}, policy_schema)

        unknown = {
            **valid,
            "scope": "unknown-replica",
            "outcome": "scope-unknown",
            "managed_scope": False,
        }
        with self.assertRaises(ValidationFailure):
            validate(unknown, deletion_schema)

    def test_v1_contracts_remain_valid_and_v2_upgrade_is_explicit(self):
        legacy_policy = {
            "schema_id": "artifact-memory/retention-policy/v1",
            "policy_id": "retention-policy://synthetic/legacy",
            "retention_class": "standard",
            "owner_ref": "actor://synthetic/owner",
            "legal_hold": False,
            "backup_expiry_behavior": "managed-expiry",
        }
        legacy_deletion = {
            "schema_id": "artifact-memory/deletion-receipt/v1",
            "receipt_id": "deletion-receipt://synthetic/" + "a" * 64,
            "target_ref": "record://synthetic/legacy",
            "scope": "active-vault",
            "outcome": "requested",
            "global_erasure_claim": False,
            "limitations": [],
        }
        legacy_tombstone = {
            "schema_id": "artifact-memory/tombstone/v1",
            "tombstone_id": "tombstone://" + "b" * 64,
            "target_ref": "record://synthetic/legacy",
            "reason": "superseded",
            "content_status": "bytes-location-unknown",
            "deletion_receipt_ref": legacy_deletion["receipt_id"],
        }
        for name, value in (
            ("retention-policy.v1.schema.json", legacy_policy),
            ("deletion-receipt.v1.schema.json", legacy_deletion),
            ("tombstone.v1.schema.json", legacy_tombstone),
        ):
            schema = json.loads((ROOT / "artifact_memory/schemas/core" / name).read_text(encoding="utf-8"))
            validate(value, schema)

        v2_schema = json.loads((ROOT / "artifact_memory/schemas/core/retention-policy.v2.schema.json").read_text(encoding="utf-8"))
        with self.assertRaises(ValidationFailure):
            validate(legacy_policy, v2_schema)


if __name__ == "__main__":
    unittest.main()
