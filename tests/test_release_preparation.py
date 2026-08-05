import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from artifact_memory.release import validate_release_manifest
from artifact_memory.release_preparation import (
    prepare_unsigned_release_preview,
    render_release_preparation_receipt,
)
from artifact_memory.validator import ValidationFailure


ROOT = Path(__file__).resolve().parents[1]


class ReleasePreparationTests(unittest.TestCase):
    def test_checked_fixture_pins_prepared_receipt_and_human_rendering(self):
        fixture = ROOT / "fixtures/synthetic/release"
        commit = "45f60d38acaa1026f8428e753efd1c773df88bd3"
        with tempfile.TemporaryDirectory() as temporary:
            receipt = prepare_unsigned_release_preview(ROOT, commit, Path(temporary) / "preview")
        expected = json.loads((fixture / "v0-preparation-expected-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt, expected)
        self.assertEqual(
            render_release_preparation_receipt(receipt),
            (fixture / "v0-preparation-receipt.md").read_text(encoding="utf-8"),
        )

    def test_exact_commit_prepares_external_unsigned_assets(self):
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "preview"
            receipt = prepare_unsigned_release_preview(ROOT, commit, output)
            manifest = json.loads((output / "release-manifest.json").read_text(encoding="utf-8"))
            validate_release_manifest(manifest)
            self.assertEqual(receipt["source_commit"], commit)
            self.assertEqual(receipt["signature_state"], "unsigned-preview")
            self.assertEqual(receipt["publication_state"], "not-authorized")
            self.assertEqual(manifest["source"]["commit"], commit)
            self.assertEqual(manifest["signature"]["public_key_fingerprint"], None)
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
            with self.assertRaises(ValidationFailure) as symbolic:
                prepare_unsigned_release_preview(ROOT, "HEAD", Path(temporary) / "symbolic")
            self.assertEqual(symbolic.exception.code, "release-preparation-candidate-not-exact")
        with self.assertRaises(ValidationFailure) as inside:
            prepare_unsigned_release_preview(ROOT, commit, ROOT / "build" / "release-preview")
        self.assertEqual(inside.exception.code, "release-preparation-output-inside-repository")


if __name__ == "__main__":
    unittest.main()
