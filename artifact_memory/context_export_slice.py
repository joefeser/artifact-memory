"""Synthetic #20 proof for bounded informational context export and recall."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, receipt_with_digest
from .context import export_context
from .independent_context_reader import recall_context
from .schema_resources import load_schema
from .validator import validate


SELECTED_AT = "2026-07-30T00:00:00Z"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def run_context_export_slice(fixture_root: Path) -> dict[str, Any]:
    records = [_load(path) for path in sorted((fixture_root / "records").glob("*.json"))]
    evidence = _load(fixture_root / "external-evidence.json")
    authorized_ids = [record["record_id"] for record in records]
    freshness = {
        record_id: {
            "status": "stale" if record_id.endswith("stale-0001") else "current",
            "assessed_at": SELECTED_AT,
            "basis": "synthetic-fixture-selection-receipt",
        }
        for record_id in authorized_ids
    }
    pack = export_context(
        reversed(records),
        reversed(evidence),
        authorized_record_ids=authorized_ids,
        authorized_evidence=[("tracemap", "fact-synthetic-status-access")],
        freshness_by_record=freshness,
        selected_at=SELECTED_AT,
        max_bytes=16_384,
    )
    recall = recall_context(canonical_bytes(pack))
    validate(pack, load_schema("core", "context-pack.v1.schema.json"))
    validate(recall, load_schema("core", "context-recall-receipt.v1.schema.json"))
    serialized = canonical_bytes(pack)
    if b"private-0001" in serialized or b"stale-0001" in serialized:
        raise RuntimeError("excluded record identity leaked into context pack")
    if b"provider-internal-row" in serialized:
        raise RuntimeError("unauthorized provider record leaked into context pack")
    if recall["records"] != [
        {
            "record_id": "record://synthetic/context-public-0001",
            "revision_digest": pack["records"][0]["revision_digest"],
            "summary": "Synthetic status evidence can be recalled without execution authority.",
        }
    ]:
        raise RuntimeError("independent reader did not recall the authorized synthetic record")
    body = {
        "outcome": "complete",
        "context_pack_id": pack["pack_id"],
        "context_pack_digest": "sha-256:" + hashlib.sha256(serialized).hexdigest(),
        "source_record_set_digest": pack["selection_receipt"]["source_record_set_digest"],
        "selected_record_ids": pack["selection_receipt"]["selected_record_ids"],
        "selected_external_evidence": pack["selection_receipt"]["selected_external_evidence"],
        "exclusion_counts": pack["selection_receipt"]["exclusion_counts"],
        "recall_receipt_id": recall["receipt_id"],
        "artifact_retrieval": recall["artifact_retrieval"],
        "mutation_authority": recall["mutation_authority"],
        "disclosure_authority": recall["disclosure_authority"],
        "execution_authority": recall["execution_authority"],
        "provider_boundary": "generic references only; provider internal model not copied",
        "limitations": [
            "freshness is an explicit operator assertion, not inferred truth",
            "artifact references require separately authorized retrieval",
        ],
    }
    receipt = receipt_with_digest(
        "artifact-memory/context-export-slice-receipt/v1",
        "context-export-receipt://synthetic/",
        body,
    )
    validate(receipt, load_schema("core", "context-export-slice-receipt.v1.schema.json"))
    return receipt
