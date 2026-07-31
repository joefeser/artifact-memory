import json
import tempfile
import unittest
from pathlib import Path

from artifact_memory.resolver import resolve
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
