import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from artifact_memory.cli import main
from artifact_memory.coordination_context import (
    CONTEXT_PACK_SCHEMA_ID,
    validate_coordination_context_pack,
)
from artifact_memory.coordination_scope_conformance import (
    CONFORMANCE_SCHEMA_ID,
    exercise,
    render_coordination_access_scope_conformance_receipt,
    run,
)
from artifact_memory.schema_resources import core_schemas
from artifact_memory.validator import ValidationFailure, load_json, validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "coordination-access-scope" / "v0"


class CoordinationAccessScopeConformanceTests(unittest.TestCase):
    def test_checked_receipt_proves_scoped_sync_context_and_narrowing(self):
        pack, receipt = exercise(ROOT / "fixtures")
        self.assertEqual(receipt, load_json(FIXTURE / "expected-receipt.json"))
        validate_coordination_context_pack(pack)
        self.assertIn(CONTEXT_PACK_SCHEMA_ID, core_schemas())
        self.assertIn(CONFORMANCE_SCHEMA_ID, core_schemas())
        validate(receipt, core_schemas()[CONFORMANCE_SCHEMA_ID])
        rendered = render_coordination_access_scope_conformance_receipt(receipt)
        self.assertEqual(
            rendered,
            (FIXTURE / "receipt.md").read_text(encoding="utf-8"),
        )
        self.assertFalse(receipt["restricted_sync"]["denied_identity_present"])
        self.assertFalse(receipt["context_pack"]["denied_identity_present"])

    def test_context_pack_validation_binds_records_membership_and_identity(self):
        pack, _ = exercise(ROOT / "fixtures")
        changed = deepcopy(pack)
        changed["records"][0]["title"] = "Changed after export"
        with self.assertRaises(ValidationFailure) as raised:
            validate_coordination_context_pack(changed)
        self.assertEqual(
            raised.exception.code,
            "coordination-context-membership-mismatch",
        )

        changed = deepcopy(pack)
        changed["sync_observation"]["excluded_count"] += 1
        with self.assertRaises(ValidationFailure) as raised:
            validate_coordination_context_pack(changed)
        self.assertEqual(
            raised.exception.code,
            "coordination-context-pack-id-mismatch",
        )

    def test_generic_cli_validation_runs_context_pack_semantics(self):
        pack, _ = exercise(ROOT / "fixtures")
        pack["records"][0]["title"] = "Changed after export"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "context-pack.json"
            path.write_text(json.dumps(pack), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(["validate", str(path), "--json"])
        self.assertEqual(exit_code, 2)
        result = json.loads(stdout.getvalue())
        self.assertEqual(
            result["diagnostics"][0]["code"],
            "coordination-context-membership-mismatch",
        )

    def test_cli_denies_without_a_verified_policy_projection(self):
        with tempfile.TemporaryDirectory() as temporary:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(
                    [
                        "coordination-context",
                        "--vault",
                        str(Path(temporary) / "vault"),
                        "--json",
                    ]
                )
        self.assertEqual(exit_code, 2)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["diagnostics"][0]["code"], "sync-marker-missing")

    def test_check_rejects_receipt_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "fixture"
            shutil.copytree(FIXTURE, fixture)
            receipt = load_json(fixture / "expected-receipt.json")
            receipt["restricted_sync"]["denied_identity_present"] = True
            (fixture / "expected-receipt.json").write_text(
                json.dumps(receipt, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_coordination_access_scope_conformance.py",
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
            "coordination access-scope conformance receipt does not match checked evidence",
            completed.stderr,
        )

    def test_script_check_passes(self):
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/run_coordination_access_scope_conformance.py",
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


if __name__ == "__main__":
    unittest.main()
