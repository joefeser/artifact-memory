import json
import unittest
from pathlib import Path

from artifact_memory.adapter_manifest import validate_manifest
from artifact_memory.canonical import receipt_with_digest
from artifact_memory.validator import validate


ROOT = Path(__file__).resolve().parents[1]


class AdapterManifestTests(unittest.TestCase):
    def test_reference_manifests_validate_and_receipt(self):
        schema = json.loads((ROOT / "artifact_memory/schemas/adapters/adapter-manifest.v1.schema.json").read_text(encoding="utf-8"))
        receipt_schema = json.loads((ROOT / "artifact_memory/schemas/adapters/adapter-receipt.v1.schema.json").read_text(encoding="utf-8"))
        for name in ("tracemap-read-manifest.json", "independent-reference-manifest.json"):
            manifest = json.loads((ROOT / "fixtures/synthetic/adapters/v1" / name).read_text(encoding="utf-8"))
            validate(manifest, schema)
            receipt = validate_manifest(manifest)
            validate(receipt, receipt_schema)
            self.assertEqual(receipt["outcome"], "succeeded")

    def test_execution_authority_in_manifest_is_rejected(self):
        manifest = {"adapter_id": "adapter://synthetic/bad", "record_contents_authorize_execution": True}
        self.assertEqual(validate_manifest(manifest)["outcome"], "failed")

    def test_receipt_helper_rejects_reserved_identity_fields(self):
        for field in ("schema_id", "receipt_id"):
            with self.assertRaisesRegex(ValueError, "reserved identity field"):
                receipt_with_digest("artifact-memory/example/v1", "example://", {field: "spoofed"})


if __name__ == "__main__":
    unittest.main()
