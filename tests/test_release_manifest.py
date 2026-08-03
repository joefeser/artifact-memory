import copy
import json
import unittest
from pathlib import Path

from artifact_memory.release import validate_release_manifest
from artifact_memory.release_conformance import render_release_conformance, run_release_conformance
from artifact_memory.validator import ValidationFailure, validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/synthetic/release"


class ReleaseManifestTests(unittest.TestCase):
    def test_legacy_preview_manifest_remains_schema_valid(self):
        schema = json.loads((ROOT / "artifact_memory/schemas/core/release-manifest.v1.schema.json").read_text(encoding="utf-8"))
        manifest = json.loads((FIXTURE / "v0-preview-manifest.json").read_text(encoding="utf-8"))
        validate(manifest, schema)
        self.assertEqual(manifest["status"], "preview")
        self.assertEqual(manifest["signature"]["state"], "not-signed")

    def test_v2_preview_reproduces_public_safe_release_materials(self):
        manifest = json.loads((FIXTURE / "v0-preview-manifest.v2.json").read_text(encoding="utf-8"))
        validate_release_manifest(manifest)
        receipt = run_release_conformance(FIXTURE)
        expected = json.loads((FIXTURE / "v0-preview-expected-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt, expected)
        self.assertEqual(render_release_conformance(receipt), (FIXTURE / "v0-preview-receipt.md").read_text(encoding="utf-8"))
        self.assertEqual(receipt["signature_state"], "unsigned-preview")
        self.assertEqual(receipt["publication_state"], "not-authorized")

    def test_unsigned_manifest_cannot_claim_release_status(self):
        manifest = json.loads((FIXTURE / "v0-preview-manifest.v2.json").read_text(encoding="utf-8"))
        manifest["status"] = "release"
        manifest["release_id"] = "artifact-memory/v0.1.0"
        with self.assertRaises(ValidationFailure):
            validate_release_manifest(manifest)

    def test_duplicate_artifact_names_fail_closed(self):
        manifest = json.loads((FIXTURE / "v0-preview-manifest.v2.json").read_text(encoding="utf-8"))
        manifest["artifacts"][1]["name"] = manifest["artifacts"][0]["name"]
        with self.assertRaises(ValidationFailure) as failure:
            validate_release_manifest(manifest)
        self.assertEqual(failure.exception.code, "release-artifact-duplicate")

    def test_released_tag_must_match_release_identifier(self):
        manifest = json.loads((FIXTURE / "v0-preview-manifest.v2.json").read_text(encoding="utf-8"))
        released = copy.deepcopy(manifest)
        released["status"] = "release"
        released["release_id"] = "artifact-memory/v0.1.0"
        released["signature"] = {
            "state": "owner-signed",
            "tag": "v0.1.1",
            "algorithm": "ssh-ed25519",
            "public_key_fingerprint": "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "key_generation": "generation-1",
            "owner_signed_annotated_tag": True,
        }
        with self.assertRaises(ValidationFailure) as failure:
            validate_release_manifest(released)
        self.assertEqual(failure.exception.code, "release-tag-mismatch")


if __name__ == "__main__":
    unittest.main()
