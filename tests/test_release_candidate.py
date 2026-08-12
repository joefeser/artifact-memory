import base64
import copy
import hashlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from artifact_memory.canonical import receipt_with_digest
from artifact_memory.cli import EXIT_INVALID, main
from artifact_memory.release import (
    RELEASE_VERIFICATION_RECEIPT_PREFIX,
    RELEASE_VERIFICATION_SCHEMA_ID,
    _replay_git_output_against_asset,
    _signed_manifest_digest,
    _ssh_ed25519_fingerprint,
    _matching_allowed_signer_lines,
    render_release_candidate_verification_receipt,
    validate_release_candidate_identity,
    validate_release_candidate_verification_receipt,
    verify_checked_out_release_candidate,
)
from artifact_memory.validator import ValidationFailure


MANIFEST = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures/synthetic/release/v0-preview-manifest.v2.json").read_text(
        encoding="utf-8"
    )
)
TREE_LISTING = b"100644 blob 0123456789abcdef0123456789abcdef01234567\tdocs/release/v0.1.0-release-manifest.json\n"
SYNTHETIC_KEY_BLOB = b"synthetic-ed25519-public-key-blob"
SYNTHETIC_PUBLIC_KEY = base64.b64encode(SYNTHETIC_KEY_BLOB).decode("ascii")
SYNTHETIC_FINGERPRINT = _ssh_ed25519_fingerprint(SYNTHETIC_PUBLIC_KEY)
SYNTHETIC_ARCHIVE = b"synthetic release archive\n"
SYNTHETIC_NOTES = b"# Synthetic release notes\n"
SYNTHETIC_ARCHIVE_NAME = "artifact-memory-0.1.0.tar"
SYNTHETIC_NOTES_NAME = "artifact-memory-0.1.0-release-notes.md"
SYNTHETIC_NOTES_SOURCE = "docs/release/v0.1.0-release-notes.md"


def release_manifest(
    version: str = "0.1.0",
    schema_id: str = "artifact-memory/release-manifest/v2",
) -> dict:
    manifest = copy.deepcopy(MANIFEST)
    commit = "a" * 40
    tag = f"v{version}"
    archive_name = f"artifact-memory-{version}.tar"
    notes_name = f"artifact-memory-{version}-release-notes.md"
    notes_source = f"docs/release/v{version}-release-notes.md"
    manifest["schema_id"] = schema_id
    manifest["release_id"] = f"artifact-memory/{tag}"
    manifest["status"] = "release-candidate"
    manifest["source"]["commit"] = commit
    manifest["source"]["tree_digest"] = f"sha-256:{hashlib.sha256(TREE_LISTING).hexdigest()}"
    manifest["surfaces"]["reference_cli"] = {
        "package_version": version,
        "stability": "stable",
    }
    manifest["signature"] = {
        "state": "pending-owner-signature",
        "tag": tag,
        "algorithm": "ssh-ed25519",
        "public_key_fingerprint": SYNTHETIC_FINGERPRINT,
        "key_generation": "generation-1",
        "owner_signed_annotated_tag": False,
    }
    if schema_id == "artifact-memory/release-manifest/v3":
        manifest["attestations"] = {
            "state": "pending-post-publication",
            "requirement": "keyless-build-artifact-attestations-after-publication",
            "evidence_boundary": "external-subject-bound-bundle",
        }
    archive_digest = hashlib.sha256(SYNTHETIC_ARCHIVE).hexdigest()
    notes_digest = hashlib.sha256(SYNTHETIC_NOTES).hexdigest()
    checksum = (
        f"{archive_digest}  {archive_name}\n"
        f"{notes_digest}  {notes_name}\n"
    ).encode("ascii")
    manifest["artifacts"] = [
        {
            "name": archive_name,
            "kind": "source-archive",
            "format": "git-archive-tar",
            "byte_size": len(SYNTHETIC_ARCHIVE),
            "sha256": "sha-256:" + archive_digest,
            "provenance": (
                f"git archive --format=tar --prefix=artifact-memory-{version}/ "
                + commit
            ),
        },
        {
            "name": notes_name,
            "kind": "documentation",
            "format": "markdown",
            "byte_size": len(SYNTHETIC_NOTES),
            "sha256": "sha-256:" + notes_digest,
            "provenance": f"exact bytes from {commit}:{notes_source}",
        },
        {
            "name": "SHA256SUMS",
            "kind": "checksum-file",
            "format": "sha256sum-v1",
            "byte_size": len(checksum),
            "sha256": "sha-256:" + hashlib.sha256(checksum).hexdigest(),
            "provenance": "synthetic canonical checksum fixture",
        },
    ]
    manifest["checksum_manifest"] = {
        "artifact_name": "SHA256SUMS",
        "format": "sha256sum-v1",
        "scope": "all-manifest-listed-artifacts-except-checksum-manifest-itself",
    }
    manifest["limitations"] = [
        "verification proves only the identities and cryptographic bindings represented in this receipt",
        "publication, visibility, deployment, and release authority remain absent",
    ]
    return manifest


def historical_release_manifest() -> dict:
    manifest = release_manifest()
    manifest["status"] = "release"
    manifest["signature"]["state"] = "owner-signed"
    manifest["signature"]["owner_signed_annotated_tag"] = True
    return manifest


def git_output_for(manifest_bytes: bytes):
    manifest = json.loads(manifest_bytes)
    manifest_digest = f"sha-256:{hashlib.sha256(manifest_bytes).hexdigest()}"
    commit = manifest["source"]["commit"]
    tag = manifest["signature"]["tag"]
    archive_name = next(
        artifact["name"]
        for artifact in manifest["artifacts"]
        if artifact["kind"] == "source-archive"
    )
    notes = next(
        artifact
        for artifact in manifest["artifacts"]
        if artifact["kind"] == "documentation"
    )
    notes_source = notes["provenance"].split(":", 1)[1]
    tag_object_id = "b" * 40
    tag_object = (
        f"object {commit}\n"
        "type commit\n"
        f"tag {tag}\n"
        "tagger Release Owner <owner@example.invalid> 0 +0000\n\n"
        f"Artifact Memory {tag}\n\n"
        f"Artifact-Memory-Manifest-SHA256: {manifest_digest}\n"
        "-----BEGIN SSH SIGNATURE-----\nsynthetic\n-----END SSH SIGNATURE-----\n"
    ).encode("utf-8")

    def output(args, **kwargs):
        command = tuple(args[1:])
        values = {
            ("rev-parse", "--show-object-format"): "sha1\n",
            ("config", "--path", "--get", "gpg.ssh.allowedSignersFile"): "allowed_signers\n",
            ("rev-parse", "HEAD"): commit + "\n",
            ("rev-parse", "--symbolic-full-name", "HEAD"): "HEAD\n",
            ("rev-parse", f"refs/tags/{tag}"): tag_object_id + "\n",
            ("rev-parse", f"{tag_object_id}^{{commit}}"): commit + "\n",
            ("cat-file", "-t", tag_object_id): "tag\n",
            ("cat-file", "tag", tag_object_id): tag_object,
            ("ls-tree", "-r", "--full-tree", f"{tag_object_id}^{{commit}}"): TREE_LISTING,
            (
                "archive",
                "--format=tar",
                f"--prefix={archive_name.removesuffix('.tar')}/",
                commit,
            ): SYNTHETIC_ARCHIVE,
            ("show", f"{commit}:{notes_source}"): SYNTHETIC_NOTES,
        }
        value = values[command]
        if kwargs.get("text") and isinstance(value, bytes):
            return value.decode("utf-8")
        if not kwargs.get("text") and isinstance(value, str):
            return value.encode("utf-8")
        return value

    return output


