import json
import shutil
import tempfile
import unittest
from pathlib import Path

from artifact_memory.private_vault_onboarding_slice import (
    render_private_vault_onboarding_receipt,
    run_private_vault_onboarding_slice,
)
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import ValidationFailure, validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "private-vault-onboarding" / "v1"


class PrivateVaultOnboardingSliceTests(unittest.TestCase):
    def test_checked_in_receipts_replay_exactly(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            receipt = run_private_vault_onboarding_slice(FIXTURE, workspace)
            self.assertTrue((workspace / "generated/search-projection/records.sqlite").is_file())
            self.assertTrue((workspace / "generated/context-pack-operator-startup/context-pack.json").is_file())
            self.assertFalse((FIXTURE / "generated").exists())

        expected = json.loads((FIXTURE / "expected-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt, expected)
        self.assertEqual(receipt["outcome"], "complete")
        self.assertEqual(receipt["public_fixture_safety"]["forbidden_category_match_count"], 0)
        self.assertEqual(receipt["context"]["schema_id"], "artifact-memory/context-pack/v4")
        self.assertLessEqual(receipt["context"]["serialized_bytes"], receipt["context"]["max_bytes"])
        self.assertEqual(receipt["context"]["mutation_authority"], "absent")
        self.assertEqual(receipt["context"]["disclosure_authority"], "absent")
        self.assertEqual(receipt["context"]["execution_authority"], "absent")
        validate(
            receipt,
            load_schema("core", "private-vault-onboarding-slice-receipt.v1.schema.json"),
        )
        self.assertEqual(
            render_private_vault_onboarding_receipt(receipt),
            (FIXTURE / "receipt.md").read_text(encoding="utf-8"),
        )

    def test_fixture_has_only_canonical_json_under_records(self):
        record_root = FIXTURE / "records"
        files = sorted(path for path in record_root.rglob("*") if path.is_file())
        self.assertTrue(files)
        self.assertTrue(all(path.suffix == ".json" for path in files))
        self.assertTrue(all("synthetic-onboarding" in path.read_text(encoding="utf-8") for path in files))

    def test_fixture_boundary_rejects_contact_or_raw_source_material(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied_fixture = Path(temporary) / "fixture"
            shutil.copytree(FIXTURE, copied_fixture)
            record_path = copied_fixture / "records/operations/relay-connectivity.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["meaning"]["summary"] = (
                "Synthetic contact uses operator" + chr(64) + "example.invalid."
            )
            record_path.write_text(json.dumps(record), encoding="utf-8")
            (copied_fixture / "records/operations/source.txt").write_text(
                "synthetic raw source that does not belong in the fixture",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValidationFailure, "forbidden category"):
                run_private_vault_onboarding_slice(copied_fixture, Path(temporary) / "workspace")


if __name__ == "__main__":
    unittest.main()
