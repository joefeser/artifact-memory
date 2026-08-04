import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from artifact_memory.release import (
    _signed_manifest_digest,
    _verified_ssh_fingerprint,
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


def release_manifest() -> dict:
    manifest = copy.deepcopy(MANIFEST)
    commit = "a" * 40
    manifest["release_id"] = "artifact-memory/v0.1.0"
    manifest["status"] = "release"
    manifest["source"]["commit"] = commit
    manifest["source"]["tree_digest"] = f"sha-256:{hashlib.sha256(TREE_LISTING).hexdigest()}"
    manifest["surfaces"]["reference_cli"] = {"package_version": "0.1.0", "stability": "stable"}
    manifest["signature"] = {
        "state": "owner-signed",
        "tag": "v0.1.0",
        "algorithm": "ssh-ed25519",
        "public_key_fingerprint": "SHA256:abcdefghijklmnopqrstuvwx",
        "key_generation": "generation-1",
        "owner_signed_annotated_tag": True,
    }
    manifest["limitations"] = [
        "verification proves only the identities and cryptographic bindings represented in this receipt",
        "publication, visibility, deployment, and release authority remain absent",
    ]
    return manifest


def git_output_for(manifest_bytes: bytes):
    manifest_digest = f"sha-256:{hashlib.sha256(manifest_bytes).hexdigest()}"
    tag_object = (
        "object " + "a" * 40 + "\n"
        "type commit\n"
        "tag v0.1.0\n"
        "tagger Release Owner <owner@example.invalid> 0 +0000\n\n"
        "Artifact Memory v0.1.0\n\n"
        f"Artifact-Memory-Manifest-SHA256: {manifest_digest}\n"
        "-----BEGIN SSH SIGNATURE-----\nsynthetic\n-----END SSH SIGNATURE-----\n"
    ).encode("utf-8")

    def output(args, **kwargs):
        command = tuple(args[1:])
        values = {
            ("rev-parse", "HEAD"): "a" * 40 + "\n",
            ("rev-parse", "refs/tags/v0.1.0^{commit}"): "a" * 40 + "\n",
            ("rev-parse", "refs/tags/v0.1.0"): "b" * 40 + "\n",
            ("cat-file", "-t", "refs/tags/v0.1.0"): "tag\n",
            ("cat-file", "tag", "refs/tags/v0.1.0"): tag_object,
            ("ls-tree", "-r", "--full-tree", "refs/tags/v0.1.0^{commit}"): TREE_LISTING,
        }
        value = values[command]
        if kwargs.get("text") and isinstance(value, bytes):
            return value.decode("utf-8")
        if not kwargs.get("text") and isinstance(value, str):
            return value.encode("utf-8")
        return value

    return output


class ReleaseCandidateIdentityTests(unittest.TestCase):
    def test_supported_c_locale_ssh_verification_record(self):
        fingerprint = "SHA256:abcdefghijklmnopqrstuvwx"
        recorded_output = (
            'Good "git" signature for release-owner@example.invalid '
            f"with ED25519 key {fingerprint}\n"
        )
        self.assertEqual(_verified_ssh_fingerprint(recorded_output), fingerprint)

    def test_rejects_ambiguous_ssh_verification_records(self):
        line = (
            'Good "git" signature for release-owner@example.invalid '
            "with ED25519 key SHA256:abcdefghijklmnopqrstuvwx\n"
        )
        with self.assertRaises(ValidationFailure) as failure:
            _verified_ssh_fingerprint(line + line)
        self.assertEqual(failure.exception.code, "release-candidate-signer-evidence-invalid")

    def test_rejects_ambiguous_signed_manifest_trailers(self):
        trailer = "Artifact-Memory-Manifest-SHA256: sha-256:" + "0" * 64 + "\n"
        with self.assertRaises(ValidationFailure) as failure:
            _signed_manifest_digest((trailer + trailer).encode("utf-8"))
        self.assertEqual(failure.exception.code, "release-candidate-manifest-binding-invalid")

    def test_checked_synthetic_verification_receipt_and_rendering(self):
        fixture_root = Path(__file__).resolve().parents[1] / "fixtures/synthetic/release"
        expected_receipt = json.loads(
            (fixture_root / "v0-release-candidate-verification-receipt.json").read_text(
                encoding="utf-8"
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_bytes = json.dumps(release_manifest()).encode("utf-8")
            manifest_path = root / "release.json"
            manifest_path.write_bytes(manifest_bytes)
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
                receipt = verify_checked_out_release_candidate(manifest_path, "v0.1.0", root)
        self.assertEqual(receipt, expected_receipt)
        validate_release_candidate_verification_receipt(receipt)
        self.assertEqual(
            render_release_candidate_verification_receipt(receipt),
            (fixture_root / "v0-release-candidate-verification-receipt.md").read_text(encoding="utf-8"),
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
        with self.assertRaisesRegex(ValidationFailure, "release status"):
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
                    verify_checked_out_release_candidate(manifest, "v0.1.0", Path(temporary))
            self.assertEqual(failure.exception.code, "duplicate-key")
            git_verify.assert_not_called()

    def test_verifier_scopes_git_and_reports_signing_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "release.json"
            manifest_bytes = json.dumps(release_manifest()).encode("utf-8")
            manifest_path.write_bytes(manifest_bytes)
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
                result = verify_checked_out_release_candidate(manifest_path, "v0.1.0", root)
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
                "artifact-memory/release-candidate-verification-receipt/v1",
            )
            validate_release_candidate_verification_receipt(result)
            self.assertEqual(verify_tag.call_args.kwargs["cwd"], root)
            self.assertEqual(verify_tag.call_args.args[0][-1], "refs/tags/v0.1.0")
            self.assertEqual(verify_tag.call_args.kwargs["env"]["LC_ALL"], "C")
            self.assertTrue(all(call.kwargs["cwd"] == root for call in git_read.call_args_list))

            tampered = dict(result)
            tampered["signing_key_generation"] = "generation-2"
            with self.assertRaises(ValidationFailure) as failure:
                validate_release_candidate_verification_receipt(tampered)
            self.assertEqual(
                failure.exception.code,
                "release-candidate-receipt-identity-mismatch",
            )

    def test_verifier_rejects_unexpected_signer_fingerprint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "release.json"
            manifest_bytes = json.dumps(release_manifest()).encode("utf-8")
            manifest_path.write_bytes(manifest_bytes)
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
                patch("artifact_memory.release.subprocess.run", return_value=verification),
                patch(
                    "artifact_memory.release.subprocess.check_output",
                    side_effect=git_output_for(manifest_bytes),
                ),
            ):
                with self.assertRaises(ValidationFailure) as failure:
                    verify_checked_out_release_candidate(manifest_path, "v0.1.0", root)
            self.assertEqual(failure.exception.code, "release-candidate-signer-mismatch")

    def test_verifier_rejects_incidental_expected_fingerprint_token(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = release_manifest()
            manifest_path = root / "release.json"
            manifest_bytes = json.dumps(manifest).encode("utf-8")
            manifest_path.write_bytes(manifest_bytes)
            fingerprint = manifest["signature"]["public_key_fingerprint"]
            verification = subprocess.CompletedProcess(
                args=["git", "verify-tag"],
                returncode=0,
                stdout="",
                stderr=f"unrelated diagnostic mentions {fingerprint}\n",
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
                    verify_checked_out_release_candidate(manifest_path, "v0.1.0", root)
            self.assertEqual(
                failure.exception.code,
                "release-candidate-signer-evidence-invalid",
            )

    def test_verifier_rejects_manifest_digest_not_in_signed_tag(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_bytes = json.dumps(release_manifest()).encode("utf-8")
            manifest_path = root / "release.json"
            manifest_path.write_bytes(manifest_bytes)
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
                    verify_checked_out_release_candidate(manifest_path, "v0.1.0", root)
            self.assertEqual(failure.exception.code, "release-candidate-manifest-binding-mismatch")

    def test_verifier_rejects_wrong_tag_tree_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = release_manifest()
            manifest["source"]["tree_digest"] = "sha-256:" + "0" * 64
            manifest_bytes = json.dumps(manifest).encode("utf-8")
            manifest_path = root / "release.json"
            manifest_path.write_bytes(manifest_bytes)
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
                    verify_checked_out_release_candidate(manifest_path, "v0.1.0", root)
            self.assertEqual(failure.exception.code, "release-candidate-tree-digest-mismatch")


if __name__ == "__main__":
    unittest.main()
