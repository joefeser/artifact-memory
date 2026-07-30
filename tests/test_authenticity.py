import json
import unittest
from pathlib import Path

from artifact_memory.authenticity import UNSIGNED_STATE, evaluate
from artifact_memory.validator import validate


ROOT = Path(__file__).resolve().parents[1]


class AuthenticityTests(unittest.TestCase):
    def test_unsigned_trace_evidence_is_labeled_without_authority(self):
        receipt = evaluate("artifact-version://synthetic/orders/1", True, True)
        schema = json.loads((ROOT / "schemas/core/authenticity-receipt.v1.schema.json").read_text(encoding="utf-8"))
        validate(receipt, schema)
        self.assertEqual(receipt["integrity_state"], UNSIGNED_STATE)
        self.assertEqual(receipt["authenticity_state"], "issuer-unverified")
        self.assertEqual(receipt["authorization_state"], "not-granted")

    def test_authenticity_required_fails_closed(self):
        receipt = evaluate("artifact-version://synthetic/orders/1", True, True, authenticity_required=True)
        self.assertEqual(receipt["outcome"], "rejected")
        self.assertEqual(receipt["authenticity_state"], "authenticity-required-unmet")

    def test_signed_input_is_explicitly_unsupported(self):
        receipt = evaluate("artifact-version://synthetic/orders/1", True, True, signed_input=True)
        self.assertEqual(receipt["outcome"], "unsupported")
        self.assertEqual(receipt["authenticity_state"], "signed-input-unsupported")


if __name__ == "__main__":
    unittest.main()
