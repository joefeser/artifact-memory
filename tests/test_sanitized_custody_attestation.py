import copy
import unittest
from pathlib import Path

from artifact_memory.sanitized_custody_attestation import (
    render_sanitized_custody_attestation,
    validate_historical_sanitized_custody_attestation,
    validate_historical_sanitized_custody_markdown,
    validate_sanitized_custody_attestation,
)
from artifact_memory.validator import ValidationFailure, load_json


ROOT = Path(__file__).resolve().parents[1]
ATTESTATION = ROOT / "evidence/sanitized/custody/v1/receipt.json"
MARKDOWN = ROOT / "evidence/sanitized/custody/v1/receipt.md"


class SanitizedCustodyAttestationTests(unittest.TestCase):
    def test_machine_receipt_validates_and_renders_checked_projection(self):
        attestation = load_json(ATTESTATION)
        validate_sanitized_custody_attestation(attestation)
        self.assertEqual(
            render_sanitized_custody_attestation(attestation),
            MARKDOWN.read_text(encoding="utf-8"),
        )

    def test_unknown_contract_version_fails_closed(self):
        attestation = copy.deepcopy(load_json(ATTESTATION))
        attestation["schema_id"] = "artifact-memory/sanitized-custody-attestation/v3"
        with self.assertRaises(ValidationFailure):
            validate_sanitized_custody_attestation(attestation)

    def test_checked_historical_v1_receipts_remain_supported(self):
        compatibility = ROOT / "evidence/sanitized/custody/v1/compatibility"
        for path in sorted(compatibility.glob("*.json")):
            with self.subTest(path=path.name):
                validate_historical_sanitized_custody_attestation(load_json(path))

    def test_historical_v1_receipts_are_semantically_pinned(self):
        compatibility = ROOT / "evidence/sanitized/custody/v1/compatibility"
        for path in sorted(compatibility.glob("*.json")):
            with self.subTest(path=path.name):
                attestation = copy.deepcopy(load_json(path))
                attestation["observed"] = "2026-08-07"
                with self.assertRaises(ValidationFailure) as failure:
                    validate_historical_sanitized_custody_attestation(attestation)
                if path.name == "provenance-v1.json":
                    self.assertEqual(
                        failure.exception.code,
                        "unsupported-contract-shape",
                    )

    def test_historical_markdown_requires_an_exact_supported_rendering(self):
        current = MARKDOWN.read_text(encoding="utf-8")
        validate_historical_sanitized_custody_markdown(
            current.replace("\n", "\r\n"),
            current,
        )
        with self.assertRaises(ValidationFailure) as failure:
            validate_historical_sanitized_custody_markdown(
                current + "\nUnexpected custody assertion.\n",
                current,
            )
        self.assertEqual(failure.exception.code, "unsupported-contract-shape")

    def test_historical_markdown_compatibility_is_independently_pinned(self):
        current = MARKDOWN.read_text(encoding="utf-8")
        compatibility = ROOT / "evidence/sanitized/custody/v1/compatibility"
        for path in sorted(compatibility.glob("*.md")):
            with self.subTest(path=path.name):
                rendering = path.read_text(encoding="utf-8")
                validate_historical_sanitized_custody_markdown(rendering, current)
                with self.assertRaises(ValidationFailure):
                    validate_historical_sanitized_custody_markdown(
                        rendering + "\n/srv/private-vault\n",
                        current,
                    )

    def test_non_object_historical_receipt_fails_typed(self):
        for value in (None, [], "receipt", 7):
            with self.subTest(value=value):
                with self.assertRaises(ValidationFailure):
                    validate_historical_sanitized_custody_attestation(value)

    def test_private_material_cannot_be_claimed_as_committed(self):
        attestation = copy.deepcopy(load_json(ATTESTATION))
        attestation["private_material_committed"] = True
        with self.assertRaises(ValidationFailure):
            validate_sanitized_custody_attestation(attestation)

    def test_invalid_calendar_dates_fail_closed(self):
        for observed in ("2026-99-99", "2024-02-30"):
            with self.subTest(observed=observed):
                attestation = copy.deepcopy(load_json(ATTESTATION))
                attestation["observed"] = observed
                with self.assertRaises(ValidationFailure):
                    validate_sanitized_custody_attestation(attestation)

    def test_machine_bound_endpoint_values_fail_closed(self):
        for endpoint in (
            "endpoint://192.168.1.10",
            "endpoint://vault.example",
            "endpoint://other-portable-slug",
        ):
            with self.subTest(endpoint=endpoint):
                attestation = copy.deepcopy(load_json(ATTESTATION))
                attestation["endpoint"] = endpoint
                with self.assertRaises(ValidationFailure):
                    validate_sanitized_custody_attestation(attestation)

    def test_claim_outcomes_and_provenance_are_pinned(self):
        mutations = {
            "remote_write": "failed",
            "repository_verification": "not attempted",
            "restore": "failed",
            "restored_verification": "not checked",
            "attestation_status": "verified",
            "private_evidence_binding": "publicly-bound",
            "independent_replay": True,
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                attestation = copy.deepcopy(load_json(ATTESTATION))
                attestation[field] = value
                with self.assertRaises(ValidationFailure):
                    validate_sanitized_custody_attestation(attestation)


if __name__ == "__main__":
    unittest.main()
