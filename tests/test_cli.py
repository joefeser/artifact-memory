import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "synthetic" / "contracts"


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "artifact_memory", *args], cwd=ROOT, text=True, capture_output=True)

    def test_version_json(self):
        result = self.run_cli("version", "--json")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["contract_version"], "v0")

    def test_valid_record(self):
        result = self.run_cli("validate", str(FIXTURES / "v0-valid-record.json"), "--json")
        self.assertEqual(result.returncode, 0)
        self.assertTrue(json.loads(result.stdout)["valid"])

    def test_absolute_path_rejected(self):
        result = self.run_cli("validate", str(FIXTURES / "v0-invalid-absolute-path.json"), "--json")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(json.loads(result.stdout)["valid"])

    def test_inspect_does_not_echo_path(self):
        result = self.run_cli("inspect", str(FIXTURES / "v0-valid-record.json"), "--json")
        self.assertEqual(result.returncode, 0)
        self.assertNotIn(str(ROOT), result.stdout)


if __name__ == "__main__":
    unittest.main()
