import json
import shutil
import tempfile
import unittest
from pathlib import Path

from artifact_memory.vault_intake_conformance import render_vault_intake_receipt, run_vault_intake_conformance
from artifact_memory.validator import ValidationFailure


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/synthetic/vault-intake/v1"


class VaultIntakeConformanceTests(unittest.TestCase):
    def test_checked_machine_and_human_receipts_replay(self):
        receipt = run_vault_intake_conformance(FIXTURE)
        expected = json.loads((FIXTURE / "expected-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt, expected)
        self.assertEqual(render_vault_intake_receipt(receipt), (FIXTURE / "receipt.md").read_text(encoding="utf-8"))

    def test_unknown_vector_contract_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "fixture"
            shutil.copytree(FIXTURE, copied)
            vector_path = copied / "vector.json"
            vector = json.loads(vector_path.read_text(encoding="utf-8"))
            vector["schema_id"] = "artifact-memory/vault-intake-vector/v2"
            vector_path.write_text(json.dumps(vector), encoding="utf-8")
            with self.assertRaises(ValidationFailure) as raised:
                run_vault_intake_conformance(copied)
            self.assertEqual(raised.exception.code, "vector-invalid")

    def test_malformed_vector_intake_fails_with_typed_error(self):
        mutations = (
            lambda vector: vector["intake"].pop("artifact_id"),
            lambda vector: vector["intake"].update({"unexpected": "value"}),
            lambda vector: vector["intake"].update({"title": 7}),
            lambda vector: vector["intake"].update({"expected_digest": "sha-256:" + "0" * 64}),
            lambda vector: vector["intake"].update({"source_ref": "https://example.test/object"}),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate), tempfile.TemporaryDirectory() as temporary:
                copied = Path(temporary) / "fixture"
                shutil.copytree(FIXTURE, copied)
                vector_path = copied / "vector.json"
                vector = json.loads(vector_path.read_text(encoding="utf-8"))
                mutate(vector)
                vector_path.write_text(json.dumps(vector), encoding="utf-8")
                with self.assertRaises(ValidationFailure) as raised:
                    run_vault_intake_conformance(copied)
                self.assertEqual(raised.exception.code, "vector-invalid")


if __name__ == "__main__":
    unittest.main()
