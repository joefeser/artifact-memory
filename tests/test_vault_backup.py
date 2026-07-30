import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from artifact_memory.backup import create_backup, create_git_bundle, restore_isolated
from artifact_memory.vault import register_bytes
from artifact_memory.validator import validate


ROOT = Path(__file__).resolve().parents[1]


class VaultBackupTests(unittest.TestCase):
    def test_sanitized_dogfood_receipt_is_public_safe(self):
        receipt = json.loads((ROOT / "fixtures/synthetic/dogfood/v1/receipt.json").read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "schemas/core/dogfood-receipt.v1.schema.json").read_text(encoding="utf-8"))
        validate(receipt, schema)
        self.assertFalse(receipt["private_material_committed"])

    def test_content_registration_is_immutable_and_duplicate_safe(self):
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            first = register_bytes(vault, b"synthetic vault bytes\n", "text/plain")
            second = register_bytes(vault, b"synthetic vault bytes\n", "text/plain")
            schema = json.loads((ROOT / "schemas/core/content-registration-receipt.v1.schema.json").read_text(encoding="utf-8"))
            validate(first, schema)
            validate(second, schema)
            self.assertEqual(first["outcome"], "registered")
            self.assertEqual(second["outcome"], "duplicate")

    def test_encrypted_backup_and_isolated_restore(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "records.ndjson").write_text('{"synthetic":true}\n', encoding="utf-8")
            (source / "vault-object").write_bytes(b"synthetic bytes")
            backup_dir = root / "backup"
            backup = create_backup({"knowledge": source}, backup_dir, "synthetic-passphrase")
            backup_schema = json.loads((ROOT / "schemas/core/backup-receipt.v1.schema.json").read_text(encoding="utf-8"))
            validate(backup, backup_schema)
            encrypted = (backup_dir / "backup.enc").read_bytes()
            self.assertNotIn(b"synthetic bytes", encrypted)
            restored = root / "isolated-restore"
            receipt = restore_isolated(backup_dir / "backup.enc", restored, "synthetic-passphrase", backup["backup_ref"], backup["backup_digest"])
            restore_schema = json.loads((ROOT / "schemas/core/restore-receipt.v1.schema.json").read_text(encoding="utf-8"))
            validate(receipt, restore_schema)
            self.assertEqual(receipt["outcome"], "restored")
            self.assertEqual((restored / "knowledge" / "records.ndjson").read_text(encoding="utf-8"), '{"synthetic":true}\n')
            self.assertEqual(restore_isolated(backup_dir / "backup.enc", restored, "synthetic-passphrase", backup["backup_ref"], backup["backup_digest"])["outcome"], "rejected")

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
            schema = json.loads((ROOT / "schemas/core/git-bundle-receipt.v1.schema.json").read_text(encoding="utf-8"))
            validate(receipt, schema)
            subprocess.run(["git", "bundle", "verify", str(bundle)], check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
