import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from artifact_memory.release import validate_release_candidate_identity, verify_checked_out_release_candidate
from artifact_memory.validator import ValidationFailure


MANIFEST = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures/synthetic/release/v0-preview-manifest.v2.json").read_text(
        encoding="utf-8"
    )
)


def release_manifest() -> dict:
    manifest = copy.deepcopy(MANIFEST)
    commit = "a" * 40
    manifest["release_id"] = "artifact-memory/v0.1.0"
    manifest["status"] = "release"
    manifest["source"]["commit"] = commit
    manifest["surfaces"]["reference_cli"] = {"package_version": "0.1.0", "stability": "stable"}
    manifest["signature"] = {
        "state": "owner-signed",
        "tag": "v0.1.0",
        "algorithm": "ssh-ed25519",
        "public_key_fingerprint": "SHA256:abcdefghijklmnopqrstuvwx",
        "key_generation": "generation-1",
        "owner_signed_annotated_tag": True,
    }
    return manifest


class ReleaseCandidateIdentityTests(unittest.TestCase):
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
            manifest_path.write_text(json.dumps(release_manifest()), encoding="utf-8")
            fingerprint = release_manifest()["signature"]["public_key_fingerprint"]
            verification = subprocess.CompletedProcess(
                args=["git", "verify-tag"],
                returncode=0,
                stdout="",
                stderr=f'Good "git" signature with ED25519 key {fingerprint}\n',
            )
            with (
                patch("artifact_memory.release._repository_root", return_value=root),
                patch("artifact_memory.release.__version__", "0.1.0"),
                patch("artifact_memory.release.subprocess.run", return_value=verification) as verify_tag,
                patch(
                    "artifact_memory.release.subprocess.check_output",
                    side_effect=["a" * 40 + "\n", "a" * 40 + "\n", "tag\n"],
                ) as git_read,
            ):
                result = verify_checked_out_release_candidate(manifest_path, "v0.1.0", root)
            self.assertEqual(result["verified_signer_fingerprint"], fingerprint)
            self.assertEqual(result["signing_key_generation"], "generation-1")
            self.assertTrue(result["annotated_tag_verified"])
            self.assertEqual(verify_tag.call_args.kwargs["cwd"], root)
            self.assertTrue(all(call.kwargs["cwd"] == root for call in git_read.call_args_list))

    def test_verifier_rejects_unexpected_signer_fingerprint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "release.json"
            manifest_path.write_text(json.dumps(release_manifest()), encoding="utf-8")
            verification = subprocess.CompletedProcess(
                args=["git", "verify-tag"],
                returncode=0,
                stdout="",
                stderr='Good "git" signature with ED25519 key SHA256:ZZZZZZZZZZZZZZZZZZZZZZZZ\n',
            )
            with (
                patch("artifact_memory.release._repository_root", return_value=root),
                patch("artifact_memory.release.subprocess.run", return_value=verification),
                patch(
                    "artifact_memory.release.subprocess.check_output",
                    side_effect=["a" * 40 + "\n", "a" * 40 + "\n", "tag\n"],
                ),
            ):
                with self.assertRaises(ValidationFailure) as failure:
                    verify_checked_out_release_candidate(manifest_path, "v0.1.0", root)
            self.assertEqual(failure.exception.code, "release-candidate-signer-mismatch")


if __name__ == "__main__":
    unittest.main()
