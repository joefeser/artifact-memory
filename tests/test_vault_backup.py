import io
import errno
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from artifact_memory.artifact_lineage import validate_artifact, validate_artifact_version
from artifact_memory.backup import create_backup, create_git_bundle, restore_isolated
from artifact_memory.canonical import canonical_bytes, expected_receipt_id
from artifact_memory.vault import intake_bytes, register_bytes
from artifact_memory.validator import validate


ROOT = Path(__file__).resolve().parents[1]


class VaultBackupTests(unittest.TestCase):
    def _intake(self, vault, data=b"synthetic intake bytes\n", **overrides):
        arguments = {
            "artifact_id": "artifact://synthetic/intake-document",
            "artifact_kind": "document",
            "title": "Synthetic intake document",
            "created_at": "2026-08-03T00:00:00Z",
            "source_ref": "fixture://synthetic/private-vault-intake",
            "media_type": "text/plain",
        }
        arguments.update(overrides)
        return intake_bytes(vault, data, **arguments)

    def test_sanitized_dogfood_receipt_is_public_safe(self):
        receipt = json.loads((ROOT / "fixtures/synthetic/dogfood/v1/receipt.json").read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "artifact_memory/schemas/core/dogfood-receipt.v1.schema.json").read_text(encoding="utf-8"))
        validate(receipt, schema)
        self.assertFalse(receipt["private_material_committed"])

    def test_content_registration_is_immutable_and_duplicate_safe(self):
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            first = register_bytes(vault, b"synthetic vault bytes\n", "text/plain")
            second = register_bytes(vault, b"synthetic vault bytes\n", "text/plain")
            schema = json.loads((ROOT / "artifact_memory/schemas/core/content-registration-receipt.v1.schema.json").read_text(encoding="utf-8"))
            validate(first, schema)
            validate(second, schema)
            self.assertEqual(first["outcome"], "registered")
            self.assertEqual(second["outcome"], "duplicate")
            self.assertEqual(
                first["receipt_id"],
                expected_receipt_id(first, "registration-receipt://"),
            )

    def test_content_registration_identity_binds_media_type(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            payload = b"synthetic media type binding\n"
            plain = register_bytes(Path(first), payload, "text/plain")
            binary = register_bytes(Path(second), payload, "application/octet-stream")

        self.assertNotEqual(plain["receipt_id"], binary["receipt_id"])
        self.assertEqual(
            binary["receipt_id"],
            expected_receipt_id(binary, "registration-receipt://"),
        )

    def test_content_registration_fails_when_existing_object_is_corrupt(self):
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            data = b"synthetic vault bytes\n"
            first = register_bytes(vault, data, "text/plain")
            digest_hex = first["digest"].removeprefix("sha-256:")
            stored = vault / "objects" / "sha256" / digest_hex[:2] / digest_hex[2:]
            stored.write_bytes(b"corrupt")

            receipt = register_bytes(vault, data, "text/plain")
            schema = json.loads((ROOT / "artifact_memory/schemas/core/content-registration-receipt.v1.schema.json").read_text(encoding="utf-8"))
            validate(receipt, schema)
            self.assertEqual(receipt["outcome"], "failed")
            self.assertEqual(receipt["diagnostics"], ["existing-object-integrity-failed"])
            self.assertEqual(stored.read_bytes(), b"corrupt")

    def test_intake_registers_verifies_records_and_replays_as_duplicate(self):
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            first = self._intake(vault)
            second = self._intake(vault)
            schema = json.loads((ROOT / "artifact_memory/schemas/core/vault-intake-receipt.v1.schema.json").read_text(encoding="utf-8"))
            validate(first, schema)
            validate(second, schema)
            self.assertEqual(first["outcome"], "registered")
            self.assertEqual(first["verification_outcome"], "verified")
            self.assertEqual(first["canonical_records"], "created")
            self.assertEqual(second["outcome"], "duplicate")
            self.assertEqual(second["canonical_records"], "duplicate")
            artifacts = list((vault / "records/artifacts").glob("*.json"))
            versions = list((vault / "records/versions").glob("*.json"))
            self.assertEqual(len(artifacts), 1)
            self.assertEqual(len(versions), 1)
            validate_artifact(json.loads(artifacts[0].read_text(encoding="utf-8")))
            validate_artifact_version(json.loads(versions[0].read_text(encoding="utf-8")))

    def test_intake_quarantines_digest_mismatch_without_registration(self):
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            receipt = self._intake(vault, expected_digest="sha-256:" + "0" * 64)
            self.assertEqual(receipt["outcome"], "quarantined")
            self.assertEqual(receipt["registration_outcome"], "not-attempted")
            self.assertFalse((vault / "objects").exists())
            self.assertEqual(len([path for path in (vault / "quarantine").rglob("*") if path.is_file()]), 1)
            self.assertNotIn(str(vault), json.dumps(receipt))

    def test_intake_invalid_metadata_fails_without_echo_or_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            receipt = self._intake(vault, artifact_id="/private/local/path")
            schema = json.loads((ROOT / "artifact_memory/schemas/core/vault-intake-receipt.v1.schema.json").read_text(encoding="utf-8"))
            validate(receipt, schema)
            self.assertEqual(receipt["outcome"], "failed")
            self.assertEqual(receipt["artifact_ref"], "artifact://unknown/unknown")
            self.assertNotIn("/private/local/path", json.dumps(receipt))
            self.assertFalse(vault.exists())

    def test_intake_rejects_nonportable_source_references_without_write(self):
        for source_ref in (
            "file:///private/local/path",
            "https://example.test/object?token=secret",
            "https://user:secret@example.test/object",
            "sftp://example.test/private/object",
        ):
            with self.subTest(source_ref=source_ref), tempfile.TemporaryDirectory() as temporary:
                vault = Path(temporary) / "vault"
                receipt = self._intake(vault, source_ref=source_ref)
                self.assertEqual(receipt["outcome"], "failed")
                self.assertEqual(receipt["diagnostics"], ["intake-metadata-invalid"])
                self.assertNotIn(source_ref, json.dumps(receipt))
                self.assertFalse(vault.exists())

    def test_intake_rejects_non_string_expected_digest_with_receipt(self):
        for expected_digest in (7, ["sha-256:" + "0" * 64]):
            with self.subTest(expected_digest=expected_digest), tempfile.TemporaryDirectory() as temporary:
                receipt = self._intake(Path(temporary) / "vault", expected_digest=expected_digest)
                self.assertEqual(receipt["outcome"], "failed")
                self.assertEqual(receipt["diagnostics"], ["expected-digest-invalid"])

    def test_mixed_canonical_record_recovery_requires_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            self.assertEqual(self._intake(vault)["outcome"], "registered")
            next((vault / "records/versions").glob("*.json")).unlink()
            mixed = self._intake(vault)
            replayed = self._intake(vault)
            self.assertEqual(mixed["outcome"], "failed")
            self.assertEqual(mixed["canonical_records"], "failed")
            self.assertEqual(mixed["diagnostics"], ["canonical-record-state-mixed-replay-required"])
            self.assertEqual(replayed["outcome"], "duplicate")

    def test_hardlink_unavailable_fails_closed_without_partial(self):
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            unavailable = OSError(errno.EOPNOTSUPP, "synthetic hardlink unavailable")
            with patch("artifact_memory.vault.os.link", side_effect=unavailable):
                receipt = register_bytes(vault, b"synthetic fallback bytes")
            self.assertEqual(receipt["outcome"], "failed")
            self.assertEqual(receipt["diagnostics"], ["object-write-hardlink-unsupported"])
            self.assertEqual([path for path in vault.rglob("*") if path.is_file()], [])

    def test_cleanup_failure_is_explicit_and_preserves_unsafe_partial(self):
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            with (
                patch("artifact_memory.vault.os.link", side_effect=OSError(errno.EIO, "synthetic publish failure")),
                patch("artifact_memory.vault.os.unlink", side_effect=OSError(errno.EACCES, "synthetic cleanup failure")),
            ):
                receipt = register_bytes(vault, b"synthetic cleanup failure bytes")
            self.assertEqual(receipt["outcome"], "failed")
            self.assertEqual(receipt["diagnostics"], ["object-write-cleanup-failed"])
            self.assertEqual(len([path for path in vault.rglob("*") if path.name.startswith(".partial-")]), 1)

    def test_interrupted_object_write_is_receipted_and_leaves_no_partial(self):
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            with patch("artifact_memory.vault.os.link", side_effect=OSError("synthetic interruption")):
                receipt = register_bytes(vault, b"synthetic interrupted bytes")
            self.assertEqual(receipt["outcome"], "failed")
            self.assertIn("object-write-failed", receipt["diagnostics"])
            self.assertEqual([path for path in vault.rglob("*") if path.name.startswith(".partial-")], [])
            self.assertEqual([path for path in (vault / "objects").rglob("*") if path.is_file()], [])

    def test_encrypted_backup_and_isolated_restore(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "records.ndjson").write_text('{"synthetic":true}\n', encoding="utf-8")
            (source / "vault-object").write_bytes(b"synthetic bytes")
            backup_dir = root / "backup"
            backup = create_backup({"knowledge": source}, backup_dir, "synthetic-passphrase")
            backup_schema = json.loads((ROOT / "artifact_memory/schemas/core/backup-receipt.v1.schema.json").read_text(encoding="utf-8"))
            validate(backup, backup_schema)
            encrypted = (backup_dir / "backup.enc").read_bytes()
            self.assertNotIn(b"synthetic bytes", encrypted)
            restored = root / "isolated-restore"
            receipt = restore_isolated(
                backup_dir / "backup.enc",
                restored,
                "synthetic-passphrase",
                backup["backup_ref"],
                backup["backup_digest"],
                backup["source_manifest_digest"],
            )
            restore_schema = json.loads((ROOT / "artifact_memory/schemas/core/restore-receipt.v1.schema.json").read_text(encoding="utf-8"))
            validate(receipt, restore_schema)
            self.assertEqual(receipt["outcome"], "restored")
            self.assertEqual((restored / "knowledge" / "records.ndjson").read_text(encoding="utf-8"), '{"synthetic":true}\n')
            self.assertEqual(restore_isolated(backup_dir / "backup.enc", restored, "synthetic-passphrase", backup["backup_ref"], backup["backup_digest"])["outcome"], "rejected")

            mismatched = restore_isolated(
                backup_dir / "backup.enc",
                root / "mismatched-restore",
                "synthetic-passphrase",
                backup["backup_ref"],
                backup["backup_digest"],
                "sha-256:" + "0" * 64,
            )
            self.assertEqual(mismatched["outcome"], "failed")
            self.assertIn("backup-manifest-digest-mismatch", mismatched["limitations"])

    def test_missing_openssl_returns_schema_valid_failure_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            source.write_text("synthetic", encoding="utf-8")
            with patch("artifact_memory.backup.subprocess.run", side_effect=FileNotFoundError):
                receipt = create_backup({"knowledge": source}, root / "backup", "synthetic-passphrase")
            schema = json.loads((ROOT / "artifact_memory/schemas/core/backup-receipt.v1.schema.json").read_text(encoding="utf-8"))
            validate(receipt, schema)
            self.assertEqual(receipt["outcome"], "failed")
            self.assertIn("openssl-unavailable", receipt["limitations"])

    def test_restore_rejects_nonregular_members_and_malformed_manifest_with_receipts(self):
        def copy_without_encryption(_args, _passphrase, input_path, output_path):
            shutil.copyfile(input_path, output_path)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            malformed = root / "malformed.tar"
            with tarfile.open(malformed, "w") as archive:
                manifest = b"[]"
                info = tarfile.TarInfo("backup-manifest.json")
                info.size = len(manifest)
                archive.addfile(info, io.BytesIO(manifest))
            with patch("artifact_memory.backup._run_openssl", side_effect=copy_without_encryption):
                receipt = restore_isolated(malformed, root / "malformed-restore", "unused", "backup://synthetic/test")
            schema = json.loads((ROOT / "artifact_memory/schemas/core/restore-receipt.v1.schema.json").read_text(encoding="utf-8"))
            validate(receipt, schema)
            self.assertEqual(receipt["outcome"], "failed")
            self.assertIn("backup-manifest-invalid", receipt["limitations"])

            unsafe = root / "unsafe.tar"
            with tarfile.open(unsafe, "w") as archive:
                fifo = tarfile.TarInfo("unsafe-fifo")
                fifo.type = tarfile.FIFOTYPE
                archive.addfile(fifo)
            with patch("artifact_memory.backup._run_openssl", side_effect=copy_without_encryption):
                receipt = restore_isolated(unsafe, root / "unsafe-restore", "unused", "backup://synthetic/test")
            validate(receipt, schema)
            self.assertEqual(receipt["outcome"], "failed")
            self.assertIn("unsafe-backup-member", receipt["limitations"])

            for index, unsafe_name in enumerate(("..\\..\\escape", "C:\\escape")):
                windows_unsafe = root / f"windows-unsafe-{index}.tar"
                with tarfile.open(windows_unsafe, "w") as archive:
                    payload = b"synthetic"
                    entry = tarfile.TarInfo(unsafe_name)
                    entry.size = len(payload)
                    archive.addfile(entry, io.BytesIO(payload))
                with patch("artifact_memory.backup._run_openssl", side_effect=copy_without_encryption):
                    receipt = restore_isolated(windows_unsafe, root / f"windows-unsafe-restore-{index}", "unused", "backup://synthetic/test")
                validate(receipt, schema)
                self.assertEqual(receipt["outcome"], "failed")
                self.assertIn("unsafe-backup-member", receipt["limitations"])

            alias_collision = root / "alias-collision.tar"
            with tarfile.open(alias_collision, "w") as archive:
                for name in ("knowledge/./record", "knowledge/record"):
                    payload = b"synthetic"
                    entry = tarfile.TarInfo(name)
                    entry.size = len(payload)
                    archive.addfile(entry, io.BytesIO(payload))
            with patch("artifact_memory.backup._run_openssl", side_effect=copy_without_encryption):
                receipt = restore_isolated(alias_collision, root / "alias-collision-restore", "unused", "backup://synthetic/test")
            validate(receipt, schema)
            self.assertEqual(receipt["outcome"], "failed")
            self.assertIn("unsafe-backup-member", receipt["limitations"])

            boolean_size = root / "boolean-size.tar"
            payload = b"x"
            manifest = {
                "schema_id": "artifact-memory/backup-manifest/v1",
                "entries": [{"path": "knowledge/record", "digest": "sha-256:" + hashlib.sha256(payload).hexdigest(), "byte_size": True}],
            }
            manifest_bytes = json.dumps(manifest).encode("utf-8")
            with tarfile.open(boolean_size, "w") as archive:
                entry = tarfile.TarInfo("knowledge/record")
                entry.size = len(payload)
                archive.addfile(entry, io.BytesIO(payload))
                manifest_entry = tarfile.TarInfo("backup-manifest.json")
                manifest_entry.size = len(manifest_bytes)
                archive.addfile(manifest_entry, io.BytesIO(manifest_bytes))
            with patch("artifact_memory.backup._run_openssl", side_effect=copy_without_encryption):
                receipt = restore_isolated(boolean_size, root / "boolean-size-restore", "unused", "backup://synthetic/test")
            validate(receipt, schema)
            self.assertEqual(receipt["outcome"], "failed")
            self.assertIn("backup-manifest-invalid", receipt["limitations"])

    def test_synthetic_git_bundle_verifies(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "synthetic@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Synthetic"], check=True)
            (repo / "record.json").write_text('{"synthetic":true}\n', encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "record.json"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "synthetic"], check=True)
            bundle = Path(temporary) / "knowledge.bundle"
            receipt = create_git_bundle(repo, bundle, "git://synthetic/knowledge")
            schema = json.loads((ROOT / "artifact_memory/schemas/core/git-bundle-receipt.v1.schema.json").read_text(encoding="utf-8"))
            validate(receipt, schema)
            subprocess.run(["git", "bundle", "verify", str(bundle)], check=True, stdout=subprocess.DEVNULL)

    def test_git_bundle_failure_receipt_has_digest_backed_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = create_git_bundle(root / "missing", root / "missing.bundle", "git-ref://synthetic/missing")
            body = {key: value for key, value in receipt.items() if key not in {"schema_id", "receipt_id"}}
            expected = hashlib.sha256(canonical_bytes(body)).hexdigest()
            self.assertEqual(receipt["outcome"], "failed")
            self.assertEqual(receipt["receipt_id"], "git-bundle-receipt://" + expected)


if __name__ == "__main__":
    unittest.main()
