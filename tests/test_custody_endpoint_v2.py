import copy
import json
import unittest
from pathlib import Path

from artifact_memory.validator import ValidationFailure, validate


ROOT = Path(__file__).resolve().parents[1]


class CustodyEndpointV2Tests(unittest.TestCase):
    def test_endpoint_prefers_append_only_with_zfs_and_no_offsite_claim(self):
        schema = json.loads((ROOT / "artifact_memory/schemas/core/custody-endpoint.v2.schema.json").read_text(encoding="utf-8"))
        template = json.loads((ROOT / "fixtures/synthetic/custody-endpoint/v2/proxmox-vault-template.json").read_text(encoding="utf-8"))
        validate(template, schema)
        self.assertEqual(template["transport"]["primary"]["mode"], "append-only")
        self.assertEqual(template["transport"]["fallback"]["mode"], "restricted-non-root-account")
        self.assertEqual(template["storage"]["backend"], "zfs-backed")
        self.assertEqual(template["storage"]["zfs_snapshots"], "required")
        self.assertEqual(template["custody_claim"], "off-machine-not-geographically-off-site")
        self.assertEqual(template["remote_write"], "not-authorized")
        self.assertFalse(template["recovery"]["tailscale_exclusive"])

    def test_remote_write_fails_closed_until_every_owner_state_is_configured(self):
        schema = json.loads((ROOT / "artifact_memory/schemas/core/custody-endpoint.v2.schema.json").read_text(encoding="utf-8"))
        template = json.loads((ROOT / "fixtures/synthetic/custody-endpoint/v2/proxmox-vault-template.json").read_text(encoding="utf-8"))
        premature = copy.deepcopy(template)
        premature["remote_write"] = "authorized"
        premature["transport"]["remote_write_authorization"] = "authorized"
        with self.assertRaises(ValidationFailure):
            validate(premature, schema)

        ready = copy.deepcopy(premature)
        ready["deployment"]["provisioning_state"] = "ready"
        ready["transport"]["primary"]["address_state"] = "configured"
        ready["transport"]["primary"]["account_state"] = "configured"
        ready["transport"]["primary"]["repository_state"] = "configured"
        ready["storage"]["snapshot_schedule_state"] = "configured"
        ready["storage"]["storage_location_state"] = "configured"
        for field in ready["provisioning"]:
            ready["provisioning"][field] = "configured"
        validate(ready, schema)

    def test_owner_configuration_template_contains_no_connection_or_secret_material(self):
        schema = json.loads((ROOT / "artifact_memory/schemas/adapters/restic-rest-server-config.v1.schema.json").read_text(encoding="utf-8"))
        config = json.loads((ROOT / "config/templates/proxmox-restic-rest-server.v1.json").read_text(encoding="utf-8"))
        validate(config, schema)
        encoded = json.dumps(config, sort_keys=True)
        for prohibited in ("sftp://", "rest://", "http://", "https://", "@", "passphrase", "private_key"):
            self.assertNotIn(prohibited, encoded)
        self.assertEqual(config["remote_write_state"], "not-authorized")
        self.assertEqual(config["secret_state"], "external-not-recorded")


if __name__ == "__main__":
    unittest.main()
