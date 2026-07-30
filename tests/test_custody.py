import json
import unittest
from pathlib import Path

from artifact_memory.custody import record_custody
from artifact_memory.validator import validate


class CustodyTests(unittest.TestCase):
    def test_unapproved_off_machine_custody_is_explicit(self):
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root / "schemas/core/custody-receipt.v1.schema.json").read_text(encoding="utf-8"))
        receipt = record_custody("backup://private/dogfood-0001", "endpoint://private/off-machine", "off-machine", False)
        validate(receipt, schema)
        self.assertEqual(receipt["outcome"], "not-authorized")
        self.assertEqual(receipt["transfer"], "not-performed-by-receipt")


if __name__ == "__main__":
    unittest.main()
