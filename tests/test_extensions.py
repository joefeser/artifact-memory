import json
import unittest
from pathlib import Path

from artifact_memory.extensions import ExtensionFailure, extension_digest, preserve_extensions
from artifact_memory.validator import validate


ROOT = Path(__file__).resolve().parents[1]


class ExtensionTests(unittest.TestCase):
    def test_unknown_optional_extension_round_trips_opaque(self):
        record = json.loads((ROOT / "fixtures/synthetic/contracts/v0-valid-record.json").read_text(encoding="utf-8"))
        bundle = json.loads((ROOT / "fixtures/synthetic/extensions/v1/optional-extension.json").read_text(encoding="utf-8"))
        result = preserve_extensions(record, bundle)
        self.assertEqual(result["extensions"]["https://synthetic.example/extensions/catalog"], bundle["extensions"]["https://synthetic.example/extensions/catalog"])
        self.assertTrue(extension_digest(bundle).startswith("sha-256:"))

    def test_unknown_required_extension_fails_closed(self):
        record = json.loads((ROOT / "fixtures/synthetic/contracts/v0-valid-record.json").read_text(encoding="utf-8"))
        bundle = json.loads((ROOT / "fixtures/synthetic/extensions/v1/required-extension.json").read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ExtensionFailure, "unsupported"):
            preserve_extensions(record, bundle)


if __name__ == "__main__":
    unittest.main()
