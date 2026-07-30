"""Explicit custody-model receipts; this module never copies backup bytes."""

from __future__ import annotations

import hashlib
import json
from typing import Any


AUTHORITY_BOUNDARY = "custody receipt does not copy, disclose, or authorize backup bytes"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


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
        "schema_id": "artifact-memory/custody-receipt/v1",
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
    return {**body, "receipt_id": "custody-receipt://" + hashlib.sha256(_canonical(body)).hexdigest()}
