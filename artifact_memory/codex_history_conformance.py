"""Synthetic #37 proof for bounded Codex-history derivative intake."""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, receipt_with_digest
from .codex_history import AUTHORITY_BOUNDARY, import_task_export
from .context import build_selection_policy, export_context
from .projection import project_records
from .retention import deletion_request
from .schema_resources import load_schema
from .validator import load_json, validate


def _object(path: Path) -> dict[str, Any]:
    value = load_json(path)
    if not isinstance(value, dict):
        raise RuntimeError(f"synthetic fixture must be an object: {path.name}")
    return value


def _record_set_digest(records: list[dict[str, Any]]) -> str:
    lines = b"".join(canonical_bytes(record) + b"\n" for record in records)
    return "sha-256:" + hashlib.sha256(lines).hexdigest()


def run_codex_history_conformance(fixture_root: Path) -> dict[str, Any]:
    """Exercise one selected synthetic export without admitting excluded source data."""
    task = _object(fixture_root / "task-export.json")
    policy = _object(fixture_root / "import-policy.json")
    validate(policy, load_schema("adapters", "codex-history-import-policy.v1.schema.json"))
    result = import_task_export(task, policy)
    records = sorted(result["records"], key=lambda item: item["record_id"])
    receipt = result["declassification_receipt"]
    record_schema = load_schema("core", "knowledge-record.v2.schema.json")
    for record in records:
        validate(record, record_schema)
    validate(receipt, load_schema("core", "declassification-receipt.v2.schema.json"))

    excluded_fields = sorted(set(task) - set(policy["allowed_fields"]))
    excluded_values = [canonical_bytes(task[field]) for field in excluded_fields]
    admitted_bytes = canonical_bytes({"records": records, "receipt": receipt})
    if any(value in admitted_bytes for value in excluded_values):
        raise RuntimeError("excluded synthetic source material reached admitted output")

    with tempfile.TemporaryDirectory(prefix="artifact-memory-codex-history-") as temporary:
        root = Path(temporary)
        record_root = root / "records"
        record_root.mkdir()
        paths = []
        for index, record in enumerate(records, start=1):
            path = record_root / f"{index:04d}.json"
            path.write_text(
                json.dumps(record, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            paths.append(path)
        projection = project_records(paths, root / "projection")
        selection = build_selection_policy(
            [record["record_id"] for record in records],
            selected_at=policy["authorized_at"],
            freshness_basis="synthetic-owner-curation",
        )
        context_pack = export_context(
            records,
            allowed_sensitivity="public",
            max_bytes=32_768,
            supported_context_schema_ids={"artifact-memory/context-pack/v4"},
            **selection,
        )

    lifecycle_request = deletion_request(
        records[0]["record_id"],
        "active-vault",
        authorized=False,
        observed_at=policy["authorized_at"],
    )
    validate(lifecycle_request, load_schema("core", "deletion-receipt.v2.schema.json"))
    context_bytes = canonical_bytes(context_pack)
    if any(value in context_bytes for value in excluded_values):
        raise RuntimeError("excluded synthetic source material reached context output")

    labels = Counter(record["meaning"]["labels"][1] for record in records)
    body = {
        "outcome": "complete",
        "import_policy_id": policy["policy_id"],
        "source_fixture_digest": "sha-256:" + hashlib.sha256(canonical_bytes(task)).hexdigest(),
        "declassification_receipt_id": receipt["receipt_id"],
        "record_set_digest": _record_set_digest(records),
        "record_type_counts": {
            "decision": labels["decision"],
            "research": labels["research"],
            "workstream": labels["workstream"],
            "question": labels["question"],
        },
        "records_validated": len(records),
        "projection_source_digest": projection["source_record_set_digest"],
        "context_pack_id": context_pack["pack_id"],
        "context_record_count": len(context_pack["records"]),
        "excluded_source_field_count": len(excluded_fields),
        "excluded_source_material_admitted": False,
        "raw_source_canonical": False,
        "correction_route": receipt["correction_route"],
        "deletion_route": receipt["deletion_route"],
        "deletion_request_outcome": lifecycle_request["outcome"],
        "destructive_execution_performed": False,
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": [
            "fixture is newly authored synthetic data, not redacted task history",
            "owner review remains required before accepting derivative meaning",
            "deletion request receipt does not execute deletion",
        ],
    }
    conformance = receipt_with_digest(
        "artifact-memory/codex-history-conformance-receipt/v1",
        "codex-history-conformance-receipt://synthetic/",
        body,
    )
    validate(
        conformance,
        load_schema("core", "codex-history-conformance-receipt.v1.schema.json"),
    )
    return conformance
