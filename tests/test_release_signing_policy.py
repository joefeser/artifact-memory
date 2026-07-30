import json
import unittest
from pathlib import Path

from artifact_memory.validator import validate


class ReleaseSigningPolicyTests(unittest.TestCase):
    def test_template_keeps_private_key_and_fingerprint_owner_controlled(self):
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root / "schemas/core/release-signing-policy.v1.schema.json").read_text(encoding="utf-8"))
        policy = json.loads((root / "fixtures/synthetic/release/v0-signing-policy-template.json").read_text(encoding="utf-8"))
        validate(policy, schema)
        serialized = json.dumps(policy, sort_keys=True).lower()
        self.assertNotIn("private key material", serialized)
        self.assertEqual(policy["public_fingerprint_state"], "owner-to-fill")
        self.assertEqual(policy["attestation"], "keyless-attestation-deferred-until-public-workflow")


if __name__ == "__main__":
    unittest.main()
