import json
import tempfile
import unittest
from pathlib import Path

from artifact_memory.resolver import resolve
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import ValidationFailure
from artifact_memory.validator import validate


class ResolverTests(unittest.TestCase):
    def test_two_machine_layouts_resolve_same_logical_reference(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            configs = [{"endpoint_ref": "endpoint://synthetic/vault", "platform": "macos", "root": first, "authorized": True}, {"endpoint_ref": "endpoint://synthetic/vault", "platform": "windows", "root": second, "authorized": True}]
            result = resolve([configs[0]], "endpoint://synthetic/vault", "records/one.json")
            self.assertEqual(result["outcome"], "resolved")
            ambiguous = resolve(configs, "endpoint://synthetic/vault", "records/one.json")
            self.assertEqual(ambiguous["outcome"], "ambiguous")

    def test_unavailable_and_unauthorized_are_explicit(self):
        self.assertEqual(resolve([], "endpoint://synthetic/missing", "one.txt")["outcome"], "unavailable-endpoint")
        self.assertEqual(resolve([{"endpoint_ref": "endpoint://synthetic/vault", "root": "/tmp/synthetic", "authorized": False}], "endpoint://synthetic/vault", "one.txt")["outcome"], "not-authorized")

    def test_noncanonical_and_uri_like_relative_paths_are_unsupported(self):
        config = [{"endpoint_ref": "endpoint://synthetic/vault", "root": "/tmp/synthetic", "authorized": True}]
        for relative_path in (
            "./objects/x",
            "objects//x",
            "objects/./x",
            "objects\\x",
            "objects/x?token=synthetic",
            "objects/x#fragment",
            "https://example.test/x?token=synthetic",
        ):
            with self.subTest(relative_path=relative_path):
                receipt = resolve(config, "endpoint://synthetic/vault", relative_path)
                self.assertEqual(receipt["outcome"], "unsupported")
                self.assertEqual(receipt["relative_path"], "unsupported")
                self.assertNotIn(relative_path, str(receipt))
                validate(receipt, load_schema("core", "resolution-receipt.v1.schema.json"))
                forged = resolve(config, "endpoint://synthetic/vault", "objects/x")
                forged["relative_path"] = relative_path
                with self.assertRaises(ValidationFailure):
                    validate(forged, load_schema("core", "resolution-receipt.v1.schema.json"))

    def test_single_segment_endpoint_identity_is_valid_resolver_config(self):
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root / "artifact_memory/schemas/core/resolver-config.v1.schema.json").read_text(encoding="utf-8"))
        validate(
            {
                "schema_id": "artifact-memory/resolver-config/v1",
                "endpoint_ref": "endpoint://joe-home-proxmox-vault-1",
                "platform": "linux",
                "root": "/synthetic/vault",
                "authorized": True,
            },
            schema,
        )


if __name__ == "__main__":
    unittest.main()
