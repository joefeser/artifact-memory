"""Explicit custody receipts plus fail-closed migration and preflight."""

from __future__ import annotations

from typing import Any

from .canonical import canonical_bytes, expected_receipt_id, receipt_with_digest, sha256_bytes
from .schema_resources import load_schema
from .validator import ValidationFailure, validate


PREFLIGHT_RECEIPT_PREFIX = "custody-write-preflight-receipt://"
AUTHORITY_BOUNDARY = "custody receipt does not copy, disclose, or authorize backup bytes"
PREFLIGHT_AUTHORITY_BOUNDARY = (
    "custody preflight evidence grants no remote-write, execution, credential, "
    "or infrastructure authority"
)
ADAPTER_CONFIGS = {
    "artifact-memory/restic-rest-server-config/v1": (
        "restic-rest-server-config.v1.schema.json",
        "restic-rest-server",
    ),
    "artifact-memory/restic-sftp-config/v1": (
        "restic-sftp-config.v1.schema.json",
        "restic-over-sftp",
    ),
    "artifact-memory/restic-sftp-config/v2": (
        "restic-sftp-config.v2.schema.json",
        "restic-over-sftp",
    ),
}
PREFLIGHT_BINDING_NAMES = {
    "artifact-memory/restic-rest-server-config/v1": (
        "account_state",
        "address_state",
        "endpoint_ref",
        "provisioned_account_state",
        "provisioned_address_state",
        "provisioned_snapshot_schedule_state",
        "provisioned_storage_state",
        "remote_write",
        "repository_state",
        "service_state",
        "snapshot_schedule_state",
        "transport_authorization",
    ),
    "artifact-memory/restic-sftp-config/v1": (
        "endpoint_ref",
        "fallback_account_state",
        "provisioned_account_state",
        "provisioned_address_state",
        "provisioned_storage_state",
        "remote_write",
        "transport_authorization",
    ),
    "artifact-memory/restic-sftp-config/v2": (
        "endpoint_ref",
        "fallback_account_state",
        "provisioned_account_state",
        "provisioned_address_state",
        "provisioned_snapshot_schedule_state",
        "provisioned_storage_state",
        "remote_write",
        "snapshot_schedule_state",
        "transport_authorization",
    ),
}


def record_custody(
    backup_ref: str,
    endpoint_ref: str,
    custody_class: str,
    authorized: bool,
    key_recovery_state: str = "external-not-recorded",
    restore_test_cadence: str = "owner-policy-required",
) -> dict[str, Any]:
    """Record the custody model without claiming that transfer occurred."""
    outcome = "recorded" if authorized else "not-authorized"
    body = {
        "backup_ref": backup_ref,
        "endpoint_ref": endpoint_ref,
        "custody_class": custody_class,
        "authorization_state": "authorized" if authorized else "not-authorized",
        "key_recovery_state": key_recovery_state,
        "restore_test_cadence": restore_test_cadence,
        "outcome": outcome,
        "transfer": "not-performed-by-receipt",
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": [
            "receipt records a custody model and does not prove an endpoint copy",
            "key recovery is external to the backup payload",
        ],
    }
    return receipt_with_digest("artifact-memory/custody-receipt/v1", "custody-receipt://", body)