def synthetic_git_replay(
    git_args: list[str],
    repository_root: Path,
    asset_directory: Path,
    asset_name: str,
) -> None:
    del repository_root
    if git_args[0] == "archive":
        reproduced = SYNTHETIC_ARCHIVE
    elif git_args[0] == "show":
        reproduced = SYNTHETIC_NOTES
    else:
        raise AssertionError(f"unexpected synthetic Git replay command: {git_args}")
    if (asset_directory / asset_name).read_bytes() != reproduced:
        raise ValidationFailure(
            "release-candidate-asset-replay-mismatch",
            "staged release asset bytes do not match the verified tag commit",
        )


def write_allowed_signers(root: Path, *, public_key: str = SYNTHETIC_PUBLIC_KEY) -> Path:
    path = root / "allowed_signers"
    path.write_text(
        f"release-owner@example.invalid ssh-ed25519 {public_key} synthetic-release-key\n",
        encoding="utf-8",
    )
    return path


def write_release_assets(root: Path, manifest: dict | None = None) -> None:
    manifest = manifest or release_manifest()
    contents = {
        next(
            artifact["name"]
            for artifact in manifest["artifacts"]
            if artifact["kind"] == "source-archive"
        ): SYNTHETIC_ARCHIVE,
        next(
            artifact["name"]
            for artifact in manifest["artifacts"]
            if artifact["kind"] == "documentation"
        ): SYNTHETIC_NOTES,
    }
    checksum = "".join(
        f"{artifact['sha256'].removeprefix('sha-256:')}  {artifact['name']}\n"
        for artifact in manifest["artifacts"]
        if artifact["kind"] != "checksum-file"
    ).encode("ascii")
    contents["SHA256SUMS"] = checksum
    for name, content in contents.items():
        (root / name).write_bytes(content)


