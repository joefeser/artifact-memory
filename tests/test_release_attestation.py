import hashlib
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from artifact_memory.canonical import receipt_with_digest
from artifact_memory.release_attestation import (
    ReleaseAttestationFailure,
    verify_release_attestation_subjects,
    write_subject_checksums,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/synthetic/release"


def _digest(data: bytes) -> str:
    return "sha-256:" + hashlib.sha256(data).hexdigest()


class ReleaseAttestationTests(unittest.TestCase):
    def _fixture(self, root: Path):
        reproduced = root / "reproduced"
        published = root / "published"
        reproduced.mkdir()
        published.mkdir()
        manifest = json.loads(
            (FIXTURE / "v0-pending-candidate-manifest.v2.json").read_text()
        )
        manifest_bytes = (
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        ).encode()
        files = {
            "release-manifest.json": manifest_bytes,
            "release-candidate-preparation-receipt.json": b"synthetic preparation receipt\n",
            "release-candidate-preparation-receipt.md": b"# Synthetic preparation\n",
        }
        for artifact in manifest["artifacts"]:
            files[artifact["name"]] = f"synthetic {artifact['name']}\n".encode()
        for name, data in files.items():
            (reproduced / name).write_bytes(data)
            (published / name).write_bytes(data)

        template = json.loads(
            (FIXTURE / "v0-release-candidate-verification-receipt.v2.json").read_text()
        )
        body = {
            key: value
            for key, value in template.items()
            if key not in {"schema_id", "receipt_id"}
        }
        source_commit = manifest["source"]["commit"]
        body.update(
            {
                "release_id": manifest["release_id"],
                "tag": manifest["signature"]["tag"],
                "tag_commit": source_commit,
                "head_commit": source_commit,
                "manifest_source_commit": source_commit,
                "manifest_sha256": _digest(manifest_bytes),
                "manifest_tree_digest": manifest["source"]["tree_digest"],
                "verified_asset_count": len(manifest["artifacts"]),
                "checksum_manifest_sha256": _digest(
                    files[manifest["checksum_manifest"]["artifact_name"]]
                ),
            }
        )
        receipt = receipt_with_digest(
            "artifact-memory/release-candidate-verification-receipt/v2",
            "release-candidate-verification-receipt://",
            body,
        )
        receipt_bytes = (json.dumps(receipt, sort_keys=True) + "\n").encode()
        generated = root / "generated-verification.json"
        generated.write_bytes(receipt_bytes)
        (published / "release-candidate-verification-receipt.json").write_bytes(
            receipt_bytes
        )
        return reproduced, published, generated

    def test_exact_replay_emits_every_published_subject(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reproduced, published, generated = self._fixture(root)
            report = verify_release_attestation_subjects(
                reproduced, published, generated, tag="v0.1.0"
            )
            names = [item["name"] for item in report["subjects"]]
            self.assertEqual(report["outcome"], "pass")
            self.assertEqual(report["subject_count"], len(list(published.iterdir())))
            self.assertEqual(names, sorted(names))
            self.assertIn("release-manifest.json", names)
            self.assertIn("release-candidate-verification-receipt.json", names)
            output = root / "subjects.sha256"
            write_subject_checksums(report, output)
            self.assertEqual(len(output.read_text().splitlines()), len(names))
            with self.assertRaisesRegex(
                ReleaseAttestationFailure,
                "could not be created exclusively",
            ):
                write_subject_checksums(report, output)

    def test_changed_reproduced_asset_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reproduced, published, generated = self._fixture(root)
            target = next(
                path for path in published.iterdir() if path.name.endswith(".tar")
            )
            target.write_bytes(b"changed")
            with self.assertRaisesRegex(
                ReleaseAttestationFailure,
                "differs from deterministic reproduction",
            ):
                verify_release_attestation_subjects(
                    reproduced, published, generated, tag="v0.1.0"
                )

    def test_missing_or_extra_published_asset_fails_closed(self):
        for mutation in ("missing", "extra"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                reproduced, published, generated = self._fixture(root)
                if mutation == "missing":
                    (published / "release-candidate-preparation-receipt.md").unlink()
                else:
                    (published / "unexpected.txt").write_text("unexpected")
                with self.assertRaisesRegex(
                    ReleaseAttestationFailure,
                    "published release asset set is incomplete",
                ):
                    verify_release_attestation_subjects(
                        reproduced, published, generated, tag="v0.1.0"
                    )

    def test_wrong_tag_and_verification_receipt_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reproduced, published, generated = self._fixture(root)
            with self.assertRaisesRegex(
                ReleaseAttestationFailure,
                "candidate for the requested tag",
            ):
                verify_release_attestation_subjects(
                    reproduced, published, generated, tag="v0.1.1"
                )
            generated.write_text("{}\n")
            with self.assertRaisesRegex(
                ReleaseAttestationFailure,
                "differs from exact replay",
            ):
                verify_release_attestation_subjects(
                    reproduced, published, generated, tag="v0.1.0"
                )

    def test_symlinked_subject_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reproduced, published, generated = self._fixture(root)
            target = published / "release-candidate-preparation-receipt.md"
            target.unlink()
            target.symlink_to(reproduced / target.name)
            with self.assertRaisesRegex(
                ReleaseAttestationFailure,
                "non-regular entry",
            ):
                verify_release_attestation_subjects(
                    reproduced, published, generated, tag="v0.1.0"
                )

    def test_workflow_is_release_bounded_and_actions_are_immutably_pinned(self):
        workflow = (ROOT / ".github/workflows/release-attestations.yml").read_text()
        self.assertIn("release:\n    types: [published]", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("\n  push:", workflow)
        self.assertIn("id-token: write", workflow)
        self.assertIn("attestations: write", workflow)
        self.assertNotIn("contents: write", workflow)
        uses = re.findall(r"^\s*uses:\s*([^\s#]+)", workflow, re.MULTILINE)
        self.assertGreaterEqual(len(uses), 4)
        for reference in uses:
            self.assertRegex(reference, r"^[^@]+@[0-9a-f]{40}$")

    def test_committed_release_public_key_matches_generation_one_fingerprint(self):
        public_key = ROOT / "docs/release/artifact-memory-release-signing-generation-1.pub"
        output = subprocess.check_output(
            ["ssh-keygen", "-lf", str(public_key)], text=True
        )
        self.assertEqual(
            output.split()[1],
            "SHA256:h9q2smRb0EzPURXH1LW6IkQcudQIRC3hlGux8ugyBU4",
        )


if __name__ == "__main__":
    unittest.main()
