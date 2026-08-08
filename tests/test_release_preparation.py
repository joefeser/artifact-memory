import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from artifact_memory.canonical import receipt_with_digest, sha256_bytes
from artifact_memory.release import validate_release_manifest
from artifact_memory.release_preparation import (
    RELEASE_CANDIDATE_PREPARATION_RECEIPT_PREFIX,
    RELEASE_CANDIDATE_PREPARATION_SCHEMA_ID,
    prepare_release_candidate,
    prepare_unsigned_release_preview,
    render_release_candidate_preparation_receipt,
    validate_release_candidate_preparation_receipt,
)
from artifact_memory.release_metadata import read_package_version, schema_inventory
from artifact_memory.validator import ValidationFailure


ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_FINGERPRINT = "SHA256:" + "A" * 43


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

    def run_candidate_cli(
        self,
        repository: Path,
        candidate: str,
        output: Path,
        *,
        plain_text: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        command = [
                sys.executable,
                str(ROOT / "scripts/prepare_release_candidate.py"),
                "--candidate",
                candidate,
                "--repo",
                str(repository),
                "--out",
                str(output),
                "--owner-fingerprint",
                SYNTHETIC_FINGERPRINT,
                "--key-generation",
                "synthetic-generation-1",
            ]
        if plain_text:
            command.append("--plain-text")
        return subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def synthetic_repository(
        self,
        root: Path,
        schemas: dict[str, bytes],
        *,
        package_version: str = "0.1.0.dev0",
        extra_files: dict[str, bytes] | None = None,
    ) -> tuple[Path, str]:
        repository = root / "repository"
        repository.mkdir(parents=True)
        subprocess.run(["git", "init", "--quiet"], cwd=repository, check=True)
        subprocess.run(["git", "config", "user.name", "Synthetic Fixture"], cwd=repository, check=True)
        subprocess.run(["git", "config", "user.email", "synthetic@example.invalid"], cwd=repository, check=True)
        (repository / "pyproject.toml").write_text(
            f'[project]\nname = "artifact-memory"\nversion = "{package_version}"\n',
            encoding="utf-8",
        )
        schema_root = repository / "artifact_memory/schemas/adapters"
        for name, content in schemas.items():
            schema_root.mkdir(parents=True, exist_ok=True)
            (schema_root / name).write_bytes(content)
        for name, content in (extra_files or {}).items():
            path = repository / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        subprocess.run(["git", "add", "."], cwd=repository, check=True)
        subprocess.run(["git", "commit", "--quiet", "-m", "Synthetic release tree"], cwd=repository, check=True)
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()
        return repository, commit

    def release_repository(
        self,
        root: Path,
        *,
        package_version: str = "0.1.0",
        runtime_version: str | None = None,
        release_notes: bytes | None = b"# Synthetic 0.1.0 release notes\n",
    ) -> tuple[Path, str]:
        v1_schema = (
            ROOT / "artifact_memory/schemas/adapters/adapter-manifest.v1.schema.json"
        ).read_bytes()
        extra_files = {
            "artifact_memory/__init__.py": (
                f'__version__ = "{runtime_version or package_version}"\n'.encode("utf-8")
            )
        }
        if release_notes is not None:
            extra_files["docs/release/v0.1.0-release-notes.md"] = release_notes
        return self.synthetic_repository(
            root,
            {"adapter-manifest.v1.schema.json": v1_schema},
            package_version=package_version,
            extra_files=extra_files,
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

    def test_exact_commit_prepares_pending_signature_release_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository, commit = self.release_repository(root / "candidate")
            output = root / "output"
            receipt = prepare_release_candidate(
                repository,
                commit,
                output,
                owner_fingerprint=SYNTHETIC_FINGERPRINT,
                key_generation="synthetic-generation-1",
            )
            validate_release_candidate_preparation_receipt(receipt)
            manifest_bytes = (output / "release-manifest.json").read_bytes()
            manifest = json.loads(manifest_bytes)
            validate_release_manifest(manifest)
            self.assertEqual(manifest["status"], "release-candidate")
            self.assertEqual(manifest["signature"]["state"], "pending-owner-signature")
            self.assertFalse(manifest["signature"]["owner_signed_annotated_tag"])
            self.assertEqual(manifest["source"]["commit"], commit)
            self.assertEqual(manifest["surfaces"]["reference_cli"]["package_version"], "0.1.0")
            self.assertEqual(
                manifest["surfaces"]["reference_cli"]["stability"],
                "development-preview",
            )
            self.assertEqual(manifest["attestations"]["state"], "deferred-public-workflow-review")
            self.assertEqual(receipt["signature_verification_state"], "pending-owner-signature")
            self.assertEqual(receipt["publication_state"], "not-authorized")
            self.assertEqual(
                receipt["tag_message_trailer"],
                "Artifact-Memory-Manifest-SHA256: " + receipt["release_manifest_digest"],
            )
            self.assertEqual(
                set(path.name for path in output.iterdir()),
                {
                    "artifact-memory-0.1.0.tar",
                    "artifact-memory-0.1.0-release-notes.md",
                    "SHA256SUMS",
                    "release-manifest.json",
                    "release-candidate-preparation-receipt.json",
                    "release-candidate-preparation-receipt.md",
                },
            )
            checksum_lines = (output / "SHA256SUMS").read_text(encoding="ascii").splitlines()
            self.assertEqual(
                [line.split("  ", 1)[1] for line in checksum_lines],
                ["artifact-memory-0.1.0.tar", "artifact-memory-0.1.0-release-notes.md"],
            )
            self.assertNotIn("release-manifest.json", (output / "SHA256SUMS").read_text())
            self.assertEqual(receipt["release_manifest_digest"], sha256_bytes(manifest_bytes))
            for artifact in manifest["artifacts"]:
                content = (output / artifact["name"]).read_bytes()
                self.assertEqual(artifact["byte_size"], len(content))
                self.assertEqual(artifact["sha256"], sha256_bytes(content))

    def test_release_candidate_is_deterministic_for_one_exact_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository, commit = self.release_repository(root / "candidate")
            outputs = [root / "first", root / "second"]
            receipts = [
                prepare_release_candidate(
                    repository,
                    commit,
                    output,
                    owner_fingerprint=SYNTHETIC_FINGERPRINT,
                    key_generation="synthetic-generation-1",
                )
                for output in outputs
            ]
            self.assertEqual(receipts[0], receipts[1])
            self.assertEqual(
                {path.name: path.read_bytes() for path in outputs[0].iterdir()},
                {path.name: path.read_bytes() for path in outputs[1].iterdir()},
            )

    def test_release_candidate_cli_reports_exact_manifest_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository, commit = self.release_repository(root / "candidate")
            output = root / "output"
            result = self.run_candidate_cli(repository, commit, output)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            summary = json.loads(result.stdout)
            receipt = json.loads(
                (output / "release-candidate-preparation-receipt.json").read_text()
            )
            self.assertEqual(summary["receipt_id"], receipt["receipt_id"])
            self.assertEqual(summary["tag_message_trailer"], receipt["tag_message_trailer"])
            self.assertEqual(summary["signature_verification_state"], "pending-owner-signature")

    def test_release_candidate_cli_emits_canonical_plain_text_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository, commit = self.release_repository(root / "candidate")
            output = root / "output"
            result = self.run_candidate_cli(
                repository,
                commit,
                output,
                plain_text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout,
                (output / "release-candidate-preparation-receipt.md").read_text(
                    encoding="utf-8"
                ),
            )

    def test_release_candidate_fails_closed_without_final_public_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = [
                ("development-version", "0.1.0.dev0", b"notes\n"),
                ("missing-notes", "0.1.0", None),
                ("empty-notes", "0.1.0", b" \n"),
                ("non-utf8-notes", "0.1.0", b"\xff"),
            ]
            for name, version, notes in cases:
                with self.subTest(name=name):
                    repository, commit = self.release_repository(
                        root / name,
                        package_version=version,
                        release_notes=notes,
                    )
                    output = root / f"{name}-output"
                    with self.assertRaises(ValidationFailure):
                        prepare_release_candidate(
                            repository,
                            commit,
                            output,
                            owner_fingerprint=SYNTHETIC_FINGERPRINT,
                            key_generation="synthetic-generation-1",
                        )
                    self.assertFalse(output.exists())

    def test_release_candidate_rejects_mismatched_runtime_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository, commit = self.release_repository(
                root / "candidate",
                runtime_version="0.1.0.dev0",
            )
            with self.assertRaises(ValidationFailure) as failure:
                prepare_release_candidate(
                    repository,
                    commit,
                    root / "output",
                    owner_fingerprint=SYNTHETIC_FINGERPRINT,
                    key_generation="synthetic-generation-1",
                )
            self.assertEqual(
                failure.exception.code,
                "release-candidate-runtime-version-mismatch",
            )

    def test_release_candidate_rejects_missing_runtime_version_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository, _commit = self.release_repository(root / "candidate")
            subprocess.run(
                ["git", "rm", "--quiet", "artifact_memory/__init__.py"],
                cwd=repository,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "--quiet", "-m", "Remove runtime version"],
                cwd=repository,
                check=True,
            )
            commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repository, text=True
            ).strip()
            with self.assertRaises(ValidationFailure) as failure:
                prepare_release_candidate(
                    repository,
                    commit,
                    root / "output",
                    owner_fingerprint=SYNTHETIC_FINGERPRINT,
                    key_generation="synthetic-generation-1",
                )
            self.assertEqual(
                failure.exception.code,
                "release-runtime-version-unavailable",
            )

    def test_release_candidate_rejects_invalid_public_signing_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository, commit = self.release_repository(root / "candidate")
            for fingerprint, generation, code in (
                ("SHA256:short", "generation-1", "release-candidate-owner-fingerprint-invalid"),
                (None, "generation-1", "release-candidate-owner-fingerprint-invalid"),
                (b"not-text", "generation-1", "release-candidate-owner-fingerprint-invalid"),
                (SYNTHETIC_FINGERPRINT, "", "release-candidate-key-generation-invalid"),
                (SYNTHETIC_FINGERPRINT, "generation 1", "release-candidate-key-generation-invalid"),
            ):
                with self.subTest(code=code):
                    with self.assertRaises(ValidationFailure) as failure:
                        prepare_release_candidate(
                            repository,
                            commit,
                            root / code,
                            owner_fingerprint=fingerprint,  # type: ignore[arg-type]
                            key_generation=generation,
                        )
                    self.assertEqual(failure.exception.code, code)

    def test_invalid_signing_metadata_does_not_create_output_parents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository, commit = self.release_repository(root / "candidate")
            output = root / "missing" / "nested" / "release"
            with self.assertRaises(ValidationFailure) as failure:
                prepare_release_candidate(
                    repository,
                    commit,
                    output,
                    owner_fingerprint="SHA256:short",
                    key_generation="generation-1",
                )
            self.assertEqual(
                failure.exception.code,
                "release-candidate-owner-fingerprint-invalid",
            )
            self.assertFalse(output.parent.parent.exists())

    def test_candidate_receipt_fixture_and_manifest_binding_are_checked(self):
        fixture_root = ROOT / "fixtures/synthetic/release"
        receipt = json.loads(
            (fixture_root / "v0-release-candidate-preparation-receipt.json").read_text()
        )
        validate_release_candidate_preparation_receipt(receipt)
        self.assertEqual(
            render_release_candidate_preparation_receipt(receipt),
            (fixture_root / "v0-release-candidate-preparation-receipt.md").read_text(),
        )
        body = {
            key: value
            for key, value in receipt.items()
            if key not in {"schema_id", "receipt_id"}
        }
        body["tag_message_trailer"] = (
            "Artifact-Memory-Manifest-SHA256: sha-256:" + "9" * 64
        )
        tampered = receipt_with_digest(
            RELEASE_CANDIDATE_PREPARATION_SCHEMA_ID,
            RELEASE_CANDIDATE_PREPARATION_RECEIPT_PREFIX,
            body,
        )
        with self.assertRaises(ValidationFailure) as failure:
            validate_release_candidate_preparation_receipt(tampered)
        self.assertEqual(
            failure.exception.code,
            "release-candidate-preparation-manifest-binding-invalid",
        )

    def test_candidate_preparation_receipt_cli_supports_json_and_canonical_text(self):
        fixture_root = ROOT / "fixtures/synthetic/release"
        fixture = fixture_root / "v0-release-candidate-preparation-receipt.json"
        text_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "artifact_memory",
                "validate-release-candidate-preparation-receipt",
                str(fixture),
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        json_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "artifact_memory",
                "validate-release-candidate-preparation-receipt",
                str(fixture),
                "--json",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(text_result.returncode, 0, text_result.stderr)
        self.assertEqual(
            text_result.stdout,
            (fixture_root / "v0-release-candidate-preparation-receipt.md").read_text(
                encoding="utf-8"
            ),
        )
        self.assertEqual(json_result.returncode, 0, json_result.stderr)
        summary = json.loads(json_result.stdout)
        self.assertEqual(summary["outcome"], "integrity-verified")
        self.assertFalse(summary["owner_signature_verified"])
        self.assertEqual(
            summary["tag_message_trailer"],
            json.loads(fixture.read_text(encoding="utf-8"))["tag_message_trailer"],
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