class ReleaseCandidateIdentityTests(unittest.TestCase):
    def setUp(self):
        self._replay_patcher = patch(
            "artifact_memory.release._replay_git_output_against_asset",
            side_effect=synthetic_git_replay,
        )
        self._replay_patcher.start()
        self._replay_patcher_active = True
        self.addCleanup(self._stop_replay_patcher)

    def _stop_replay_patcher(self):
        if self._replay_patcher_active:
            self._replay_patcher.stop()
            self._replay_patcher_active = False

    def test_allowed_signer_parser_requires_ed25519_at_the_key_position(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "allowed_signers"
            path.write_text(
                "owner@example.invalid ssh-rsa ssh-ed25519 "
                + SYNTHETIC_PUBLIC_KEY
                + "\n"
                + "owner@example.invalid cert-authority ssh-ed25519 "
                + SYNTHETIC_PUBLIC_KEY
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValidationFailure) as failure:
                _matching_allowed_signer_lines(path, SYNTHETIC_FINGERPRINT)
        self.assertEqual(
            failure.exception.code,
            "release-candidate-expected-signer-unavailable",
        )

    def test_allowed_signer_parser_rejects_malformed_or_incomplete_records(self):
        for record in ('owner@example.invalid namespaces="unterminated\n', "owner@example.invalid\n"):
            with self.subTest(record=record):
                with tempfile.TemporaryDirectory() as temporary:
                    path = Path(temporary) / "allowed_signers"
                    path.write_text(record, encoding="utf-8")
                    with self.assertRaises(ValidationFailure) as failure:
                        _matching_allowed_signer_lines(path, SYNTHETIC_FINGERPRINT)
                self.assertEqual(
                    failure.exception.code,
                    "release-candidate-allowed-signers-invalid",
                )

    def test_streamed_replay_prioritizes_git_failure_after_empty_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "asset.bin").write_bytes(b"expected bytes")

            class FailedProcess:
                stdout = io.BytesIO(b"")

                @staticmethod
                def poll():
                    return 1

                @staticmethod
                def wait():
                    return 1

                @staticmethod
                def kill():
                    raise AssertionError("completed Git process must not be killed")

            with patch(
                "artifact_memory.release.subprocess.Popen",
                return_value=FailedProcess(),
            ) as git_replay:
                with self.assertRaises(ValidationFailure) as failure:
                    _replay_git_output_against_asset(
                        ["show", "missing"],
                        root,
                        root,
                        "asset.bin",
                    )
            self.assertEqual(
                failure.exception.code,
                "release-candidate-asset-replay-failed",
            )
            self.assertIs(
                git_replay.call_args.kwargs["stderr"],
                subprocess.DEVNULL,
            )

    def test_rejects_ambiguous_signed_manifest_trailers(self):
        trailer = "Artifact-Memory-Manifest-SHA256: sha-256:" + "0" * 64 + "\n"
        with self.assertRaises(ValidationFailure) as failure:
            _signed_manifest_digest((trailer + trailer).encode("utf-8"))
        self.assertEqual(failure.exception.code, "release-candidate-manifest-binding-invalid")

    def test_rejects_missing_ssh_signature_boundary(self):
        trailer = "Artifact-Memory-Manifest-SHA256: sha-256:" + "0" * 64 + "\n"
        with self.assertRaises(ValidationFailure) as failure:
            _signed_manifest_digest(trailer.encode("utf-8"))
        self.assertEqual(failure.exception.code, "release-candidate-manifest-binding-invalid")

    def test_checked_synthetic_verification_receipt_and_rendering(self):
        fixture_root = Path(__file__).resolve().parents[1] / "fixtures/synthetic/release"
        expected_receipt = json.loads(
            (fixture_root / "v0-release-candidate-verification-receipt.v2.json").read_text(
                encoding="utf-8"
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_bytes = json.dumps(release_manifest()).encode("utf-8")
            manifest_path = root / "release.json"
            manifest_path.write_bytes(manifest_bytes)
            write_allowed_signers(root)
            write_release_assets(root)
            fingerprint = release_manifest()["signature"]["public_key_fingerprint"]
            verification = subprocess.CompletedProcess(
                args=["git", "verify-tag"],
                returncode=0,
                stdout="",
                stderr=f'Good "git" signature for release-owner@example.invalid with ED25519 key {fingerprint}\n',
            )
            with (
                patch("artifact_memory.release._repository_root", return_value=root),
                patch("artifact_memory.release.__version__", "0.1.0"),
                patch("artifact_memory.release.subprocess.run", return_value=verification),
                patch(
                    "artifact_memory.release.subprocess.check_output",
                    side_effect=git_output_for(manifest_bytes),
                ),
            ):
                receipt = verify_checked_out_release_candidate(
                    manifest_path,
                    "v0.1.0",
                    root,
                    asset_directory=root,
                    owner_fingerprint=SYNTHETIC_FINGERPRINT,
                    isolated_checkout=True,
                )
        self.assertEqual(receipt, expected_receipt)
        validate_release_candidate_verification_receipt(receipt)
        self.assertEqual(
            render_release_candidate_verification_receipt(receipt),
            (fixture_root / "v0-release-candidate-verification-receipt.v2.md").read_text(encoding="utf-8"),
        )

    def test_v3_candidate_verification_receipts_pending_attestation_separately(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = release_manifest(
                "0.1.2", "artifact-memory/release-manifest/v3"
            )
            manifest_bytes = json.dumps(manifest).encode("utf-8")
            manifest_path = root / "release.json"
            manifest_path.write_bytes(manifest_bytes)
            write_allowed_signers(root)
            write_release_assets(root, manifest)
            fingerprint = manifest["signature"]["public_key_fingerprint"]
            verification = subprocess.CompletedProcess(
                args=["git", "verify-tag"],
                returncode=0,
                stdout="",
                stderr=(
                    'Good "git" signature for release-owner@example.invalid '
                    f"with ED25519 key {fingerprint}\n"
                ),
            )
            with (
                patch("artifact_memory.release._repository_root", return_value=root),
                patch("artifact_memory.release.__version__", "0.1.2"),
                patch("artifact_memory.release.subprocess.run", return_value=verification),
                patch(
                    "artifact_memory.release.subprocess.check_output",
                    side_effect=git_output_for(manifest_bytes),
                ),
            ):
                receipt = verify_checked_out_release_candidate(
                    manifest_path,
                    "v0.1.2",
                    root,
                    asset_directory=root,
                    owner_fingerprint=SYNTHETIC_FINGERPRINT,
                    isolated_checkout=True,
                )
        self.assertEqual(
            receipt["schema_id"],
            "artifact-memory/release-candidate-verification-receipt/v3",
        )
        self.assertEqual(receipt["attestation_state"], "pending-post-publication")
        self.assertFalse(receipt["attestation_evidence_evaluated"])
        validate_release_candidate_verification_receipt(receipt)
        rendered = render_release_candidate_verification_receipt(receipt)
        self.assertIn("Attestation state: `pending-post-publication`", rendered)
        self.assertIn("Attestation evidence evaluated: `false`", rendered)

    def test_receipt_cli_reports_integrity_without_replaying_live_evidence(self):
        fixture = Path(__file__).resolve().parents[1] / (
            "fixtures/synthetic/release/v0-release-candidate-verification-receipt.json"
        )
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(
                ["validate-release-candidate-receipt", str(fixture), "--json"]
            )
        self.assertEqual(result, 0)
        receipt = json.loads(output.getvalue())
        self.assertEqual(receipt["outcome"], "integrity-verified")
        self.assertFalse(receipt["live_release_evidence_verified"])

    def test_historical_v1_receipt_remains_valid_and_renderable(self):
        fixture_root = Path(__file__).resolve().parents[1] / "fixtures/synthetic/release"
        receipt = json.loads(
            (fixture_root / "v0-release-candidate-verification-receipt.json").read_text(
                encoding="utf-8"
            )
        )
        validate_release_candidate_verification_receipt(receipt)
        self.assertEqual(
            render_release_candidate_verification_receipt(receipt),
            (fixture_root / "v0-release-candidate-verification-receipt.md").read_text(
                encoding="utf-8"
            ),
        )
        self.assertNotIn("asset_replay", receipt)

    def test_receipt_schema_is_bound_to_release_version(self):
        fixture_root = Path(__file__).resolve().parents[1] / "fixtures/synthetic/release"
        v1 = json.loads(
            (fixture_root / "v0-release-candidate-verification-receipt.json").read_text(
                encoding="utf-8"
            )
        )
        v2 = json.loads(
            (
                fixture_root
                / "v0-release-candidate-verification-receipt.v2.json"
            ).read_text(encoding="utf-8")
        )
        mismatches = (
            (v1, "artifact-memory/release-candidate-verification-receipt/v1", "0.1.1"),
            (v2, "artifact-memory/release-candidate-verification-receipt/v2", "0.1.2"),
            (v2, "artifact-memory/release-candidate-verification-receipt/v3", "0.1.1"),
        )
        for original, schema_id, version in mismatches:
            with self.subTest(schema_id=schema_id, version=version):
                body = {
                    key: value
                    for key, value in original.items()
                    if key not in {"schema_id", "receipt_id"}
                }
                body.update(
                    {
                        "tag": f"v{version}",
                        "release_id": f"artifact-memory/v{version}",
                        "manifest_package_version": version,
                        "package_version": version,
                    }
                )
                if schema_id.endswith("/v3"):
                    body.update(
                        {
                            "attestation_state": "pending-post-publication",
                            "attestation_requirement": "keyless-build-artifact-attestations-after-publication",
                            "attestation_evidence_evaluated": False,
                        }
                    )
                receipt = receipt_with_digest(
                    schema_id,
                    RELEASE_VERIFICATION_RECEIPT_PREFIX,
                    body,
                )
                with self.assertRaises(ValidationFailure) as failure:
                    validate_release_candidate_verification_receipt(receipt)
                self.assertEqual(
                    failure.exception.code,
                    "release-candidate-receipt-version-binding-invalid",
                )

    def test_receipt_rejects_rehashed_incoherent_release_identity(self):
        fixture = (
            Path(__file__).resolve().parents[1]
            / "fixtures/synthetic/release/v0-release-candidate-verification-receipt.json"
        )
        original = json.loads(fixture.read_text(encoding="utf-8"))
        for field, value in (
            ("head_commit", "c" * 40),
            ("package_version", "0.1.1"),
        ):
            body = {
                key: item
                for key, item in original.items()
                if key not in {"schema_id", "receipt_id"}
            }
            body[field] = value
            tampered = receipt_with_digest(
                original["schema_id"],
                RELEASE_VERIFICATION_RECEIPT_PREFIX,
                body,
            )
            with self.subTest(field=field):
                with self.assertRaises(ValidationFailure) as failure:
                    validate_release_candidate_verification_receipt(tampered)
                self.assertEqual(
                    failure.exception.code,
                    "release-candidate-receipt-evidence-incoherent",
                )

    def test_accepts_one_exact_release_identity(self):
        result = validate_release_candidate_identity(
            release_manifest(),
            tag="v0.1.0",
            head_commit="a" * 40,
            tag_commit="a" * 40,
            package_version="0.1.0",
        )
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["release_id"], "artifact-memory/v0.1.0")
        self.assertEqual(result["tag_commit"], "a" * 40)
        self.assertEqual(result["manifest_package_version"], "0.1.0")

    def test_rejects_v2_manifest_for_future_release_identity(self):
        manifest = release_manifest("0.1.2")
        with self.assertRaises(ValidationFailure) as failure:
            validate_release_candidate_identity(
                manifest,
                tag="v0.1.2",
                head_commit="a" * 40,
                tag_commit="a" * 40,
                package_version="0.1.2",
            )
        self.assertEqual(
            failure.exception.code,
            "release-manifest-version-binding-invalid",
        )

    def test_accepts_historical_release_identity(self):
        result = validate_release_candidate_identity(
            historical_release_manifest(),
            tag="v0.1.0",
            head_commit="a" * 40,
            tag_commit="a" * 40,
            package_version="0.1.0",
        )
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["release_id"], "artifact-memory/v0.1.0")

    def test_rejects_wrong_tag_commit(self):
        with self.assertRaisesRegex(ValidationFailure, "tag, HEAD, and manifest"):
            validate_release_candidate_identity(
                release_manifest(),
                tag="v0.1.0",
                head_commit="a" * 40,
                tag_commit="b" * 40,
                package_version="0.1.0",
            )

    def test_rejects_development_package_version(self):
        with self.assertRaisesRegex(ValidationFailure, "installed package version"):
            validate_release_candidate_identity(
                release_manifest(),
                tag="v0.1.0",
                head_commit="a" * 40,
                tag_commit="a" * 40,
                package_version="0.1.0.dev0",
            )

    def test_rejects_preview_manifest(self):
        with self.assertRaisesRegex(ValidationFailure, "historical release status"):
            validate_release_candidate_identity(
                MANIFEST,
                tag="v0.1.0-preview",
                head_commit=MANIFEST["source"]["commit"],
                tag_commit=MANIFEST["source"]["commit"],
                package_version="0.1.0.dev0",
            )

    def test_rejects_legacy_manifest_without_crashing(self):
        legacy = {
            "schema_id": "artifact-memory/release-manifest/v1",
            "release_id": "artifact-memory/v0.1.0",
        }
        with self.assertRaisesRegex(ValidationFailure, "requires a v2 release manifest"):
            validate_release_candidate_identity(
                legacy,
                tag="v0.1.0",
                head_commit="a" * 40,
                tag_commit="a" * 40,
                package_version="0.1.0",
            )

    def test_rejects_non_object_candidate_identity_inputs(self):
        for candidate in (None, [], "release"):
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValidationFailure) as failure:
                    validate_release_candidate_identity(
                        candidate,  # type: ignore[arg-type]
                        tag="v0.1.0",
                        head_commit="a" * 40,
                        tag_commit="a" * 40,
                        package_version="0.1.0",
                    )
                self.assertEqual(failure.exception.code, "release-candidate-manifest-not-object")

    def test_duplicate_manifest_key_fails_before_git_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "release.json"
            manifest.write_text(
                '{"schema_id":"artifact-memory/release-manifest/v2",'
                '"schema_id":"artifact-memory/release-manifest/v2"}',
                encoding="utf-8",
            )
            with patch("artifact_memory.release.subprocess.run") as git_verify:
                with self.assertRaises(ValidationFailure) as failure:
                    verify_checked_out_release_candidate(
                        manifest,
                        "v0.1.0",
                        Path(temporary),
                        asset_directory=Path(temporary),
                        owner_fingerprint=SYNTHETIC_FINGERPRINT,
                        isolated_checkout=True,
                    )
            self.assertEqual(failure.exception.code, "duplicate-key")
            git_verify.assert_not_called()

    def test_verifier_missing_or_invalid_asset_directory_is_typed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "release.json"
            manifest_path.write_text(json.dumps(release_manifest()), encoding="utf-8")
            for asset_directory, code in (
                (None, "release-candidate-asset-directory-required"),
                ("assets", "release-candidate-asset-directory-invalid"),
            ):
                with self.subTest(asset_directory=asset_directory):
                    with patch("artifact_memory.release._repository_root") as repository_root:
                        with self.assertRaises(ValidationFailure) as failure:
                            verify_checked_out_release_candidate(
                                manifest_path,
                                "v0.1.0",
                                root,
                                asset_directory=asset_directory,  # type: ignore[arg-type]
                                owner_fingerprint=SYNTHETIC_FINGERPRINT,
                                isolated_checkout=True,
                            )
                    self.assertEqual(failure.exception.code, code)
                    repository_root.assert_not_called()

    def test_verifier_cli_missing_asset_directory_returns_json_migration_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "release.json"
            manifest_path.write_text(json.dumps(release_manifest()), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                result = main(
                    [
                        "verify-release-candidate",
                        str(manifest_path),
                        "--tag",
                        "v0.1.0",
                        "--repo",
                        str(root),
                        "--owner-fingerprint",
                        SYNTHETIC_FINGERPRINT,
                        "--isolated-checkout",
                        "--json",
                    ]
                )
        self.assertEqual(result, EXIT_INVALID)
        rejection = json.loads(output.getvalue())
        self.assertEqual(rejection["outcome"], "rejected")
        self.assertEqual(
            rejection["diagnostics"][0]["code"],
            "release-candidate-asset-directory-required",
        )

    def test_verifier_scopes_git_and_reports_signing_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "release.json"
            manifest_bytes = json.dumps(release_manifest()).encode("utf-8")
            manifest_path.write_bytes(manifest_bytes)
            write_allowed_signers(root)
            write_release_assets(root)
            fingerprint = release_manifest()["signature"]["public_key_fingerprint"]
            verification = subprocess.CompletedProcess(
                args=["git", "verify-tag"],
                returncode=0,
                stdout="",
                stderr=f'Good "git" signature for release-owner@example.invalid with ED25519 key {fingerprint}\n',
            )
            with (
                patch("artifact_memory.release._repository_root", return_value=root),
                patch("artifact_memory.release.__version__", "0.1.0"),
                patch("artifact_memory.release.subprocess.run", return_value=verification) as verify_tag,
                patch(
                    "artifact_memory.release.subprocess.check_output",
                    side_effect=git_output_for(manifest_bytes),
                ) as git_read,
            ):
                result = verify_checked_out_release_candidate(
                    manifest_path,
                    "v0.1.0",
                    root,
                    asset_directory=root,
                    owner_fingerprint=SYNTHETIC_FINGERPRINT,
                    isolated_checkout=True,
                )
            self.assertEqual(result["verified_signer_fingerprint"], fingerprint)
            self.assertEqual(result["signing_key_generation"], "generation-1")
            self.assertEqual(result["tag_object_id"], "b" * 40)
            self.assertEqual(
                result["manifest_sha256"],
                f"sha-256:{hashlib.sha256(manifest_bytes).hexdigest()}",
            )
            self.assertEqual(result["manifest_binding"], "signed-annotated-tag-trailer-v1")
            self.assertEqual(result["manifest_tree_digest"], release_manifest()["source"]["tree_digest"])
            self.assertEqual(result["authority_boundary"], release_manifest()["authority_boundary"])
            self.assertTrue(result["annotated_tag_verified"])
            self.assertEqual(
                result["schema_id"],
                "artifact-memory/release-candidate-verification-receipt/v2",
            )
            validate_release_candidate_verification_receipt(result)
            self.assertEqual(verify_tag.call_args.kwargs["cwd"], root)
            self.assertEqual(verify_tag.call_args.args[0][-1], "b" * 40)
            self.assertIn("gpg.ssh.allowedSignersFile=", verify_tag.call_args.args[0][2])
            self.assertTrue(all(call.kwargs["cwd"] == root for call in git_read.call_args_list))

            tampered = dict(result)
            tampered["signing_key_generation"] = "generation-2"
            with self.assertRaises(ValidationFailure) as failure:
                validate_release_candidate_verification_receipt(tampered)
            self.assertEqual(
                failure.exception.code,
                "release-candidate-receipt-identity-mismatch",
            )

    def test_verifier_rejects_substituted_staged_asset_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = release_manifest()
            manifest_bytes = json.dumps(manifest).encode("utf-8")
            manifest_path = root / "release.json"
            manifest_path.write_bytes(manifest_bytes)
            write_allowed_signers(root)
            write_release_assets(root, manifest)
            (root / SYNTHETIC_NOTES_NAME).write_bytes(b"substituted notes\n")
            verification = subprocess.CompletedProcess(
                args=["git", "verify-tag"], returncode=0, stdout="", stderr=""
            )
            with (
                patch("artifact_memory.release._repository_root", return_value=root),
                patch("artifact_memory.release.__version__", "0.1.0"),
                patch("artifact_memory.release.subprocess.run", return_value=verification),
                patch(
                    "artifact_memory.release.subprocess.check_output",
                    side_effect=git_output_for(manifest_bytes),
                ),
            ):
                with self.assertRaises(ValidationFailure) as failure:
                    verify_checked_out_release_candidate(
                        manifest_path,
                        "v0.1.0",
                        root,
                        asset_directory=root,
                        owner_fingerprint=SYNTHETIC_FINGERPRINT,
                        isolated_checkout=True,
                    )
            self.assertEqual(
                failure.exception.code,
                "release-candidate-asset-digest-mismatch",
            )

    def test_verifier_rejects_self_consistent_asset_not_in_tagged_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = release_manifest()
            substituted_notes = b"self-consistent but not from tagged source\n"
            notes = manifest["artifacts"][1]
            notes["byte_size"] = len(substituted_notes)
            notes["sha256"] = "sha-256:" + hashlib.sha256(substituted_notes).hexdigest()
            checksum = "".join(
                f"{artifact['sha256'].removeprefix('sha-256:')}  {artifact['name']}\n"
                for artifact in manifest["artifacts"]
                if artifact["kind"] != "checksum-file"
            ).encode("ascii")
            checksum_artifact = manifest["artifacts"][2]
            checksum_artifact["byte_size"] = len(checksum)
            checksum_artifact["sha256"] = (
                "sha-256:" + hashlib.sha256(checksum).hexdigest()
            )
            manifest_bytes = json.dumps(manifest).encode("utf-8")
            manifest_path = root / "release.json"
            manifest_path.write_bytes(manifest_bytes)
            write_allowed_signers(root)
            (root / SYNTHETIC_ARCHIVE_NAME).write_bytes(SYNTHETIC_ARCHIVE)
            (root / SYNTHETIC_NOTES_NAME).write_bytes(substituted_notes)
            (root / "SHA256SUMS").write_bytes(checksum)
            verification = subprocess.CompletedProcess(
                args=["git", "verify-tag"], returncode=0, stdout="", stderr=""
            )
            with (
                patch("artifact_memory.release._repository_root", return_value=root),
                patch("artifact_memory.release.__version__", "0.1.0"),
                patch("artifact_memory.release.subprocess.run", return_value=verification),
                patch(
                    "artifact_memory.release.subprocess.check_output",
                    side_effect=git_output_for(manifest_bytes),
                ),
            ):
                with self.assertRaises(ValidationFailure) as failure:
                    verify_checked_out_release_candidate(
                        manifest_path,
                        "v0.1.0",
                        root,
                        asset_directory=root,
                        owner_fingerprint=SYNTHETIC_FINGERPRINT,
                        isolated_checkout=True,
                    )
            self.assertEqual(
                failure.exception.code,
                "release-candidate-asset-replay-mismatch",
            )

    def test_verifier_rejects_assets_changed_during_streamed_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = release_manifest()
            manifest_bytes = json.dumps(manifest).encode("utf-8")
            manifest_path = root / "release.json"
            manifest_path.write_bytes(manifest_bytes)
            write_allowed_signers(root)
            write_release_assets(root, manifest)

            def replay_and_mutate(*args, **kwargs):
                synthetic_git_replay(*args, **kwargs)
                if args[3] == SYNTHETIC_ARCHIVE_NAME:
                    (root / SYNTHETIC_ARCHIVE_NAME).write_bytes(b"changed after replay\n")

            verification = subprocess.CompletedProcess(
                args=["git", "verify-tag"], returncode=0, stdout="", stderr=""
            )
            with (
                patch("artifact_memory.release._repository_root", return_value=root),
                patch("artifact_memory.release.__version__", "0.1.0"),
                patch("artifact_memory.release.subprocess.run", return_value=verification),
                patch(
                    "artifact_memory.release.subprocess.check_output",
                    side_effect=git_output_for(manifest_bytes),
                ),
                patch(
                    "artifact_memory.release._replay_git_output_against_asset",
                    side_effect=replay_and_mutate,
                ),
            ):
                with self.assertRaises(ValidationFailure) as failure:
                    verify_checked_out_release_candidate(
                        manifest_path,
                        "v0.1.0",
                        root,
                        asset_directory=root,
                        owner_fingerprint=SYNTHETIC_FINGERPRINT,
                        isolated_checkout=True,
                    )
            self.assertEqual(failure.exception.code, "release-candidate-assets-changed")

    def test_historical_release_with_legacy_provenance_is_explicitly_unsupported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = historical_release_manifest()
            manifest["artifacts"][0]["provenance"] = "historical free-form provenance"
            manifest_bytes = json.dumps(manifest).encode("utf-8")
            manifest_path = root / "release.json"
            manifest_path.write_bytes(manifest_bytes)
            write_allowed_signers(root)
            write_release_assets(root, manifest)
            verification = subprocess.CompletedProcess(
                args=["git", "verify-tag"], returncode=0, stdout="", stderr=""
            )
            with (
                patch("artifact_memory.release._repository_root", return_value=root),
                patch("artifact_memory.release.__version__", "0.1.0"),
                patch("artifact_memory.release.subprocess.run", return_value=verification),
                patch(
                    "artifact_memory.release.subprocess.check_output",
                    side_effect=git_output_for(manifest_bytes),
                ),
            ):
                with self.assertRaises(ValidationFailure) as failure:
                    verify_checked_out_release_candidate(
                        manifest_path,
                        "v0.1.0",
                        root,
                        asset_directory=root,
                        owner_fingerprint=SYNTHETIC_FINGERPRINT,
                        isolated_checkout=True,
                    )
            self.assertEqual(
                failure.exception.code,
                "release-candidate-historical-asset-replay-unsupported",
            )

    def test_verifier_rejects_allowed_signers_without_expected_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "release.json"
            manifest_bytes = json.dumps(release_manifest()).encode("utf-8")
            manifest_path.write_bytes(manifest_bytes)
            write_allowed_signers(
                root,
                public_key=base64.b64encode(b"different-public-key").decode("ascii"),
            )
            verification = subprocess.CompletedProcess(
                args=["git", "verify-tag"],
                returncode=0,
                stdout="",
                stderr=(
                    'Good "git" signature for release-owner@example.invalid '
                    "with ED25519 key SHA256:ZZZZZZZZZZZZZZZZZZZZZZZZ\n"
                ),
            )
            with (
                patch("artifact_memory.release._repository_root", return_value=root),
                patch("artifact_memory.release.__version__", "0.1.0"),
                patch("artifact_memory.release.subprocess.run", return_value=verification),
                patch(
                    "artifact_memory.release.subprocess.check_output",
                    side_effect=git_output_for(manifest_bytes),
                ),
            ):
                with self.assertRaises(ValidationFailure) as failure:
                    verify_checked_out_release_candidate(
                        manifest_path,
                        "v0.1.0",
                        root,
                        asset_directory=root,
                        owner_fingerprint=SYNTHETIC_FINGERPRINT,
                        isolated_checkout=True,
                    )
            self.assertEqual(failure.exception.code, "release-candidate-expected-signer-unavailable")

    def test_verifier_rejects_signer_policy_change_during_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_bytes = json.dumps(release_manifest()).encode("utf-8")
            manifest_path = root / "release.json"
            manifest_path.write_bytes(manifest_bytes)
            allowed_signers = write_allowed_signers(root)
            write_release_assets(root)

            def mutate_policy(*args, **kwargs):
                allowed_signers.write_text(
                    allowed_signers.read_text(encoding="utf-8") + "# changed\n",
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

            with (
                patch("artifact_memory.release._repository_root", return_value=root),
                patch("artifact_memory.release.__version__", "0.1.0"),
                patch("artifact_memory.release.subprocess.run", side_effect=mutate_policy),
                patch(
                    "artifact_memory.release.subprocess.check_output",
                    side_effect=git_output_for(manifest_bytes),
                ),
            ):
                with self.assertRaises(ValidationFailure) as failure:
                    verify_checked_out_release_candidate(
                        manifest_path,
                        "v0.1.0",
                        root,
                        asset_directory=root,
                        owner_fingerprint=SYNTHETIC_FINGERPRINT,
                        isolated_checkout=True,
                    )
            self.assertEqual(
                failure.exception.code,
                "release-candidate-signer-policy-changed",
            )

    def test_verifier_does_not_parse_human_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = release_manifest()
            manifest_path = root / "release.json"
            manifest_bytes = json.dumps(manifest).encode("utf-8")
            manifest_path.write_bytes(manifest_bytes)
            write_allowed_signers(root)
            write_release_assets(root, manifest)
            fingerprint = manifest["signature"]["public_key_fingerprint"]
            verification = subprocess.CompletedProcess(
                args=["git", "verify-tag"],
                returncode=0,
                stdout="",
                stderr=f"unrelated diagnostic mentions {fingerprint}\n",
            )
            with (
                patch("artifact_memory.release._repository_root", return_value=root),
                patch("artifact_memory.release.__version__", "0.1.0"),
                patch("artifact_memory.release.subprocess.run", return_value=verification),
                patch(
                    "artifact_memory.release.subprocess.check_output",
                    side_effect=git_output_for(manifest_bytes),
                ),
            ):
                result = verify_checked_out_release_candidate(
                    manifest_path,
                    "v0.1.0",
                    root,
                    asset_directory=root,
                    owner_fingerprint=SYNTHETIC_FINGERPRINT,
                    isolated_checkout=True,
                )
            self.assertEqual(result["verified_signer_fingerprint"], fingerprint)

    def test_verifier_rejects_manifest_digest_not_in_signed_tag(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_bytes = json.dumps(release_manifest()).encode("utf-8")
            manifest_path = root / "release.json"
            manifest_path.write_bytes(manifest_bytes)
            write_allowed_signers(root)
            fingerprint = release_manifest()["signature"]["public_key_fingerprint"]
            verification = subprocess.CompletedProcess(
                args=["git", "verify-tag"], returncode=0, stdout="",
                stderr=f'Good "git" signature for owner with ED25519 key {fingerprint}\n',
            )
            other_manifest_bytes = manifest_bytes.replace(b'"generation-1"', b'"generation-2"')
            with (
                patch("artifact_memory.release._repository_root", return_value=root),
                patch("artifact_memory.release.subprocess.run", return_value=verification),
                patch(
                    "artifact_memory.release.subprocess.check_output",
                    side_effect=git_output_for(other_manifest_bytes),
                ),
            ):
                with self.assertRaises(ValidationFailure) as failure:
                    verify_checked_out_release_candidate(
                        manifest_path,
                        "v0.1.0",
                        root,
                        asset_directory=root,
                        owner_fingerprint=SYNTHETIC_FINGERPRINT,
                        isolated_checkout=True,
                    )
            self.assertEqual(failure.exception.code, "release-candidate-manifest-binding-mismatch")

    def test_verifier_rejects_wrong_tag_tree_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = release_manifest()
            manifest["source"]["tree_digest"] = "sha-256:" + "0" * 64
            manifest_bytes = json.dumps(manifest).encode("utf-8")
            manifest_path = root / "release.json"
            manifest_path.write_bytes(manifest_bytes)
            write_allowed_signers(root)
            fingerprint = manifest["signature"]["public_key_fingerprint"]
            verification = subprocess.CompletedProcess(
                args=["git", "verify-tag"], returncode=0, stdout="",
                stderr=f'Good "git" signature for owner with ED25519 key {fingerprint}\n',
            )
            with (
                patch("artifact_memory.release._repository_root", return_value=root),
                patch("artifact_memory.release.subprocess.run", return_value=verification),
                patch(
                    "artifact_memory.release.subprocess.check_output",
                    side_effect=git_output_for(manifest_bytes),
                ),
            ):
                with self.assertRaises(ValidationFailure) as failure:
                    verify_checked_out_release_candidate(
                        manifest_path,
                        "v0.1.0",
                        root,
                        asset_directory=root,
                        owner_fingerprint=SYNTHETIC_FINGERPRINT,
                        isolated_checkout=True,
                    )
            self.assertEqual(failure.exception.code, "release-candidate-tree-digest-mismatch")

    def test_verifier_rejects_unsupported_git_object_format_explicitly(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = release_manifest()
            manifest["source"]["commit"] = "a" * 64
            manifest_path = root / "release.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with (
                patch("artifact_memory.release._repository_root", return_value=root),
                patch(
                    "artifact_memory.release.subprocess.check_output",
                    return_value="sha256\n",
                ),
            ):
                with self.assertRaises(ValidationFailure) as failure:
                    verify_checked_out_release_candidate(
                        manifest_path,
                        "v0.1.0",
                        root,
                        asset_directory=root,
                        owner_fingerprint=SYNTHETIC_FINGERPRINT,
                        isolated_checkout=True,
                    )
            self.assertEqual(failure.exception.code, "release-candidate-object-format-unsupported")

    def test_verifier_rejects_manifest_key_different_from_owner_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "release.json"
            manifest_path.write_text(json.dumps(release_manifest()), encoding="utf-8")
            other_fingerprint = _ssh_ed25519_fingerprint(
                base64.b64encode(b"independent-other-owner-key").decode("ascii")
            )
            with (
                patch("artifact_memory.release._repository_root", return_value=root),
                patch(
                    "artifact_memory.release.subprocess.check_output",
                    return_value="sha1\n",
                ),
            ):
                with self.assertRaises(ValidationFailure) as failure:
                    verify_checked_out_release_candidate(
                        manifest_path,
                        "v0.1.0",
                        root,
                        asset_directory=root,
                        owner_fingerprint=other_fingerprint,
                        isolated_checkout=True,
                    )
            self.assertEqual(
                failure.exception.code,
                "release-candidate-owner-fingerprint-mismatch",
            )

    def test_verifier_rejects_noncanonical_manifest_fingerprint_precisely(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = release_manifest()
            manifest["signature"]["public_key_fingerprint"] = "SHA256:" + "A" * 20 + "=="
            manifest_path = root / "release.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with (
                patch("artifact_memory.release._repository_root", return_value=root),
                patch(
                    "artifact_memory.release.subprocess.check_output",
                    return_value="sha1\n",
                ),
            ):
                with self.assertRaises(ValidationFailure) as failure:
                    verify_checked_out_release_candidate(
                        manifest_path,
                        "v0.1.0",
                        root,
                        asset_directory=root,
                        owner_fingerprint=SYNTHETIC_FINGERPRINT,
                        isolated_checkout=True,
                    )
            self.assertEqual(
                failure.exception.code,
                "release-candidate-owner-fingerprint-invalid",
            )

    def test_verifier_requires_isolated_checkout_assertion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "release.json"
            manifest_path.write_text(json.dumps(release_manifest()), encoding="utf-8")
            with (
                patch("artifact_memory.release._repository_root", return_value=root),
                patch(
                    "artifact_memory.release.subprocess.check_output",
                    return_value="sha1\n",
                ),
            ):
                with self.assertRaises(ValidationFailure) as failure:
                    verify_checked_out_release_candidate(
                        manifest_path,
                        "v0.1.0",
                        root,
                        asset_directory=root,
                        owner_fingerprint=SYNTHETIC_FINGERPRINT,
                        isolated_checkout=False,
                    )
            self.assertEqual(failure.exception.code, "release-candidate-isolation-required")

    def test_verifier_rejects_non_string_owner_fingerprint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "release.json"
            manifest_path.write_text(json.dumps(release_manifest()), encoding="utf-8")
            with (
                patch("artifact_memory.release._repository_root", return_value=root),
                patch(
                    "artifact_memory.release.subprocess.check_output",
                    return_value="sha1\n",
                ),
            ):
                with self.assertRaises(ValidationFailure) as failure:
                    verify_checked_out_release_candidate(
                        manifest_path,
                        "v0.1.0",
                        root,
                        asset_directory=root,
                        owner_fingerprint=None,  # type: ignore[arg-type]
                        isolated_checkout=True,
                    )
            self.assertEqual(
                failure.exception.code,
                "release-candidate-owner-fingerprint-invalid",
            )

    def test_receipt_rejects_noncanonical_signer_fingerprint(self):
        fixture = Path(__file__).resolve().parents[1] / (
            "fixtures/synthetic/release/v0-release-candidate-verification-receipt.json"
        )
        receipt = json.loads(fixture.read_text(encoding="utf-8"))
        receipt["verified_signer_fingerprint"] = "SHA256:" + "A" * 20
        with self.assertRaises(ValidationFailure) as failure:
            validate_release_candidate_verification_receipt(receipt)
        self.assertEqual(failure.exception.code, "constraint-failed")

    def test_receipt_cli_rejects_noncanonical_surrogate_without_traceback(self):
        fixture = Path(__file__).resolve().parents[1] / (
            "fixtures/synthetic/release/v0-release-candidate-verification-receipt.json"
        )
        receipt = json.loads(fixture.read_text(encoding="utf-8"))
        receipt["limitations"][0] = "\ud800"
        with tempfile.TemporaryDirectory() as temporary:
            receipt_path = Path(temporary) / "receipt.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                result = main(
                    ["validate-release-candidate-receipt", str(receipt_path), "--json"]
                )
        self.assertEqual(result, EXIT_INVALID)
        rendered = json.loads(output.getvalue())
        self.assertEqual(rendered["outcome"], "rejected")
        self.assertEqual(
            rendered["diagnostics"][0]["code"],
            "release-candidate-receipt-noncanonical",
        )

    def test_verifier_rejects_tag_ref_change_during_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_bytes = json.dumps(release_manifest()).encode("utf-8")
            manifest_path = root / "release.json"
            manifest_path.write_bytes(manifest_bytes)
            write_allowed_signers(root)
            write_release_assets(root)
            base_output = git_output_for(manifest_bytes)
            tag_reads = 0

            def changing_output(args, **kwargs):
                nonlocal tag_reads
                if tuple(args[1:]) == ("rev-parse", "refs/tags/v0.1.0"):
                    tag_reads += 1
                    value = ("b" if tag_reads == 1 else "c") * 40 + "\n"
                    return value if kwargs.get("text") else value.encode("utf-8")
                return base_output(args, **kwargs)

            verification = subprocess.CompletedProcess(
                args=["git", "verify-tag"], returncode=0, stdout="", stderr=""
            )
            with (
                patch("artifact_memory.release._repository_root", return_value=root),
                patch("artifact_memory.release.__version__", "0.1.0"),
                patch("artifact_memory.release.subprocess.run", return_value=verification),
                patch(
                    "artifact_memory.release.subprocess.check_output",
                    side_effect=changing_output,
                ),
            ):
                with self.assertRaises(ValidationFailure) as failure:
                    verify_checked_out_release_candidate(
                        manifest_path,
                        "v0.1.0",
                        root,
                        asset_directory=root,
                        owner_fingerprint=SYNTHETIC_FINGERPRINT,
                        isolated_checkout=True,
                    )
            self.assertEqual(failure.exception.code, "release-candidate-tag-ref-changed")

    def test_verifier_rejects_head_becoming_attached_during_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_bytes = json.dumps(release_manifest()).encode("utf-8")
            manifest_path = root / "release.json"
            manifest_path.write_bytes(manifest_bytes)
            write_allowed_signers(root)
            write_release_assets(root)
            base_output = git_output_for(manifest_bytes)
            symbolic_reads = 0

            def attaching_output(args, **kwargs):
                nonlocal symbolic_reads
                if tuple(args[1:]) == ("rev-parse", "--symbolic-full-name", "HEAD"):
                    symbolic_reads += 1
                    value = "HEAD\n" if symbolic_reads == 1 else "refs/heads/main\n"
                    return value if kwargs.get("text") else value.encode("utf-8")
                return base_output(args, **kwargs)

            verification = subprocess.CompletedProcess(
                args=["git", "verify-tag"], returncode=0, stdout="", stderr=""
            )
            with (
                patch("artifact_memory.release._repository_root", return_value=root),
                patch("artifact_memory.release.__version__", "0.1.0"),
                patch("artifact_memory.release.subprocess.run", return_value=verification),
                patch(
                    "artifact_memory.release.subprocess.check_output",
                    side_effect=attaching_output,
                ),
            ):
                with self.assertRaises(ValidationFailure) as failure:
                    verify_checked_out_release_candidate(
                        manifest_path,
                        "v0.1.0",
                        root,
                        asset_directory=root,
                        owner_fingerprint=SYNTHETIC_FINGERPRINT,
                        isolated_checkout=True,
                    )
            self.assertEqual(failure.exception.code, "release-candidate-head-not-detached")

    @unittest.skipUnless(shutil.which("git") and shutil.which("ssh-keygen"), "Git SSH tools required")
    def test_real_git_ssh_tag_verification_contract(self):
        self._stop_replay_patcher()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "checkout"
            subprocess.run(["git", "init", "-q", str(repository)], check=True)
            subprocess.run(
                ["git", "config", "user.name", "Synthetic Release Owner"],
                cwd=repository,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "release-owner@example.invalid"],
                cwd=repository,
                check=True,
            )
            tracked = repository / "synthetic.txt"
            tracked.write_text("synthetic release content\n", encoding="utf-8")
            notes_source = repository / SYNTHETIC_NOTES_SOURCE
            notes_source.parent.mkdir(parents=True)
            notes_source.write_bytes(SYNTHETIC_NOTES)
            subprocess.run(["git", "add", "."], cwd=repository, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "synthetic"], cwd=repository, check=True)
            commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repository, text=True
            ).strip()
            tree_listing = subprocess.check_output(
                ["git", "ls-tree", "-r", "--full-tree", commit], cwd=repository
            )

            key_path = root / "synthetic_release_key"
            subprocess.run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key_path)],
                check=True,
            )
            public_key_fields = key_path.with_suffix(".pub").read_text(encoding="utf-8").split()
            public_key = public_key_fields[1]
            fingerprint = _ssh_ed25519_fingerprint(public_key)
            allowed_signers = root / "allowed_signers"
            allowed_signers.write_text(
                f"artifact-memory-release ssh-ed25519 {public_key} synthetic-release-key\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "config", "gpg.format", "ssh"], cwd=repository, check=True)
            subprocess.run(
                ["git", "config", "user.signingkey", str(key_path)], cwd=repository, check=True
            )
            subprocess.run(
                ["git", "config", "gpg.ssh.allowedSignersFile", str(allowed_signers)],
                cwd=repository,
                check=True,
            )

            manifest = release_manifest()
            manifest["source"]["commit"] = commit
            manifest["source"]["tree_digest"] = (
                f"sha-256:{hashlib.sha256(tree_listing).hexdigest()}"
            )
            manifest["signature"]["public_key_fingerprint"] = fingerprint
            archive_bytes = subprocess.check_output(
                [
                    "git",
                    "archive",
                    "--format=tar",
                    "--prefix=artifact-memory-0.1.0/",
                    commit,
                ],
                cwd=repository,
            )
            archive_digest = hashlib.sha256(archive_bytes).hexdigest()
            notes_digest = hashlib.sha256(SYNTHETIC_NOTES).hexdigest()
            checksum_bytes = (
                f"{archive_digest}  {SYNTHETIC_ARCHIVE_NAME}\n"
                f"{notes_digest}  {SYNTHETIC_NOTES_NAME}\n"
            ).encode("ascii")
            manifest["artifacts"][0].update(
                byte_size=len(archive_bytes),
                sha256="sha-256:" + archive_digest,
                provenance=(
                    "git archive --format=tar --prefix=artifact-memory-0.1.0/ "
                    + commit
                ),
            )
            manifest["artifacts"][1].update(
                byte_size=len(SYNTHETIC_NOTES),
                sha256="sha-256:" + notes_digest,
                provenance=f"exact bytes from {commit}:{SYNTHETIC_NOTES_SOURCE}",
            )
            manifest["artifacts"][2].update(
                byte_size=len(checksum_bytes),
                sha256="sha-256:" + hashlib.sha256(checksum_bytes).hexdigest(),
            )
            (root / SYNTHETIC_ARCHIVE_NAME).write_bytes(archive_bytes)
            (root / SYNTHETIC_NOTES_NAME).write_bytes(SYNTHETIC_NOTES)
            (root / "SHA256SUMS").write_bytes(checksum_bytes)
            manifest_bytes = json.dumps(manifest).encode("utf-8")
            manifest_path = root / "release.json"
            manifest_path.write_bytes(manifest_bytes)
            manifest_digest = f"sha-256:{hashlib.sha256(manifest_bytes).hexdigest()}"
            subprocess.run(
                [
                    "git",
                    "tag",
                    "-s",
                    "-m",
                    "Synthetic release",
                    "-m",
                    f"Artifact-Memory-Manifest-SHA256: {manifest_digest}",
                    "v0.1.0",
                ],
                cwd=repository,
                check=True,
            )
            subprocess.run(
                ["git", "checkout", "-q", "--detach", "v0.1.0"],
                cwd=repository,
                check=True,
            )
            with patch("artifact_memory.release.__version__", "0.1.0"):
                receipt = verify_checked_out_release_candidate(
                    manifest_path,
                    "v0.1.0",
                    repository,
                    asset_directory=root,
                    owner_fingerprint=fingerprint,
                    isolated_checkout=True,
                )
            self.assertEqual(receipt["verified_signer_fingerprint"], fingerprint)
            self.assertEqual(receipt["manifest_sha256"], manifest_digest)
            validate_release_candidate_verification_receipt(receipt)


if __name__ == "__main__":
    unittest.main()
