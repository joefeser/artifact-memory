import json
import unittest
from pathlib import Path

from artifact_memory.validator import validate


class CustodyEndpointTests(unittest.TestCase):
    def test_proxmox_template_is_portable_and_unprovisioned(self):
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root / "schemas/core/custody-endpoint.v1.schema.json").read_text(encoding="utf-8"))
        template = json.loads((root / "fixtures/synthetic/custody-endpoint/v1/proxmox-vault-template.json").read_text(encoding="utf-8"))
        validate(template, schema)
        forbidden_keys = {"hostname", "ip_address", "mount_point", "drive_letter", "unc_path", "passphrase", "account", "storage_path"}
        self.assertTrue(forbidden_keys.isdisjoint(template))
        self.assertNotIn("sftp://", json.dumps(template, sort_keys=True))
        self.assertNotIn("@", json.dumps(template, sort_keys=True))
        self.assertEqual(template["remote_write"], "not-authorized")
        self.assertFalse(template["network_boundary"]["public_inbound"])


if __name__ == "__main__":
    unittest.main()
