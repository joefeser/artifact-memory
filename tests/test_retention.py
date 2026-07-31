import json
import unittest
from pathlib import Path

from artifact_memory.retention import content_retrievability, deletion_receipt, deletion_request, overall_deletion_status, retention_disposition, tombstone
from artifact_memory.validator import validate


ROOT = Path(__file__).resolve().parents[1]


class RetentionTests(unittest.TestCase):
    def test_unauthorized_request_does_not_mutate_and_tombstone_is_minimal(self):
        receipt = deletion_request("content://synthetic/order-sample/sha256", "managed-backup", authorized=False, endpoint_ref="endpoint://synthetic/backup", generation_ref="generation-0001")
        schema = json.loads((ROOT / "artifact_memory/schemas/core/deletion-receipt.v1.schema.json").read_text(encoding="utf-8"))
        validate(receipt, schema)
        self.assertEqual(receipt["outcome"], "not-authorized")
        self.assertFalse(receipt["global_erasure_claim"])
        marker = tombstone(receipt["target_ref"], "accidental-ingestion", "bytes-location-unknown", receipt["receipt_id"], created_at="2026-07-31T00:00:00Z")
        tombstone_schema = json.loads((ROOT / "artifact_memory/schemas/core/tombstone.v1.schema.json").read_text(encoding="utf-8"))
        validate(marker, tombstone_schema)
        self.assertNotIn("byte_payload", marker)
        self.assertFalse(marker["sensitive_payload_retained"])

    def test_backup_retention_keeps_status_partial(self):
        receipts = [
            deletion_request("content://synthetic/order-sample/sha256", "active-vault", authorized=True),
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
        schema = json.loads((ROOT / "artifact_memory/schemas/core/deletion-receipt.v1.schema.json").read_text(encoding="utf-8"))
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
            "schema_id": "artifact-memory/retention-policy/v1",
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
            "schema_id": "artifact-memory/retention-policy/v1",
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


if __name__ == "__main__":
    unittest.main()
