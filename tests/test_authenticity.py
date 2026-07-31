import json
import unittest
from pathlib import Path

from artifact_memory.authenticity import AUTHORITY_BOUNDARY, INTEGRITY_VERIFIED_STATE, evaluate
from artifact_memory.canonical import receipt_with_digest
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import ValidationFailure, validate


ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "fixtures" / "synthetic" / "security" / "authenticity-v0-v2.json"
EVALUATED_AT = "2026-07-31T00:00:00Z"


class AuthenticityTests(unittest.TestCase):
    def test_synthetic_v0_matrix_is_deterministic_and_schema_valid(self):
        vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
        schema = load_schema("core", "authenticity-receipt.v2.schema.json")
        for vector in vectors:
            with self.subTest(vector=vector["case"]):
                receipt = evaluate(**vector["input"])
                validate(receipt, schema)
                self.assertEqual(receipt["outcome"], vector["expected"]["outcome"])
                self.assertEqual(receipt["integrity_state"], vector["expected"]["integrity_state"])
                self.assertEqual(receipt["authenticity_state"], vector["expected"]["authenticity_state"])
                self.assertEqual(receipt["transport_state"], vector["expected"]["transport_state"])
                self.assertEqual(receipt, evaluate(**vector["input"]))

    def test_unsigned_trace_evidence_is_labeled_without_authority_or_trust(self):
        receipt = evaluate(
            "artifact-version://synthetic/orders/1",
            True,
            True,
            issuer_ref="actor://synthetic/tracemap-exporter",
            audience_ref="audience://synthetic/receiver",
            transport_authenticated=True,
            evaluated_at=EVALUATED_AT,
        )
        self.assertEqual(receipt["schema_id"], "artifact-memory/authenticity-receipt/v2")
        self.assertEqual(receipt["integrity_state"], INTEGRITY_VERIFIED_STATE)
        self.assertEqual(receipt["issuer_identity_state"], "self-asserted / unverified")
        self.assertEqual(receipt["authenticity_state"], "issuer-unverified")
        self.assertEqual(receipt["authorization_state"], "not-granted")
        self.assertEqual(receipt["trust_state"], "not-established")
        self.assertEqual(receipt["authority_boundary"], AUTHORITY_BOUNDARY)
        self.assertEqual(receipt["transport_state"], "channel-authenticated / subject-issuer-unverified")
        self.assertNotIn("signer_key_ref", receipt)
        self.assertNotIn("algorithm", receipt)

    def test_authenticity_required_fails_closed_for_unsigned_and_signed_inputs(self):
        for signed_input in (False, True):
            with self.subTest(signed_input=signed_input):
                receipt = evaluate(
                    "artifact-version://synthetic/orders/1",
                    True,
                    True,
                    authenticity_required=True,
                    signed_input=signed_input,
                    evaluated_at=EVALUATED_AT,
                )
                self.assertEqual(receipt["outcome"], "rejected")
                self.assertEqual(receipt["authenticity_state"], "authenticity-required-unmet")

    def test_signed_input_is_unsupported_when_authenticity_is_not_required(self):
        receipt = evaluate(
            "artifact-version://synthetic/orders/1",
            True,
            True,
            signed_input=True,
            evaluated_at=EVALUATED_AT,
        )
        self.assertEqual(receipt["outcome"], "unsupported")
        self.assertEqual(receipt["authenticity_state"], "signed-input-unsupported")

    def test_integrity_failure_or_unverified_integrity_rejects_before_admission(self):
        failed = evaluate(
            "artifact-version://synthetic/orders/1", False, True, evaluated_at=EVALUATED_AT
        )
        unverified = evaluate(
            "artifact-version://synthetic/orders/1", None, True, evaluated_at=EVALUATED_AT
        )
        self.assertEqual(failed["integrity_state"], "integrity-failed")
        self.assertEqual(unverified["integrity_state"], "integrity-unverified")
        self.assertEqual(failed["outcome"], "rejected")
        self.assertEqual(unverified["outcome"], "rejected")

    def test_schema_rejects_forged_required_authenticity_and_signer_metadata(self):
        schema = load_schema("core", "authenticity-receipt.v2.schema.json")
        receipt = evaluate(
            "artifact-version://synthetic/orders/1",
            True,
            True,
            authenticity_required=True,
            evaluated_at=EVALUATED_AT,
        )
        body = {key: value for key, value in receipt.items() if key not in {"schema_id", "receipt_id"}}
        forged = receipt_with_digest(
            "artifact-memory/authenticity-receipt/v2",
            "authenticity-receipt://",
            {**body, "authenticity_state": "issuer-unverified", "outcome": "accepted"},
        )
        with self.assertRaises(ValidationFailure):
            validate(forged, schema)
        signed_metadata = {**receipt, "signer_key_ref": "key://synthetic/not-admitted"}
        with self.assertRaises(ValidationFailure):
            validate(signed_metadata, schema)
        contradictory = receipt_with_digest(
            "artifact-memory/authenticity-receipt/v2",
            "authenticity-receipt://",
            {
                **body,
                "requirement": "authenticity-optional",
                "authenticity_state": "authenticity-required-unmet",
                "outcome": "rejected",
            },
        )
        with self.assertRaises(ValidationFailure):
            validate(contradictory, schema)

    def test_invalid_assessment_arguments_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "integrity_verified"):
            evaluate("artifact://synthetic/one", 1, True, evaluated_at=EVALUATED_AT)
        for requirement in ("", 0):
            with self.subTest(requirement=requirement), self.assertRaisesRegex(ValueError, "unsupported"):
                evaluate(
                    "artifact://synthetic/one",
                    True,
                    True,
                    requirement=requirement,
                    evaluated_at=EVALUATED_AT,
                )
        for field in ("issuer_ref", "audience_ref"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                evaluate(
                    "artifact://synthetic/one",
                    True,
                    True,
                    evaluated_at=EVALUATED_AT,
                    **{field: "  "},
                )
        with self.assertRaisesRegex(ValueError, "conflicts"):
            evaluate(
                "artifact://synthetic/one",
                True,
                True,
                authenticity_required=True,
                requirement="integrity-only",
                evaluated_at=EVALUATED_AT,
            )
        with self.assertRaises(ValidationFailure):
            evaluate("artifact://synthetic/one", True, True, evaluated_at="not-a-time")

    def test_v1_schema_remains_available_without_reinterpretation(self):
        schema = load_schema("core", "authenticity-receipt.v1.schema.json")
        self.assertEqual(
            schema["properties"]["schema_id"]["const"],
            "artifact-memory/authenticity-receipt/v1",
        )


if __name__ == "__main__":
    unittest.main()
