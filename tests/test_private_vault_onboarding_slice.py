import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from artifact_memory import private_vault_onboarding_slice as onboarding
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

    def _copied_fixture(self, temporary: str) -> tuple[Path, Path]:
        copied_fixture = Path(temporary) / "fixture"
        shutil.copytree(FIXTURE, copied_fixture)
        return copied_fixture, copied_fixture / "records/operations/relay-connectivity.json"

    def test_fixture_boundary_rejects_each_network_or_machine_binding(self):
        forbidden_summaries = (
            "Synthetic contact uses operator" + chr(64) + "example.invalid.",
            "Synthetic relay uses node" + ".internal for routing.",
            "Synthetic relay uses address " + "10" + ".0.0.7.",
            "Synthetic relay uses address " + "2001" + ":db8::7.",
            "Synthetic source is " + "/" + "Users/example/project.",
        )
        for summary in forbidden_summaries:
            with self.subTest(kind=summary.split()[1]):
                with tempfile.TemporaryDirectory() as temporary:
                    copied_fixture, record_path = self._copied_fixture(temporary)
                    record = json.loads(record_path.read_text(encoding="utf-8"))
                    record["meaning"]["summary"] = summary
                    record_path.write_text(json.dumps(record), encoding="utf-8")
                    with self.assertRaisesRegex(ValidationFailure, "forbidden category"):
                        run_private_vault_onboarding_slice(
                            copied_fixture,
                            Path(temporary) / "workspace",
                        )

    def test_fixture_boundary_rejects_each_credential_key_form(self):
        for credential_key in (
            "to" + "ken",
            "api" + "Key",
            "auth" + "Token",
            "refresh" + "Token",
        ):
            with self.subTest(credential_key=credential_key):
                with tempfile.TemporaryDirectory() as temporary:
                    copied_fixture, record_path = self._copied_fixture(temporary)
                    record = json.loads(record_path.read_text(encoding="utf-8"))
                    record["extensions"] = {
                        "synthetic-extension": {credential_key: "synthetic-placeholder"}
                    }
                    record_path.write_text(json.dumps(record), encoding="utf-8")
                    with self.assertRaisesRegex(ValidationFailure, "forbidden category"):
                        run_private_vault_onboarding_slice(
                            copied_fixture,
                            Path(temporary) / "workspace",
                        )

    def test_fixture_boundary_rejects_raw_source_material(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied_fixture, _ = self._copied_fixture(temporary)
            (copied_fixture / "records/operations/source.txt").write_text(
                "synthetic raw source that does not belong in the fixture",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValidationFailure, "forbidden category"):
                run_private_vault_onboarding_slice(copied_fixture, Path(temporary) / "workspace")

    def test_failed_search_receipt_and_human_rendering_are_honest(self):
        mismatched_cases = (
            (
                onboarding.SEARCH_CASES[0][0],
                ["record://synthetic-onboarding/unexpected"],
            ),
            onboarding.SEARCH_CASES[1],
        )
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(onboarding, "SEARCH_CASES", mismatched_cases):
                receipt = run_private_vault_onboarding_slice(FIXTURE, Path(temporary))
        self.assertEqual(receipt["outcome"], "failed")
        validate(
            receipt,
            load_schema("core", "private-vault-onboarding-slice-receipt.v1.schema.json"),
        )
        rendered = render_private_vault_onboarding_receipt(receipt)
        self.assertIn("Operational searches executed: `2`; outcome: `failed`", rendered)
        self.assertNotIn("searches verified", rendered.casefold())


if __name__ == "__main__":
    unittest.main()
