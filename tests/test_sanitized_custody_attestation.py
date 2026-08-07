import copy
import unittest
from pathlib import Path

from artifact_memory.sanitized_custody_attestation import (
    render_sanitized_custody_attestation,
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
        attestation["schema_id"] = "artifact-memory/sanitized-custody-attestation/v2"
        with self.assertRaises(ValidationFailure):
            validate_sanitized_custody_attestation(attestation)

    def test_private_material_cannot_be_claimed_as_committed(self):
        attestation = copy.deepcopy(load_json(ATTESTATION))
        attestation["private_material_committed"] = True
        with self.assertRaises(ValidationFailure):
            validate_sanitized_custody_attestation(attestation)


if __name__ == "__main__":
    unittest.main()
