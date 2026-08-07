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

    def synthetic_repository(self, root: Path, schemas: dict[str, bytes]) -> tuple[Path, str]:
        repository = root / "repository"
        repository.mkdir(parents=True)
        subprocess.run(["git", "init", "--quiet"], cwd=repository, check=True)
        subprocess.run(["git", "config", "user.name", "Synthetic Fixture"], cwd=repository, check=True)
        subprocess.run(["git", "config", "user.email", "synthetic@example.invalid"], cwd=repository, check=True)
        (repository / "pyproject.toml").write_text(
            '[project]\nname = "artifact-memory"\nversion = "0.1.0.dev0"\n',
            encoding="utf-8",
        )
        schema_root = repository / "artifact_memory/schemas/adapters"
        for name, content in schemas.items():
            schema_root.mkdir(parents=True, exist_ok=True)
            (schema_root / name).write_bytes(content)
        subprocess.run(["git", "add", "."], cwd=repository, check=True)
        subprocess.run(["git", "commit", "--quiet", "-m", "Synthetic release tree"], cwd=repository, check=True)
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()
        return repository, commit

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

    def test_adapter_schema_discovery_uses_the_exact_candidate_tree(self):
        v1_schema = (ROOT / "artifact_memory/schemas/adapters/adapter-manifest.v1.schema.json").read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository, commit = self.synthetic_repository(root / "v1-only", {"adapter-manifest.v1.schema.json": v1_schema})
            output = root / "v1-preview"
            prepare_unsigned_release_preview(repository, commit, output)
            manifest = json.loads((output / "release-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["surfaces"]["adapters"]["supported_manifest_schemas"],
                ["artifact-memory/adapter-manifest/v1"],
            )

            empty_repository, empty_commit = self.synthetic_repository(root / "no-adapters", {})
            failed_output = root / "missing-preview"
            with self.assertRaises(ValidationFailure) as missing:
                prepare_unsigned_release_preview(empty_repository, empty_commit, failed_output)
            self.assertEqual(missing.exception.code, "release-preparation-adapter-contract-missing")
            self.assertFalse(failed_output.exists())

    def test_v2_only_candidate_cannot_publish_previews(self):
        v2_schema = (ROOT / "artifact_memory/schemas/adapters/adapter-manifest.v2.schema.json").read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository, commit = self.synthetic_repository(
                root / "v2-only", {"adapter-manifest.v2.schema.json": v2_schema}
            )
            output = root / "v2-preview"
            with self.assertRaises(ValidationFailure) as unsupported:
                prepare_unsigned_release_preview(repository, commit, output)
            self.assertEqual(
                unsupported.exception.code,
                "release-preparation-adapter-primary-schema-unsupported",
            )
            self.assertFalse(output.exists())

    def test_invalid_candidate_adapter_schema_is_not_advertised(self):
        schema = json.loads(
            (ROOT / "artifact_memory/schemas/adapters/adapter-manifest.v1.schema.json").read_text(encoding="utf-8")
        )
        schema["$id"] = "https://artifact-memory.dev/schemas/adapters/adapter-manifest/not-v1"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository, commit = self.synthetic_repository(
                root / "invalid-adapter",
                {"adapter-manifest.v1.schema.json": (json.dumps(schema, sort_keys=True) + "\n").encode("utf-8")},
            )
            output = root / "invalid-preview"
            with self.assertRaises(ValidationFailure) as invalid:
                prepare_unsigned_release_preview(repository, commit, output)
            self.assertEqual(invalid.exception.code, "release-preparation-adapter-contract-invalid")
            self.assertFalse(output.exists())

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
