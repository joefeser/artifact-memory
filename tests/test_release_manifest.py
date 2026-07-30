import json
import unittest
from pathlib import Path

from artifact_memory.validator import validate


class ReleaseManifestTests(unittest.TestCase):
    def test_preview_manifest_has_checksums_provenance_and_explicit_signature_state(self):
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root / "schemas/core/release-manifest.v1.schema.json").read_text(encoding="utf-8"))
        manifest = json.loads((root / "fixtures/synthetic/release/v0-preview-manifest.json").read_text(encoding="utf-8"))
        validate(manifest, schema)
        self.assertEqual(manifest["status"], "preview")
        self.assertEqual(manifest["signature"]["state"], "not-signed")
        self.assertTrue(manifest["artifacts"][0]["sha256"].startswith("sha-256:"))


if __name__ == "__main__":
    unittest.main()
