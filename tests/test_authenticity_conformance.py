import json
import tempfile
import unittest
from pathlib import Path

from artifact_memory.authenticity_conformance import render_authenticity_receipt, run_authenticity_conformance
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import ValidationFailure, validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "security"


class AuthenticityConformanceTests(unittest.TestCase):
    def test_checked_in_machine_and_human_receipts_replay_exactly(self):
        receipt = run_authenticity_conformance(FIXTURE / "authenticity-v0-v2.json")
        expected = json.loads((FIXTURE / "authenticity-v0-v2-expected-receipt.json").read_text(encoding="utf-8"))
        expected_markdown = (FIXTURE / "authenticity-v0-v2-receipt.md").read_text(encoding="utf-8")
        self.assertEqual(receipt, expected)
        self.assertEqual(render_authenticity_receipt(receipt), expected_markdown)
        validate(receipt, load_schema("core", "authenticity-conformance-receipt.v1.schema.json"))

    def test_malformed_vector_inputs_fail_with_structured_diagnostics(self):
        vectors = json.loads((FIXTURE / "authenticity-v0-v2.json").read_text(encoding="utf-8"))
        for mutate in (
            lambda value: value[0]["input"].pop("evaluated_at"),
            lambda value: value[0]["input"].update({"unknown": True}),
            lambda value: value[0]["input"].update({"requirement": ""}),
        ):
            malformed = json.loads(json.dumps(vectors))
            mutate(malformed)
            with self.subTest(malformed=malformed[0]["input"]), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "vectors.json"
                path.write_text(json.dumps(malformed), encoding="utf-8")
                with self.assertRaises(ValidationFailure) as raised:
                    run_authenticity_conformance(path)
                self.assertEqual(raised.exception.code, "invalid-vector")


if __name__ == "__main__":
    unittest.main()
