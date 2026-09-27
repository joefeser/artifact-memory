"""Receipt-bound context packs from one verified authorized projection."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, sha256_bytes
from .coordination import (
    ACCESS_LABEL_SCHEMA_ID,
    revision_digest,
    validate_coordination_record_body,
)
from .coordination_sync import (
    load_authorized_coordination_snapshot,
    pair_set_digest,
    sorted_pairs,
)
from .schema_resources import load_schema
from .validator import ValidationFailure, validate


CONTEXT_PACK_SCHEMA_ID = "artifact-memory/coordination-context-pack/v0"
CONTEXT_PACK_PREFIX = "coordination-context-pack://sha-256/"
AUTHORITY_BOUNDARY = (
    "coordination context is informational only and grants no execution, mutation, "
    "routing, disclosure, credential, spending, deployment, approval, or merge authority"
)
_CONTEXT_PACK_SCHEMA = load_schema(
    "core", "coordination-context-pack.v0.schema.json"
)


def _record_ref(record: dict[str, Any], digest: str | None = None) -> dict[str, str]:
    return {
        "record_id": record["record_id"],
        "revision_digest": digest or revision_digest(record),
    }


def _expected_pack_id(pack: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in pack.items()
        if key not in {"schema_id", "pack_id"}
    }
    return CONTEXT_PACK_PREFIX + sha256_bytes(canonical_bytes(body)).removeprefix(
        "sha-256:"
    )


def validate_coordination_context_pack(pack: dict[str, Any]) -> None:
    """Validate detached integrity, not the existence of referenced policy evidence."""
    validate(pack, _CONTEXT_PACK_SCHEMA)
    references: list[dict[str, str]] = []
    for index, candidate in enumerate(pack["records"]):
        try:
            record, digest = validate_coordination_record_body(candidate)
        except ValidationFailure as exc:
            raise ValidationFailure(
                "coordination-context-record-invalid",
                "coordination context contains an invalid record",
                f"$.records[{index}]",
            ) from exc
        if record["schema_id"] == ACCESS_LABEL_SCHEMA_ID:
            raise ValidationFailure(
                "coordination-context-label-body-forbidden",
                "restricted coordination context cannot contain an AccessLabel body",
                f"$.records[{index}]",
            )
        references.append(_record_ref(record, digest))
    keys = [
        (reference["record_id"], reference["revision_digest"])
        for reference in references
    ]
    if len(keys) != len(set(keys)):
        raise ValidationFailure(
            "coordination-context-record-duplicate",
            "coordination context contains a duplicate exact record pair",
            "$.records",
        )
    if references != sorted_pairs(references):
        raise ValidationFailure(
            "coordination-context-record-order-invalid",
            "coordination context records are not in canonical pair order",
            "$.records",
        )
    observation = pack["sync_observation"]
    if (
        pack["record_count"] != len(references)
        or observation["authorized_pair_count"] != len(references)
    ):
        raise ValidationFailure(
            "coordination-context-count-mismatch",
            "coordination context record counts do not match its records",
            "$.record_count",
        )
    if observation["authorized_pair_set_digest"] != pair_set_digest(references):
        raise ValidationFailure(
            "coordination-context-membership-mismatch",
            "coordination context records do not match the authorized pair-set digest",
            "$.sync_observation.authorized_pair_set_digest",
        )
    if pack["pack_id"] != _expected_pack_id(pack):
        raise ValidationFailure(
            "coordination-context-pack-id-mismatch",
            "coordination context pack identity does not match its canonical body",
            "$.pack_id",
        )


def build_coordination_context_pack(vault: Path) -> dict[str, Any]:
    """Export only records named by the latest verified authorized projection."""
    snapshot = load_authorized_coordination_snapshot(vault)
    receipt = snapshot["receipt"]
    records = deepcopy(snapshot["records"])
    body = {
        "sync_observation": {
            "receipt_id": receipt["receipt_id"],
            "completed_at": receipt["completed_at"],
            "scope_generation": receipt["scope_generation"],
            "access_label_ref": deepcopy(receipt["access_label_ref"]),
            "authorized_pair_count": receipt["authorized_membership"][
                "pair_count"
            ],
            "authorized_pair_set_digest": receipt["authorized_membership"][
                "pair_set_digest"
            ],
            "excluded_count": receipt["excluded_count"],
            "transport_state": receipt["transport_state"],
            "issuer_state": receipt["issuer_state"],
        },
        "record_count": len(records),
        "records": records,
        "authority_boundary": AUTHORITY_BOUNDARY,
    }
    pack = {
        "schema_id": CONTEXT_PACK_SCHEMA_ID,
        "pack_id": CONTEXT_PACK_PREFIX
        + sha256_bytes(canonical_bytes(body)).removeprefix("sha-256:"),
        **body,
    }
    validate_coordination_context_pack(pack)
    return pack
