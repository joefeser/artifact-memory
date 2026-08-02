import json
import tempfile
import unittest
from pathlib import Path

from artifact_memory.extension_conformance import render_extension_conformance_receipt, run_extension_conformance
from artifact_memory.validator import ValidationFailure


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "extensions" / "v1"


class ExtensionConformanceTests(unittest.TestCase):
    def test_checked_machine_and_human_receipts_replay(self):
        receipt = run_extension_conformance(FIXTURE)
        expected = json.loads((FIXTURE / "expected-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt, expected)
        self.assertEqual(render_extension_conformance_receipt(receipt), (FIXTURE / "receipt.md").read_text(encoding="utf-8"))

    def test_fixture_roles_fail_closed_when_swapped(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            optional = json.loads((FIXTURE / "optional-extension.json").read_text(encoding="utf-8"))
            required = json.loads((FIXTURE / "required-extension.json").read_text(encoding="utf-8"))
            (fixture / "optional-extension.json").write_text(json.dumps(required), encoding="utf-8")
            (fixture / "required-extension.json").write_text(json.dumps(optional), encoding="utf-8")
            with self.assertRaises(ValidationFailure) as raised:
                run_extension_conformance(fixture)
        self.assertEqual(raised.exception.code, "invalid-vector")


if __name__ == "__main__":
    unittest.main()
