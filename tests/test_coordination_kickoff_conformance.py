import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from artifact_memory.coordination_kickoff import validate_kickoff_pack
from artifact_memory.coordination_kickoff_conformance import (
    CONFORMANCE_SCHEMA_ID,
    exercise,
    render_coordination_kickoff_conformance_receipt,
    run,
)
from artifact_memory.schema_resources import core_schemas
from artifact_memory.validator import load_json, validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "coordination-kickoff" / "v0"


class CoordinationKickoffConformanceTests(unittest.TestCase):
    def test_checked_golden_pack_prompt_and_receipt_match_evidence(self):
        pack, prompt, receipt = exercise(ROOT / "fixtures")
        self.assertEqual(pack, load_json(FIXTURE / "expected-pack.json"))
        self.assertEqual(
            prompt,
            (FIXTURE / "expected-prompt.md").read_text(encoding="utf-8"),
        )
        self.assertEqual(receipt, load_json(FIXTURE / "expected-receipt.json"))
        validate_kickoff_pack(pack)
        self.assertIn(CONFORMANCE_SCHEMA_ID, core_schemas())
        validate(receipt, core_schemas()[CONFORMANCE_SCHEMA_ID])
        self.assertEqual(
            render_coordination_kickoff_conformance_receipt(receipt),
            (FIXTURE / "receipt.md").read_text(encoding="utf-8"),
        )

    def test_check_rejects_machine_receipt_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "fixture"
            shutil.copytree(FIXTURE, fixture)
            expected_path = fixture / "expected-receipt.json"
            expected = json.loads(expected_path.read_text(encoding="utf-8"))
            expected["open_task_count"] = 3
            expected_path.write_text(
                json.dumps(expected, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_coordination_kickoff_conformance.py",
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
            "coordination kickoff conformance receipt does not match checked evidence",
            completed.stderr,
        )

    def test_script_check_passes(self):
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/run_coordination_kickoff_conformance.py",
                "--check",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(run(ROOT / "fixtures", FIXTURE), load_json(FIXTURE / "expected-receipt.json"))


if __name__ == "__main__":
    unittest.main()
