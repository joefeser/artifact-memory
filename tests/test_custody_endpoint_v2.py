import copy
import json
import unittest
from pathlib import Path

from artifact_memory.custody import (
    migrate_custody_endpoint_v1_to_v2,
    render_custody_write_preflight_receipt,
    validate_custody_write_preflight,
    validate_custody_write_preflight_receipt,
)
from artifact_memory.canonical import expected_receipt_id
from artifact_memory.validator import ValidationFailure, validate


ROOT = Path(__file__).resolve().parents[1]


class CustodyEndpointV2Tests(unittest.TestCase):
    def _load(self, relative_path):
        return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))

    def _authorized_pair(self):
        endpoint = self._load("fixtures/synthetic/custody-endpoint/v2/proxmox-vault-template.json")
        adapter = self._load("config/templates/proxmox-restic-rest-server.v1.json")
        endpoint["remote_write"] = "authorized"
        endpoint["transport"]["remote_write_authorization"] = "authorized"
        endpoint["deployment"]["provisioning_state"] = "ready"
        for field in endpoint["transport"]["primary"]:
            if field.endswith("_state"):
                endpoint["transport"]["primary"][field] = "configured"
        endpoint["storage"]["snapshot_schedule_state"] = "configured"
        endpoint["storage"]["storage_location_state"] = "configured"
        for field in endpoint["provisioning"]:
            endpoint["provisioning"][field] = "configured"
        adapter["remote_write_state"] = "authorized"
        for field in ("address_state", "account_state", "repository_state", "service_state"):
            adapter[field] = "configured"
        adapter["storage_boundary"]["zfs_snapshot_schedule_state"] = "configured"
        return endpoint, adapter

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
        self.assertEqual(template["transport"]["primary"]["service_state"], "owner-to-fill")
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
        with self.assertRaises(ValidationFailure):
            validate(ready, schema)

        ready["transport"]["primary"]["service_state"] = "configured"
        validate(ready, schema)

    def test_transport_authorization_cannot_contradict_top_level_authorization(self):
        schema = json.loads((ROOT / "artifact_memory/schemas/core/custody-endpoint.v2.schema.json").read_text(encoding="utf-8"))
        template = json.loads((ROOT / "fixtures/synthetic/custody-endpoint/v2/proxmox-vault-template.json").read_text(encoding="utf-8"))
        contradictory = copy.deepcopy(template)
        contradictory["transport"]["remote_write_authorization"] = "authorized"
        with self.assertRaises(ValidationFailure):
            validate(contradictory, schema)

    def test_cross_document_preflight_rejects_adapter_authorization_divergence(self):
        endpoint, adapter = self._authorized_pair()
        adapter["remote_write_state"] = "not-authorized"
        with self.assertRaises(ValidationFailure) as failure:
            validate_custody_write_preflight(endpoint, adapter)
        self.assertEqual(failure.exception.code, "custody-preflight-binding-mismatch")

    def test_cross_document_preflight_emits_bound_non_authorizing_receipts(self):
        endpoint = self._load("fixtures/synthetic/custody-endpoint/v2/proxmox-vault-template.json")
        adapter = self._load("config/templates/proxmox-restic-rest-server.v1.json")
        pending = validate_custody_write_preflight(endpoint, adapter)
        self.assertEqual(pending["outcome"], "not-authorized")
        validate_custody_write_preflight_receipt(pending)

        endpoint, adapter = self._authorized_pair()
        ready = validate_custody_write_preflight(endpoint, adapter)
        self.assertEqual(ready["outcome"], "ready-for-owner-authorized-write")
        self.assertIn("grants no remote-write", ready["authority_boundary"])
        validate_custody_write_preflight_receipt(ready)
        forged = dict(ready)
        forged["outcome"] = "not-authorized"
        with self.assertRaises(ValidationFailure) as failure:
            validate_custody_write_preflight_receipt(forged)
        self.assertEqual(failure.exception.code, "custody-preflight-receipt-id-mismatch")

    def test_checked_in_preflight_fixture_proves_the_non_authorized_seam(self):
        fixture = ROOT / "fixtures/synthetic/custody-preflight/v1"
        endpoint = self._load("fixtures/synthetic/custody-endpoint/v2/proxmox-vault-template.json")
        adapter = self._load("config/templates/proxmox-restic-rest-server.v1.json")
        receipt = validate_custody_write_preflight(endpoint, adapter)
        expected = json.loads((fixture / "expected-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt, expected)
        self.assertEqual(
            render_custody_write_preflight_receipt(receipt),
            (fixture / "receipt.md").read_text(encoding="utf-8"),
        )

    def test_cross_document_preflight_dispatches_to_sftp_and_binds_documents(self):
        endpoint, _ = self._authorized_pair()
        adapter = self._load("config/templates/proxmox-restic-sftp.v2.json")
        for field in ("address_state", "account_state", "repository_state"):
            adapter[field] = "configured"
        adapter["storage_boundary"]["zfs_snapshot_schedule_state"] = "configured"
        adapter["remote_write_state"] = "authorized"
        endpoint["transport"]["fallback"]["account_state"] = "configured"
        receipt = validate_custody_write_preflight(endpoint, adapter)
        self.assertEqual(receipt["transport"], "restic-over-sftp")
        self.assertEqual(receipt["outcome"], "ready-for-owner-authorized-write")
        self.assertNotEqual(receipt["endpoint_document_digest"], receipt["adapter_document_digest"])
        validate_custody_write_preflight_receipt(receipt)

    def test_sftp_preflight_requires_restricted_non_root_mode(self):
        endpoint, _ = self._authorized_pair()
        adapter = self._load("config/templates/proxmox-restic-sftp.v2.json")
        adapter.pop("mode")
        with self.assertRaises(ValidationFailure):
            validate_custody_write_preflight(endpoint, adapter)

    def test_legacy_sftp_v1_remains_valid_and_fail_closed(self):
        endpoint = self._load("fixtures/synthetic/custody-endpoint/v2/proxmox-vault-template.json")
        adapter = self._load("config/templates/proxmox-restic-sftp.v1.json")
        receipt = validate_custody_write_preflight(endpoint, adapter)
        self.assertEqual(receipt["adapter_schema_id"], "artifact-memory/restic-sftp-config/v1")
        self.assertEqual(receipt["outcome"], "not-authorized")
        validate_custody_write_preflight_receipt(receipt)

    def test_preflight_receipt_rejects_mismatched_adapter_transport(self):
        endpoint, adapter = self._authorized_pair()
        receipt = validate_custody_write_preflight(endpoint, adapter)
        receipt["transport"] = "restic-over-sftp"
        receipt["receipt_id"] = expected_receipt_id(
            receipt,
            "custody-write-preflight-receipt://",
        )
        with self.assertRaises(ValidationFailure) as failure:
            validate_custody_write_preflight_receipt(receipt)
        self.assertEqual(failure.exception.code, "custody-preflight-transport-mismatch")

    def test_cross_document_preflight_rejects_non_string_keys(self):
        endpoint = self._load("fixtures/synthetic/custody-endpoint/v2/proxmox-vault-template.json")
        adapter = self._load("config/templates/proxmox-restic-rest-server.v1.json")
        endpoint["transport"][1] = "invalid"
        with self.assertRaises(ValidationFailure) as failure:
            validate_custody_write_preflight(endpoint, adapter)
        self.assertEqual(failure.exception.code, "type-mismatch")

    def test_v1_migration_builds_and_validates_a_new_fail_closed_v2_document(self):
        source = self._load("fixtures/synthetic/custody-endpoint/v1/proxmox-vault-template.json")
        migrated = migrate_custody_endpoint_v1_to_v2(source)
        self.assertEqual(source["schema_id"], "artifact-memory/custody-endpoint/v1")
        self.assertEqual(migrated["schema_id"], "artifact-memory/custody-endpoint/v2")
        self.assertEqual(migrated["transport"]["fallback"]["method"], source["transport"]["method"])
        self.assertEqual(migrated["remote_write"], "not-authorized")
        validate(migrated, self._load("artifact_memory/schemas/core/custody-endpoint.v2.schema.json"))

    def test_v1_migration_rejects_v2_input_and_relabel_only_conversion(self):
        v2 = self._load("fixtures/synthetic/custody-endpoint/v2/proxmox-vault-template.json")
        with self.assertRaises(ValidationFailure):
            migrate_custody_endpoint_v1_to_v2(v2)

        relabeled = self._load("fixtures/synthetic/custody-endpoint/v1/proxmox-vault-template.json")
        relabeled["schema_id"] = "artifact-memory/custody-endpoint/v2"
        with self.assertRaises(ValidationFailure):
            validate(relabeled, self._load("artifact_memory/schemas/core/custody-endpoint.v2.schema.json"))

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
