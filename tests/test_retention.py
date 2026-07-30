import json
import unittest
from pathlib import Path

from artifact_memory.retention import deletion_request, overall_deletion_status, tombstone
from artifact_memory.validator import validate


ROOT = Path(__file__).resolve().parents[1]


class RetentionTests(unittest.TestCase):
    def test_unauthorized_request_does_not_mutate_and_tombstone_is_minimal(self):
        receipt = deletion_request("content://synthetic/order-sample/sha256", "managed-backup", authorized=False, endpoint_ref="endpoint://synthetic/backup", generation_ref="generation-0001")
        schema = json.loads((ROOT / "schemas/core/deletion-receipt.v1.schema.json").read_text(encoding="utf-8"))
        validate(receipt, schema)
        self.assertEqual(receipt["outcome"], "not-authorized")
        self.assertFalse(receipt["global_erasure_claim"])
        marker = tombstone(receipt["target_ref"], "accidental-ingestion", "bytes-location-unknown", receipt["receipt_id"])
        tombstone_schema = json.loads((ROOT / "schemas/core/tombstone.v1.schema.json").read_text(encoding="utf-8"))
        validate(marker, tombstone_schema)
        self.assertNotIn("byte_payload", marker)

    def test_backup_retention_keeps_status_partial(self):
        receipts = [
            deletion_request("content://synthetic/order-sample/sha256", "active-vault", authorized=True),
            {"outcome": "retained-until-expiry"},
        ]
        self.assertEqual(overall_deletion_status(receipts), "partially-complete")


if __name__ == "__main__":
    unittest.main()
