import json
import unittest
from pathlib import Path

from artifact_memory.retention_lifecycle_slice import run_retention_lifecycle_slice


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "retention-lifecycle" / "v1"


class RetentionLifecycleSliceTests(unittest.TestCase):
    def test_checked_lifecycle_receipt_is_reproducible_and_partial(self):
        actual = run_retention_lifecycle_slice(FIXTURE)
        expected = json.loads((FIXTURE / "expected-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(actual, expected)
        self.assertEqual(actual["overall_deletion_outcome"], "partially-complete")
        self.assertFalse(actual["global_erasure_claim"])
        self.assertEqual(actual["managed_backup_state"], "retained-until-expiry")
        self.assertEqual(actual["unknown_replica_state"], "scope-unknown")
        self.assertEqual(actual["generated_index_rebuild"], "deleted-content-absent")


if __name__ == "__main__":
    unittest.main()
