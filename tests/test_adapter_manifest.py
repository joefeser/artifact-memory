import json
import unittest
from copy import deepcopy
from pathlib import Path

from artifact_memory.adapter_manifest import validate_manifest
from artifact_memory.canonical import receipt_with_digest
from artifact_memory.validator import validate


ROOT = Path(__file__).resolve().parents[1]


class AdapterManifestTests(unittest.TestCase):
    def test_reference_manifests_validate_and_receipt(self):
        schema = json.loads((ROOT / "artifact_memory/schemas/adapters/adapter-manifest.v1.schema.json").read_text(encoding="utf-8"))
        receipt_schema = json.loads((ROOT / "artifact_memory/schemas/adapters/adapter-receipt.v1.schema.json").read_text(encoding="utf-8"))
        for name in ("tracemap-read-manifest.json", "independent-reference-manifest.json", "wits-projection-manifest.json"):
            manifest = json.loads((ROOT / "fixtures/synthetic/adapters/v1" / name).read_text(encoding="utf-8"))
            validate(manifest, schema)
            receipt = validate_manifest(manifest)
            validate(receipt, receipt_schema)
            self.assertEqual(receipt["outcome"], "succeeded")

    def test_execution_authority_in_manifest_is_rejected(self):
        manifest = json.loads((ROOT / "fixtures/synthetic/adapters/v1/independent-reference-manifest.json").read_text(encoding="utf-8"))
        manifest["record_contents_authorize_execution"] = True
        receipt = validate_manifest(manifest)
        self.assertEqual(receipt["outcome"], "failed")
        self.assertEqual(receipt["diagnostics"][0]["code"], "authority-boundary")
        self.assertEqual(receipt["diagnostics"][0]["path"], "$.record_contents_authorize_execution")

    def test_schema_invalid_manifests_emit_valid_failure_receipts(self):
        manifest = json.loads((ROOT / "fixtures/synthetic/adapters/v1/independent-reference-manifest.json").read_text(encoding="utf-8"))
        receipt_schema = json.loads((ROOT / "artifact_memory/schemas/adapters/adapter-receipt.v1.schema.json").read_text(encoding="utf-8"))
        mutations = (
            lambda value: value.update(schema_id="wrong"),
            lambda value: value.update(adapter_id="not-an-adapter"),
            lambda value: value.update(capabilities="all"),
            lambda value: value["capabilities"].update(network="root"),
            lambda value: value.update(determinism="sometimes"),
            lambda value: value.update(surprise=True),
        )
        for mutation in mutations:
            malformed = deepcopy(manifest)
            mutation(malformed)
            result = validate_manifest(malformed)
            validate(result, receipt_schema)
            self.assertEqual(result["outcome"], "failed")
            self.assertEqual(result["diagnostics"][0]["code"], "manifest-invalid")
            self.assertNotIn("root", json.dumps(result))

    def test_non_object_manifest_uses_safe_fallback_identity(self):
        receipt = validate_manifest([])
        self.assertEqual(receipt["outcome"], "failed")
        self.assertEqual(receipt["adapter_ref"], "adapter://unknown/unknown")

    def test_receipt_helper_rejects_reserved_identity_fields(self):
        for field in ("schema_id", "receipt_id"):
            with self.assertRaisesRegex(ValueError, "reserved identity field"):
                receipt_with_digest("artifact-memory/example/v1", "example://", {field: "spoofed"})


if __name__ == "__main__":
    unittest.main()
