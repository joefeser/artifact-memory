import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from artifact_memory.adapter_manifest import receipt, validate_manifest
from artifact_memory.canonical import receipt_with_digest
from artifact_memory.validator import ValidationFailure, validate


ROOT = Path(__file__).resolve().parents[1]


class AdapterManifestTests(unittest.TestCase):
    def test_failed_receipt_requires_diagnostics(self):
        with self.assertRaisesRegex(ValueError, "require diagnostics"):
            receipt({"adapter_id": "adapter://synthetic/test"}, "failed")

    def test_failed_receipt_rejects_incomplete_diagnostics(self):
        with self.assertRaisesRegex(ValueError, "does not satisfy"):
            receipt(
                {"adapter_id": "adapter://synthetic/test"},
                "failed",
                [{"code": "synthetic", "message": "missing detail and path"}],
            )

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

    def test_optional_extensions_are_accepted_and_required_extensions_fail_closed(self):
        optional = json.loads(
            (ROOT / "fixtures/synthetic/adapters/v1/optional-extension-manifest.json").read_text(encoding="utf-8")
        )
        required = json.loads(
            (ROOT / "fixtures/synthetic/adapters/v1/unsupported-required-extension-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(validate_manifest(optional)["outcome"], "succeeded")
        rejected = validate_manifest(required)
        self.assertEqual(rejected["outcome"], "failed")
        self.assertEqual(rejected["diagnostics"][0]["code"], "extension-invalid")
        self.assertEqual(rejected["diagnostics"][0]["detail_code"], "required-extension-unsupported")
        admitted = validate_manifest(
            required,
            (("https://example.invalid/extensions/required", "v1"),),
        )
        self.assertEqual(admitted["outcome"], "succeeded")

    def test_v1_opaque_extensions_remain_readable(self):
        manifest = json.loads((ROOT / "fixtures/synthetic/adapters/v1/tracemap-read-manifest.json").read_text(encoding="utf-8"))
        manifest["extensions"] = {"artifact-memory/compatibility/v1": ["synthetic"]}
        self.assertEqual(validate_manifest(manifest)["outcome"], "succeeded")

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

    def test_packaged_schema_failure_is_not_reported_as_invalid_input(self):
        manifest = json.loads((ROOT / "fixtures/synthetic/adapters/v1/independent-reference-manifest.json").read_text(encoding="utf-8"))
        with patch("artifact_memory.adapter_manifest.load_schema", side_effect=ValidationFailure("invalid-schema", "unavailable")):
            with self.assertRaisesRegex(ValidationFailure, "unavailable"):
                validate_manifest(manifest)

    def test_failed_receipt_requires_path_aware_diagnostics(self):
        schema = json.loads((ROOT / "artifact_memory/schemas/adapters/adapter-receipt.v1.schema.json").read_text(encoding="utf-8"))
        failed = validate_manifest([])
        del failed["diagnostics"][0]["detail_code"]
        with self.assertRaises(ValidationFailure):
            validate(failed, schema)

    def test_receipt_helper_rejects_reserved_identity_fields(self):
        for field in ("schema_id", "receipt_id"):
            with self.assertRaisesRegex(ValueError, "reserved identity field"):
                receipt_with_digest("artifact-memory/example/v1", "example://", {field: "spoofed"})


if __name__ == "__main__":
    unittest.main()