def _require_object(value: Any, *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationFailure("custody-input-invalid", f"{name} must be a JSON object")
    return value


def migrate_custody_endpoint_v1_to_v2(document: dict[str, Any]) -> dict[str, Any]:
    """Build and validate a new fail-closed v2 endpoint from an exact v1 input."""

    source = _require_object(document, name="v1 custody endpoint")
    validate(source, load_schema("core", "custody-endpoint.v1.schema.json"))
    if source.get("schema_id") != "artifact-memory/custody-endpoint/v1":
        raise ValidationFailure(
            "custody-migration-source-unsupported",
            "custody migration requires the exact v1 schema identifier",
            "$.schema_id",
        )

    migrated = {
        "schema_id": "artifact-memory/custody-endpoint/v2",
        "endpoint_ref": source["endpoint_ref"],
        "purpose": source["purpose"],
        "custody_claim": "off-machine-not-geographically-off-site",
        "deployment": dict(source["deployment"]),
        "network_boundary": dict(source["network_boundary"]),
        "transport": {
            "primary": {
                "method": "restic-rest-server",
                "mode": "append-only",
                "address_state": "owner-to-fill",
                "account_state": "owner-to-fill",
                "repository_state": "owner-to-fill",
                "service_state": "owner-to-fill",
            },
            "fallback": {
                "method": source["transport"]["method"],
                "mode": "restricted-non-root-account",
                "account_state": source["transport"]["account_state"],
            },
            "authenticated": source["transport"]["authenticated"],
            "credential_state": "external-not-recorded",
            "remote_write_authorization": "not-authorized",
        },
        "storage": {
            "backend": "zfs-backed",
            "client_side_encryption": source["storage"]["encryption"],
            "zfs_snapshots": "required",
            "snapshot_schedule_state": "owner-to-fill",
            "snapshot_control": "server-side-separate-from-backup-client",
            "key_material_state": source["storage"]["key_material_state"],
            "storage_location_state": source["storage"]["storage_location_state"],
        },
        "schedule": dict(source["schedule"]),
        "recovery": {
            "material_state": "owner-held-external",
            "separate_from": ["workstation", "repository", "backup-vm"],
            "alternate_access": "console-or-local",
            "tailscale_exclusive": False,
        },
        "diversity_boundary": {
            "current_geographic_claim": "not-off-site",
            "portable_provider_policy": True,
            "portable_geography_policy": True,
            "portable_jurisdiction_policy": True,
            "mandatory_vendor": False,
            "mandatory_country": False,
            "mandatory_identity_provider": False,
        },
        "provisioning": {
            "vm_address_state": source["provisioning"]["vm_address_state"],
            "account_state": source["provisioning"]["account_state"],
            "storage_state": source["provisioning"]["storage_state"],
            "snapshot_schedule_state": "owner-to-fill",
        },
        "remote_write": "not-authorized",
    }
    validate(migrated, load_schema("core", "custody-endpoint.v2.schema.json"))
    return migrated


def validate_custody_write_preflight_receipt(receipt: dict[str, Any]) -> None:
    """Validate a preflight receipt and its canonical identity."""

    validate(receipt, load_schema("core", "custody-write-preflight-receipt.v1.schema.json"))
    adapter_schema_id = receipt["adapter_schema_id"]
    expected_transport = ADAPTER_CONFIGS[adapter_schema_id][1]
    if receipt["transport"] != expected_transport:
        raise ValidationFailure(
            "custody-preflight-transport-mismatch",
            "custody preflight receipt transport does not match its adapter schema",
            "$.transport",
        )
    expected_binding_names = list(PREFLIGHT_BINDING_NAMES[adapter_schema_id])
    if receipt["binding_names"] != expected_binding_names:
        raise ValidationFailure(
            "custody-preflight-binding-names-mismatch",
            "custody preflight receipt binding names do not match its adapter schema",
            "$.binding_names",
        )
    expected_bindings_digest = sha256_bytes(canonical_bytes(expected_binding_names))
    if receipt["bindings_digest"] != expected_bindings_digest:
        raise ValidationFailure(
            "custody-preflight-bindings-digest-mismatch",
            "custody preflight receipt bindings digest does not match its canonical binding names",
            "$.bindings_digest",
        )
    if receipt["receipt_id"] != expected_receipt_id(receipt, PREFLIGHT_RECEIPT_PREFIX):
        raise ValidationFailure(
            "custody-preflight-receipt-id-mismatch",
            "custody preflight receipt identity does not match its canonical body",
            "$.receipt_id",
        )


def render_custody_write_preflight_receipt(receipt: dict[str, Any]) -> str:
    """Render the bounded preflight evidence for human review."""

    validate_custody_write_preflight_receipt(receipt)
    return (
        "# Custody write preflight receipt\n\n"
        f"- Outcome: `{receipt['outcome']}`\n"
        f"- Receipt: `{receipt['receipt_id']}`\n"
        f"- Endpoint: `{receipt['endpoint_ref']}`\n"
        f"- Adapter: `{receipt['adapter_schema_id']}`\n"
        f"- Transport: `{receipt['transport']}`\n"
        f"- Bound states: {len(receipt['binding_names'])}\n"
        f"- Authority boundary: {receipt['authority_boundary']}\n\n"
        "## Limitations\n\n"
        + "".join(f"- {limitation}\n" for limitation in receipt["limitations"])
        + "\nThis synthetic preflight proves only that the checked endpoint and adapter states agree.\n"
    )


def validate_custody_write_preflight(
    endpoint: dict[str, Any],
    adapter: dict[str, Any],
) -> dict[str, Any]:
    """Bind endpoint and owner-local adapter states without performing a write."""

    endpoint = _require_object(endpoint, name="custody endpoint")
    adapter = _require_object(adapter, name="custody adapter")
    validate(endpoint, load_schema("core", "custody-endpoint.v2.schema.json"))
    adapter_schema_id = adapter.get("schema_id")
    adapter_config = ADAPTER_CONFIGS.get(adapter_schema_id)
    if adapter_config is None:
        raise ValidationFailure(
            "custody-preflight-adapter-unsupported",
            "custody preflight requires a supported exact adapter schema identifier",
            "$.adapter.schema_id",
        )
    adapter_schema_name, transport = adapter_config
    validate(adapter, load_schema("adapters", adapter_schema_name))
    common_bindings = {
        "endpoint_ref": (endpoint["endpoint_ref"], adapter["endpoint_ref"]),
        "remote_write": (endpoint["remote_write"], adapter["remote_write_state"]),
        "transport_authorization": (
            endpoint["transport"]["remote_write_authorization"],
            adapter["remote_write_state"],
        ),
        "provisioned_address_state": (endpoint["provisioning"]["vm_address_state"], adapter["address_state"]),
        "provisioned_account_state": (endpoint["provisioning"]["account_state"], adapter["account_state"]),
        "provisioned_storage_state": (endpoint["provisioning"]["storage_state"], adapter["repository_state"]),
    }
    if adapter_schema_id == "artifact-memory/restic-rest-server-config/v1":
        bindings = {
            **common_bindings,
            "address_state": (endpoint["transport"]["primary"]["address_state"], adapter["address_state"]),
            "account_state": (endpoint["transport"]["primary"]["account_state"], adapter["account_state"]),
            "repository_state": (
                endpoint["transport"]["primary"]["repository_state"],
                adapter["repository_state"],
            ),
            "service_state": (endpoint["transport"]["primary"]["service_state"], adapter["service_state"]),
            "snapshot_schedule_state": (
                endpoint["storage"]["snapshot_schedule_state"],
                adapter["storage_boundary"]["zfs_snapshot_schedule_state"],
            ),
            "provisioned_snapshot_schedule_state": (
                endpoint["provisioning"]["snapshot_schedule_state"],
                adapter["storage_boundary"]["zfs_snapshot_schedule_state"],
            ),
        }
    elif adapter_schema_id == "artifact-memory/restic-sftp-config/v1":
        bindings = {
            **common_bindings,
            "fallback_account_state": (
                endpoint["transport"]["fallback"]["account_state"],
                adapter["account_state"],
            ),
        }
    elif adapter_schema_id == "artifact-memory/restic-sftp-config/v2":
        bindings = {
            **common_bindings,
            "fallback_account_state": (
                endpoint["transport"]["fallback"]["account_state"],
                adapter["account_state"],
            ),
            "snapshot_schedule_state": (
                endpoint["storage"]["snapshot_schedule_state"],
                adapter["storage_boundary"]["zfs_snapshot_schedule_state"],
            ),
            "provisioned_snapshot_schedule_state": (
                endpoint["provisioning"]["snapshot_schedule_state"],
                adapter["storage_boundary"]["zfs_snapshot_schedule_state"],
            ),
        }
    for name, (endpoint_value, adapter_value) in bindings.items():
        if endpoint_value != adapter_value:
            raise ValidationFailure(
                "custody-preflight-binding-mismatch",
                f"custody endpoint and adapter disagree on {name}",
                f"$.bindings.{name}",
            )

    outcome = (
        "ready-for-owner-authorized-write"
        if endpoint["remote_write"] == "authorized"
        else "not-authorized"
    )
    binding_names = sorted(bindings)
    if binding_names != list(PREFLIGHT_BINDING_NAMES[adapter_schema_id]):
        raise ValidationFailure(
            "custody-preflight-binding-contract-mismatch",
            "custody preflight implementation bindings do not match its adapter contract",
            "$.bindings",
        )
    body = {
        "endpoint_ref": endpoint["endpoint_ref"],
        "endpoint_schema_id": endpoint["schema_id"],
        "adapter_schema_id": adapter["schema_id"],
        "transport": transport,
        "outcome": outcome,
        "binding_names": binding_names,
        "endpoint_document_digest": sha256_bytes(canonical_bytes(endpoint)),
        "adapter_document_digest": sha256_bytes(canonical_bytes(adapter)),
        "bindings_digest": sha256_bytes(canonical_bytes(binding_names)),
        "authority_boundary": PREFLIGHT_AUTHORITY_BOUNDARY,
        "limitations": [
            "no network connection or remote write was attempted",
            "connection details and secret material are not represented",
            "explicit owner authorization remains required before any remote write",
        ],
    }
    receipt = receipt_with_digest(
        "artifact-memory/custody-write-preflight-receipt/v1",
        PREFLIGHT_RECEIPT_PREFIX,
        body,
    )
    validate_custody_write_preflight_receipt(receipt)
    return receipt
