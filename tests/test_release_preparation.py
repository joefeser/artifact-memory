import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from artifact_memory.release import validate_release_manifest
from artifact_memory.release_preparation import prepare_unsigned_release_preview
from artifact_memory.release_metadata import read_package_version, schema_inventory
from artifact_memory.validator import ValidationFailure


ROOT = Path(__file__).resolve().parents[1]


class ReleasePreparationTests(unittest.TestCase):
    def run_cli(self, candidate: str, output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/prepare_release_preview.py"),
                "--candidate",
                candidate,
                "--repo",
                str(ROOT),
                "--out",
                str(output),
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_checked_fixture_pins_prepared_receipt_and_human_rendering(self):
        fixture = ROOT / "fixtures/synthetic/release"
        commit = "45f60d38acaa1026f8428e753efd1c773df88bd3"
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "preview"
            result = self.run_cli(commit, output)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            summary = json.loads(result.stdout)
            expected = json.loads((fixture / "v0-preparation-expected-receipt.json").read_text(encoding="utf-8"))
            persisted = json.loads((output / "release-preparation-receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["receipt_id"], expected["receipt_id"])
            self.assertEqual(persisted, expected)
            self.assertEqual(
                (output / "release-preparation-receipt.md").read_text(encoding="utf-8"),
                (fixture / "v0-preparation-receipt.md").read_text(encoding="utf-8"),
            )

    def test_exact_commit_prepares_external_unsigned_assets(self):
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "preview"
            output.mkdir()
            receipt = prepare_unsigned_release_preview(ROOT, commit, output)
            manifest = json.loads((output / "release-manifest.json").read_text(encoding="utf-8"))
            validate_release_manifest(manifest)
            self.assertEqual(receipt["source_commit"], commit)
            self.assertEqual(receipt["signature_state"], "unsigned-preview")
            self.assertEqual(receipt["publication_state"], "not-authorized")
            self.assertEqual(manifest["source"]["commit"], commit)
            self.assertEqual(
                manifest["surfaces"]["adapters"]["supported_manifest_schemas"],
                [
                    "artifact-memory/adapter-manifest/v1",
                    "artifact-memory/adapter-manifest/v2",
                ],
            )
            self.assertEqual(manifest["signature"]["public_key_fingerprint"], None)
            self.assertEqual(
                manifest["checksum_manifest"]["scope"],
                "all-manifest-listed-artifacts-except-checksum-manifest-itself",
            )
            self.assertEqual(
                set(path.name for path in output.iterdir()),
                {
                    "artifact-memory-0.1.0-preview.tar",
                    "SHA256SUMS",
                    "release-manifest.json",
                    "release-preparation-receipt.json",
                    "release-preparation-receipt.md",
                },
            )

    def test_symbolic_or_nonexact_candidates_and_in_repo_output_fail_closed(self):
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        with tempfile.TemporaryDirectory() as temporary:
            symbolic_output = Path(temporary) / "symbolic"
            symbolic = self.run_cli("HEAD", symbolic_output)
            self.assertEqual(symbolic.returncode, 2)
            self.assertEqual(symbolic.stdout, "")
            self.assertEqual(
                json.loads(symbolic.stderr)["diagnostics"][0]["code"],
                "release-preparation-candidate-not-exact",
            )
            self.assertFalse(symbolic_output.exists())
        inside_output = ROOT / "build" / "release-preview"
        inside = self.run_cli(commit, inside_output)
        self.assertEqual(inside.returncode, 2)
        self.assertEqual(inside.stdout, "")
        self.assertEqual(
            json.loads(inside.stderr)["diagnostics"][0]["code"],
            "release-preparation-output-inside-repository",
        )
        self.assertFalse(inside_output.exists())

    def test_output_is_not_published_after_staging_failure(self):
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "preview"
            with mock.patch(
                "artifact_memory.release_preparation._write_exclusive",
                side_effect=ValidationFailure("release-preparation-output-invalid", "synthetic failure"),
            ):
                with self.assertRaises(ValidationFailure):
                    prepare_unsigned_release_preview(ROOT, commit, output)
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_shared_release_metadata_rejects_invalid_values_structurally(self):
        with self.assertRaises(ValidationFailure) as version:
            read_package_version(b'[project]\nname = "artifact-memory"\nversion = "0.1.0.rc1"\n')
        self.assertEqual(version.exception.code, "release-pyproject-invalid")
        with self.assertRaises(ValidationFailure) as inventory:
            schema_inventory([b'{"$id":"\\ud800"}'])
        self.assertEqual(inventory.exception.code, "release-schema-inventory-invalid")


if __name__ == "__main__":
    unittest.main()
