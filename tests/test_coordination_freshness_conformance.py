import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from artifact_memory.coordination_freshness_conformance import (
    CONFORMANCE_SCHEMA_ID,
    exercise,
    render_coordination_freshness_conformance_receipt,
    run,
)
from artifact_memory.coordination_kickoff import validate_kickoff_pack
from artifact_memory.schema_resources import core_schemas
from artifact_memory.validator import load_json, validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "coordination-freshness" / "v0"


class CoordinationFreshnessConformanceTests(unittest.TestCase):
    def test_checked_receipt_matches_repo_ancestry_evidence(self):
        stale_pack, current_pack, receipt = exercise(ROOT / "fixtures")
        self.assertEqual(receipt, load_json(FIXTURE / "expected-receipt.json"))
        validate_kickoff_pack(stale_pack)
        validate_kickoff_pack(current_pack)
        self.assertIn(CONFORMANCE_SCHEMA_ID, core_schemas())
        validate(receipt, core_schemas()[CONFORMANCE_SCHEMA_ID])
        rendered = render_coordination_freshness_conformance_receipt(receipt)
        self.assertEqual(
            rendered,
            (FIXTURE / "receipt.md").read_text(encoding="utf-8"),
        )
        self.assertIn("Divergent commit status: `stale-verify`", rendered)

    def test_check_rejects_receipt_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "fixture"
            shutil.copytree(FIXTURE, fixture)
            receipt = load_json(fixture / "expected-receipt.json")
            receipt["unknown_optional_preserved"] = False
            (fixture / "expected-receipt.json").write_text(
                json.dumps(receipt, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_coordination_freshness_conformance.py",
                    "--fixture",
                    str(fixture),
                    "--check",
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "coordination freshness conformance receipt does not match checked evidence",
            completed.stderr,
        )

    def test_script_check_passes(self):
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/run_coordination_freshness_conformance.py",
                "--check",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            run(ROOT / "fixtures", FIXTURE),
            load_json(FIXTURE / "expected-receipt.json"),
        )

    def test_script_check_ignores_ambient_default_hash_format(self):
        environment = os.environ.copy()
        environment["GIT_DEFAULT_HASH"] = "sha256"
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/run_coordination_freshness_conformance.py",
                "--check",
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
