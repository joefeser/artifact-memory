import json
import unittest
from pathlib import Path

from artifact_memory.extensions import ExtensionFailure, extension_digest, preserve_extensions, validate_extension_bundle
from artifact_memory.validator import ValidationFailure, validate


ROOT = Path(__file__).resolve().parents[1]


class ExtensionTests(unittest.TestCase):
    def test_unknown_optional_extension_round_trips_opaque(self):
        record = json.loads((ROOT / "fixtures/synthetic/contracts/v0-valid-record.json").read_text(encoding="utf-8"))
        bundle = json.loads((ROOT / "fixtures/synthetic/extensions/v1/optional-extension.json").read_text(encoding="utf-8"))
        result = preserve_extensions(record, bundle)
        self.assertEqual(result["extensions"]["https://synthetic.example/extensions/catalog"], bundle["extensions"]["https://synthetic.example/extensions/catalog"])
        self.assertTrue(extension_digest(bundle).startswith("sha-256:"))

    def test_extension_values_cannot_redefine_core_fields(self):
        record = {"schema_id": "artifact-memory/knowledge-record/v2", "record_id": "record://synthetic/extensions", "sensitivity": "public"}
        bundle = {
            "schema_id": "artifact-memory/extension-bundle/v1",
            "extensions": {
                "https://synthetic.example/extensions/spoof": {
                    "version": "v1",
                    "required": False,
                    "value": {"schema_id": "spoofed", "record_id": "record://spoofed/value", "sensitivity": "restricted", "authority": "execute"},
                }
            },
        }
        result = preserve_extensions(record, bundle)
        self.assertEqual({key: result[key] for key in record}, record)
        self.assertEqual(result["extensions"], bundle["extensions"])

    def test_unknown_required_extension_fails_closed(self):
        record = json.loads((ROOT / "fixtures/synthetic/contracts/v0-valid-record.json").read_text(encoding="utf-8"))
        bundle = json.loads((ROOT / "fixtures/synthetic/extensions/v1/required-extension.json").read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ExtensionFailure, "unsupported"):
            preserve_extensions(record, bundle)

    def test_extension_entries_are_validated_by_additional_properties_schema(self):
        schema = json.loads((ROOT / "artifact_memory/schemas/core/extension-bundle.v1.schema.json").read_text(encoding="utf-8"))
        for invalid_entry in ("scalar", {"version": "v1", "required": False}):
            bundle = {
                "schema_id": "artifact-memory/extension-bundle/v1",
                "extensions": {"https://synthetic.example/extensions/invalid": invalid_entry},
            }
            with self.assertRaises(ValidationFailure):
                validate(bundle, schema)
            with self.assertRaises(ExtensionFailure) as raised:
                validate_extension_bundle(bundle)
            self.assertTrue(raised.exception.path.startswith("$.extensions."))

    def test_supported_required_configuration_is_validated(self):
        bundle = json.loads((ROOT / "fixtures/synthetic/extensions/v1/required-extension.json").read_text(encoding="utf-8"))
        malformed_values = (
            {"https://synthetic.example/extensions/required"},
            [("https://synthetic.example/extensions/required", 1)],
            [("not-namespaced", "v1")],
        )
        for malformed in malformed_values:
            with self.assertRaises(ExtensionFailure) as raised:
                preserve_extensions({}, bundle, supported_required=malformed)
            self.assertEqual(raised.exception.code, "invalid-supported-required")
            self.assertTrue(raised.exception.path.startswith("$.supported_required"))

    def test_declared_digest_and_existing_extension_conflicts_fail_closed(self):
        bundle = json.loads((ROOT / "fixtures/synthetic/extensions/v1/optional-extension.json").read_text(encoding="utf-8"))
        invalid_digest = {**bundle, "extensions_digest": "sha-256:" + "0" * 64}
        with self.assertRaisesRegex(ExtensionFailure, "digest"):
            preserve_extensions({}, invalid_digest)
        with self.assertRaisesRegex(ExtensionFailure, "conflicts"):
            preserve_extensions({"extensions": {next(iter(bundle["extensions"])): {"different": True}}}, bundle)

    def test_conflict_comparison_preserves_json_type_fidelity(self):
        identifier = "https://synthetic.example/extensions/type-fidelity"
        existing = {"version": "v1", "required": False, "value": {"flag": True}}
        incoming = {"version": "v1", "required": False, "value": {"flag": 1}}
        bundle = {"schema_id": "artifact-memory/extension-bundle/v1", "extensions": {identifier: incoming}}
        with self.assertRaisesRegex(ExtensionFailure, "conflicts"):
            preserve_extensions({"extensions": {identifier: existing}}, bundle)


if __name__ == "__main__":
    unittest.main()
