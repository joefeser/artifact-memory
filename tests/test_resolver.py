import tempfile
import unittest
from pathlib import Path

from artifact_memory.resolver import resolve


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


if __name__ == "__main__":
    unittest.main()
