import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from artifact_memory.coordination_sync_conformance import (
    CONFORMANCE_SCHEMA_ID,
    render_coordination_sync_conformance_receipt,
    run,
)
from artifact_memory.schema_resources import core_schemas
from artifact_memory.validator import load_json, validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "coordination-sync" / "v0"


class CoordinationSyncConformanceTests(unittest.TestCase):
    def test_checked_receipt_is_registered_valid_and_rendered(self):
        expected = load_json(FIXTURE / "expected-receipt.json")
        receipt = run(ROOT / "fixtures", FIXTURE)
        self.assertEqual(receipt, expected)
        self.assertIn(CONFORMANCE_SCHEMA_ID, core_schemas())
        validate(receipt, core_schemas()[CONFORMANCE_SCHEMA_ID])
        self.assertEqual(
            render_coordination_sync_conformance_receipt(receipt),
            (FIXTURE / "receipt.md").read_text(encoding="utf-8"),
        )

    def test_check_rejects_machine_receipt_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "fixture"
            shutil.copytree(FIXTURE, fixture)
            expected_path = fixture / "expected-receipt.json"
            expected = json.loads(expected_path.read_text(encoding="utf-8"))
            expected["pair_set_vector_count"] += 1
            expected_path.write_text(
                json.dumps(expected, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_coordination_sync_conformance.py",
                    "--fixture",
                    str(fixture),
                    "--check",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertIn(
                "coordination sync conformance receipt does not match checked evidence",
                completed.stderr,
            )


if __name__ == "__main__":
    unittest.main()
