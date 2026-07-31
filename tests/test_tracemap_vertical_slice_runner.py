import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_tracemap_vertical_slice import _select_status_facts


class TraceMapVerticalSliceRunnerTests(unittest.TestCase):
    def test_missing_optional_fact_fields_do_not_escape_as_key_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            packet = Path(temporary)
            (packet / "facts.ndjson").write_text(
                json.dumps({"factId": "unrelated", "factType": "TypeDeclared"}) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "exactly one expected"):
                _select_status_facts(packet)


if __name__ == "__main__":
    unittest.main()
