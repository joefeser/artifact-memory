import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from artifact_memory.release import validate_release_manifest
from artifact_memory.release_conformance import render_release_conformance, run_release_conformance
from artifact_memory.validator import ValidationFailure, validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/synthetic/release"


class ReleaseManifestTests(unittest.TestCase):
    def test_released_v2_contract_and_fixture_bytes_remain_frozen(self):
        expected = {
            "artifact_memory/schemas/core/release-manifest.v2.schema.json": "61f383f256e4c677cd15993a92d2ac77cd50f8c4f8e2086160d9015341aa67b1",
            "artifact_memory/schemas/core/release-candidate-preparation-receipt.v2.schema.json": "f525f631cd88484864cf9c50fffb1c8809a20dc6919fc68622cbc86236c69c05",
            "artifact_memory/schemas/core/release-candidate-verification-receipt.v2.schema.json": "e2f2c03ad720fff2ef800a19f0a8b6f92942a17a87a1a2afb651db151790cd14",
            "fixtures/synthetic/release/v0-pending-candidate-manifest.v2.json": "de7955c12e207b73d8a3d489e9b5a2cb6da57ea8a13e0d9b0f3a5255fcf5a606",
            "fixtures/synthetic/release/v0-release-candidate-verification-receipt.v2.json": "2af4afdb1e43069d935542ed6b9394f798ade10a11d72b9358785f87ed94238d",
        }
        for relative_path, digest in expected.items():
            with self.subTest(path=relative_path):
                self.assertEqual(
                    hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest(),
                    digest,
                )

    def test_legacy_preview_manifest_remains_schema_valid(self):
        schema = json.loads((ROOT / "artifact_memory/schemas/core/release-manifest.v1.schema.json").read_text(encoding="utf-8"))
        manifest = json.loads((FIXTURE / "v0-preview-manifest.json").read_text(encoding="utf-8"))
        validate(manifest, schema)
        validate_release_manifest(manifest)
        self.assertEqual(manifest["status"], "preview")
        self.assertEqual(manifest["signature"]["state"], "not-signed")

    def test_v1_manifest_cannot_claim_release_status(self):
        manifest = json.loads((FIXTURE / "v0-preview-manifest.json").read_text(encoding="utf-8"))
        manifest["status"] = "release"
        with self.assertRaises(ValidationFailure) as failure:
            validate_release_manifest(manifest)
        self.assertEqual(failure.exception.code, "release-manifest-migration-required")

    def test_v2_preview_reproduces_public_safe_release_materials(self):
        manifest = json.loads((FIXTURE / "v0-preview-manifest.v2.json").read_text(encoding="utf-8"))
        validate_release_manifest(manifest)
        receipt = run_release_conformance(FIXTURE)
        expected = json.loads((FIXTURE / "v0-preview-expected-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt, expected)
        self.assertEqual(render_release_conformance(receipt), (FIXTURE / "v0-preview-receipt.md").read_text(encoding="utf-8"))
        self.assertEqual(receipt["signature_state"], "unsigned-preview")
        self.assertEqual(receipt["publication_state"], "not-authorized")

    def test_v3_candidate_records_pending_post_publication_attestation(self):
        manifest = json.loads(
            (FIXTURE / "v0-pending-candidate-manifest.v3.json").read_text(
                encoding="utf-8"
            )
        )
        validate_release_manifest(manifest)
        self.assertEqual(manifest["status"], "release-candidate")
        self.assertEqual(
            manifest["attestations"],
            {
                "state": "pending-post-publication",
                "requirement": "keyless-build-artifact-attestations-after-publication",
                "evidence_boundary": "external-subject-bound-bundle",
            },
        )

    def test_v3_candidate_rejects_premature_or_embedded_attestation_claims(self):
        original = json.loads(
            (FIXTURE / "v0-pending-candidate-manifest.v3.json").read_text(
                encoding="utf-8"
            )
        )
        mutations = (
            ("published", lambda value: value["attestations"].update(state="published")),
            ("verified", lambda value: value["attestations"].update(state="verified")),
            (
                "url",
                lambda value: value["attestations"].update(
                    url="https://synthetic.example/attestation"
                ),
            ),
            (
                "bundle",
                lambda value: value["attestations"].update(bundle={"synthetic": True}),
            ),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                candidate = copy.deepcopy(original)
                mutate(candidate)
                with self.assertRaises(ValidationFailure):
                    validate_release_manifest(candidate)

    def test_candidate_manifest_schema_is_bound_to_release_version(self):
        historical = json.loads(
            (FIXTURE / "v0-pending-candidate-manifest.v2.json").read_text(
                encoding="utf-8"
            )
        )
        future = json.loads(
            (FIXTURE / "v0-pending-candidate-manifest.v3.json").read_text(
                encoding="utf-8"
            )
        )
        mismatches = (
            (historical, "0.1.2"),
            (future, "0.1.1"),
        )
        for manifest, release_version in mismatches:
            with self.subTest(
                schema_id=manifest["schema_id"], release_version=release_version
            ):
                candidate = copy.deepcopy(manifest)
                candidate["release_id"] = f"artifact-memory/v{release_version}"
                candidate["signature"]["tag"] = f"v{release_version}"
                candidate["surfaces"]["reference_cli"][
                    "package_version"
                ] = release_version
                with self.assertRaises(ValidationFailure) as failure:
                    validate_release_manifest(candidate)
                self.assertEqual(
                    failure.exception.code,
                    "release-manifest-version-binding-invalid",
                )

    def test_unsigned_manifest_cannot_claim_release_status(self):
        manifest = json.loads((FIXTURE / "v0-preview-manifest.v2.json").read_text(encoding="utf-8"))
        manifest["status"] = "release"
        manifest["release_id"] = "artifact-memory/v0.1.0"
        with self.assertRaises(ValidationFailure):
            validate_release_manifest(manifest)

    def test_duplicate_artifact_names_fail_closed(self):
        manifest = json.loads((FIXTURE / "v0-preview-manifest.v2.json").read_text(encoding="utf-8"))
        manifest["artifacts"][1]["name"] = manifest["artifacts"][0]["name"]
        with self.assertRaises(ValidationFailure) as failure:
            validate_release_manifest(manifest)
        self.assertEqual(failure.exception.code, "release-artifact-duplicate")

    def test_case_colliding_artifact_names_fail_closed(self):
        manifest = json.loads((FIXTURE / "v0-preview-manifest.v2.json").read_text(encoding="utf-8"))
        duplicate = copy.deepcopy(manifest["artifacts"][0])
        duplicate["name"] = duplicate["name"].upper()
        duplicate["kind"] = "documentation"
        manifest["artifacts"].append(duplicate)
        with self.assertRaises(ValidationFailure) as failure:
            validate_release_manifest(manifest)
        self.assertEqual(failure.exception.code, "release-artifact-case-collision")

    def test_optional_manifest_extensions_are_preserved_and_required_fail_closed(self):
        identifier = "https://synthetic.example/release-preview"
        declaration = {"version": "v1", "required": False, "value": {"opaque": True}}
        manifest = json.loads((FIXTURE / "v0-preview-manifest.v2.json").read_text(encoding="utf-8"))
        manifest["extensions"] = {identifier: declaration}
        validate_release_manifest(manifest)
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            for source in FIXTURE.iterdir():
                if source.is_file():
                    (fixture / source.name).write_bytes(source.read_bytes())
            (fixture / "v0-preview-manifest.v2.json").write_text(json.dumps(manifest), encoding="utf-8")
            receipt = run_release_conformance(fixture)
        self.assertEqual(receipt["extensions"], {identifier: declaration})
        manifest["extensions"][identifier]["required"] = True
        with self.assertRaises(ValidationFailure) as failure:
            validate_release_manifest(manifest)
        self.assertEqual(failure.exception.code, "required-extension-unsupported")
        validate_release_manifest(
            manifest,
            supported_required_extensions={(identifier, "v1")},
        )
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            for source in FIXTURE.iterdir():
                if source.is_file():
                    (fixture / source.name).write_bytes(source.read_bytes())
            (fixture / "v0-preview-manifest.v2.json").write_text(json.dumps(manifest), encoding="utf-8")
            receipt = run_release_conformance(
                fixture,
                supported_required_extensions={(identifier, "v1")},
            )
        self.assertTrue(receipt["extensions"][identifier]["required"])

    def test_correct_adapter_schema_claim_passes_conformance(self):
        manifest = json.loads((FIXTURE / "v0-preview-manifest.v2.json").read_text(encoding="utf-8"))
        manifest["surfaces"]["adapters"]["supported_manifest_schemas"] = ["artifact-memory/adapter-manifest/v1"]
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            for source in FIXTURE.iterdir():
                if source.is_file():
                    (fixture / source.name).write_bytes(source.read_bytes())
            (fixture / "v0-preview-manifest.v2.json").write_text(json.dumps(manifest), encoding="utf-8")
            receipt = run_release_conformance(fixture)
        self.assertEqual(receipt["outcome"], "pass")

    def test_stale_adapter_schema_claim_fails_closed(self):
        manifest = json.loads((FIXTURE / "v0-preview-manifest.v2.json").read_text(encoding="utf-8"))
        manifest["surfaces"]["adapters"]["supported_manifest_schemas"] = [
            "artifact-memory/adapter-manifest/v1",
            "artifact-memory/adapter-manifest/v2",
        ]
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            for source in FIXTURE.iterdir():
                if source.is_file():
                    (fixture / source.name).write_bytes(source.read_bytes())
            (fixture / "v0-preview-manifest.v2.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValidationFailure) as failure:
                run_release_conformance(fixture)
        self.assertEqual(failure.exception.code, "release-adapter-schema-claim-mismatch")

    def test_primary_schema_is_still_checked_when_supported_list_is_absent(self):
        """A v2 manifest omitting supported_manifest_schemas must not skip verification."""
        manifest = json.loads((FIXTURE / "v0-preview-manifest.v2.json").read_text(encoding="utf-8"))
        self.assertNotIn("supported_manifest_schemas", manifest["surfaces"]["adapters"])
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            for source in FIXTURE.iterdir():
                if source.is_file():
                    (fixture / source.name).write_bytes(source.read_bytes())
            (fixture / "v0-preview-manifest.v2.json").write_text(json.dumps(manifest), encoding="utf-8")
            with mock.patch(
                "artifact_memory.release_conformance._supported_adapter_manifest_schemas",
                return_value=["artifact-memory/adapter-manifest/v2"],
            ) as reproduced:
                with self.assertRaises(ValidationFailure) as failure:
                    run_release_conformance(fixture)
            reproduced.assert_called_once()
        self.assertEqual(failure.exception.code, "release-adapter-schema-claim-mismatch")

    def test_v1_fixture_reports_typed_migration_requirement(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            (fixture / "v0-preview-manifest.json").write_bytes(
                (FIXTURE / "v0-preview-manifest.json").read_bytes()
            )
            with self.assertRaises(ValidationFailure) as failure:
                run_release_conformance(fixture)
        self.assertEqual(failure.exception.code, "release-manifest-migration-required")

    def test_documentation_asset_bytes_are_reproduced(self):
        manifest = json.loads((FIXTURE / "v0-preview-manifest.v2.json").read_text(encoding="utf-8"))
        documentation = b"synthetic release notes\n"
        documentation_name = "SYNTHETIC-NOTES.md"
        documentation_digest = hashlib.sha256(documentation).hexdigest()
        manifest["artifacts"].append(
            {
                "name": documentation_name,
                "kind": "documentation",
                "format": "markdown",
                "byte_size": len(documentation),
                "sha256": "sha-256:" + documentation_digest,
                "provenance": "newly authored synthetic release fixture",
            }
        )
        checksum_name = manifest["checksum_manifest"]["artifact_name"]
        source = next(artifact for artifact in manifest["artifacts"] if artifact["kind"] == "source-archive")
        checksum = f"{source['sha256'].removeprefix('sha-256:')}  {source['name']}\n{documentation_digest}  {documentation_name}\n".encode("ascii")
        checksum_artifact = next(artifact for artifact in manifest["artifacts"] if artifact["kind"] == "checksum-file")
        checksum_artifact["byte_size"] = len(checksum)
        checksum_artifact["sha256"] = "sha-256:" + hashlib.sha256(checksum).hexdigest()

        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            (fixture / "v0-preview-manifest.v2.json").write_text(json.dumps(manifest), encoding="utf-8")
            (fixture / checksum_name).write_bytes(checksum)
            with self.assertRaises(ValidationFailure) as missing:
                run_release_conformance(fixture)
            self.assertEqual(missing.exception.code, "release-artifact-unavailable")
            (fixture / documentation_name).write_bytes(documentation)
            self.assertEqual(run_release_conformance(fixture)["outcome"], "pass")

    def test_non_ascii_checksum_manifest_fails_closed(self):
        manifest = json.loads((FIXTURE / "v0-preview-manifest.v2.json").read_text(encoding="utf-8"))
        checksum_name = manifest["checksum_manifest"]["artifact_name"]
        checksum = b"\xff"
        checksum_artifact = next(artifact for artifact in manifest["artifacts"] if artifact["kind"] == "checksum-file")
        checksum_artifact["byte_size"] = len(checksum)
        checksum_artifact["sha256"] = "sha-256:" + hashlib.sha256(checksum).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            (fixture / "v0-preview-manifest.v2.json").write_text(json.dumps(manifest), encoding="utf-8")
            (fixture / checksum_name).write_bytes(checksum)
            with self.assertRaises(ValidationFailure) as failure:
                run_release_conformance(fixture)
            self.assertEqual(failure.exception.code, "release-checksum-encoding-invalid")

    def test_release_cli_reports_invalid_fixture_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                ["python3", "scripts/run_release_conformance.py", "--fixture", directory, "--check"],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("release-preview-fixture-invalid", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_released_tag_must_match_release_identifier(self):
        manifest = json.loads((FIXTURE / "v0-preview-manifest.v2.json").read_text(encoding="utf-8"))
        released = copy.deepcopy(manifest)
        released["status"] = "release"
        released["release_id"] = "artifact-memory/v0.1.0"
        released["signature"] = {
            "state": "owner-signed",
            "tag": "v0.1.1",
            "algorithm": "ssh-ed25519",
            "public_key_fingerprint": "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "key_generation": "generation-1",
            "owner_signed_annotated_tag": True,
        }
        with self.assertRaises(ValidationFailure) as failure:
            validate_release_manifest(released)
        self.assertEqual(failure.exception.code, "release-tag-mismatch")

    def test_existing_v2_release_status_remains_structurally_valid(self):
        manifest = json.loads(
            (FIXTURE / "v0-preview-manifest.v2.json").read_text(encoding="utf-8")
        )
        manifest["status"] = "release"
        manifest["release_id"] = "artifact-memory/v0.1.0"
        manifest["signature"] = {
            "state": "owner-signed",
            "tag": "v0.1.0",
            "algorithm": "ssh-ed25519",
            "public_key_fingerprint": "SHA256:" + "A" * 43,
            "key_generation": "generation-1",
            "owner_signed_annotated_tag": True,
        }
        validate_release_manifest(manifest)

    def test_pending_candidate_is_rejected_before_preview_conformance_git_work(self):
        candidate = FIXTURE / "v0-pending-candidate-manifest.v2.json"
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            (fixture / "v0-preview-manifest.v2.json").write_bytes(candidate.read_bytes())
            with mock.patch("artifact_memory.release_conformance._git") as git_read:
                with self.assertRaises(ValidationFailure) as failure:
                    run_release_conformance(fixture)
        self.assertEqual(failure.exception.code, "release-preview-lifecycle-invalid")
        git_read.assert_not_called()

    def test_pending_candidate_schema_requires_canonical_fingerprint(self):
        manifest = json.loads(
            (FIXTURE / "v0-pending-candidate-manifest.v2.json").read_text(
                encoding="utf-8"
            )
        )
        validate_release_manifest(manifest)
        for fingerprint in ("SHA256:" + "A" * 20 + "==", "SHA256:short"):
            with self.subTest(fingerprint=fingerprint):
                invalid = copy.deepcopy(manifest)
                invalid["signature"]["public_key_fingerprint"] = fingerprint
                with self.assertRaises(ValidationFailure):
                    validate_release_manifest(invalid)

    def test_pending_candidate_schema_requires_bounded_key_generation(self):
        manifest = json.loads(
            (FIXTURE / "v0-pending-candidate-manifest.v2.json").read_text(
                encoding="utf-8"
            )
        )
        for key_generation in ("A", "generation-1", "a" * 64):
            with self.subTest(key_generation=key_generation):
                valid = copy.deepcopy(manifest)
                valid["signature"]["key_generation"] = key_generation
                validate_release_manifest(valid)
        for key_generation in ("", "generation 1", "génération-1", "a" * 65):
            with self.subTest(key_generation=key_generation):
                invalid = copy.deepcopy(manifest)
                invalid["signature"]["key_generation"] = key_generation
                with self.assertRaises(ValidationFailure):
                    validate_release_manifest(invalid)

    def test_historical_release_keeps_nonempty_key_generation_compatibility(self):
        manifest = json.loads(
            (FIXTURE / "v0-preview-manifest.v2.json").read_text(encoding="utf-8")
        )
        manifest["status"] = "release"
        manifest["release_id"] = "artifact-memory/v0.1.0"
        manifest["signature"] = {
            "state": "owner-signed",
            "tag": "v0.1.0",
            "algorithm": "ssh-ed25519",
            "public_key_fingerprint": "SHA256:" + "A" * 43,
            "key_generation": "legacy generation 1",
            "owner_signed_annotated_tag": True,
        }
        validate_release_manifest(manifest)

    def test_legacy_v2_fingerprint_is_schema_readable_but_requires_migration(self):
        manifest = json.loads((FIXTURE / "v0-preview-manifest.v2.json").read_text(encoding="utf-8"))
        manifest["status"] = "release"
        manifest["release_id"] = "artifact-memory/v0.1.0"
        manifest["signature"] = {
            "state": "owner-signed",
            "tag": "v0.1.0",
            "algorithm": "ssh-ed25519",
            "public_key_fingerprint": "SHA256:" + "A" * 20 + "==",
            "key_generation": "legacy-generation",
            "owner_signed_annotated_tag": True,
        }
        schema = json.loads(
            (ROOT / "artifact_memory/schemas/core/release-manifest.v2.schema.json").read_text(
                encoding="utf-8"
            )
        )
        validate(manifest, schema)
        with self.assertRaises(ValidationFailure) as failure:
            validate_release_manifest(manifest)
        self.assertEqual(failure.exception.code, "release-fingerprint-migration-required")


if __name__ == "__main__":
    unittest.main()
