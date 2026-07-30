import json
import unittest
from pathlib import Path

from artifact_memory.validator import validate


class ResticSftpConfigTests(unittest.TestCase):
    def test_configuration_template_has_no_connection_or_secret_material(self):
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root / "artifact_memory/schemas/adapters/restic-sftp-config.v1.schema.json").read_text(encoding="utf-8"))
        config = json.loads((root / "config/templates/proxmox-restic-sftp.v1.json").read_text(encoding="utf-8"))
        validate(config, schema)
        self.assertEqual(config["remote_write_state"], "not-authorized")
        self.assertEqual(config["secret_state"], "external-not-recorded")
        self.assertEqual(config["address_state"], "owner-to-fill")


if __name__ == "__main__":
    unittest.main()
