"""Provider-free synthetic proof for the projection read integrity gate."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from typing import Any, Callable

from .canonical import receipt_with_digest
from .projection import (
    logical_projection_snapshot,
    project_records,
    projection_metadata,
    records_with_provenance,
    related_records,
    search_records,
)
from .schema_resources import load_schema
from .validator import ValidationFailure, validate


PROVENANCE_REF = "fixture://synthetic/projection-integrity/v1"
AUTHORITY_BOUNDARY = "informational-only/no-execution-authority"
FORGED_TERM = "syntheticforged"
FORGED_SUMMARY = "synthetic forged summary advertising syntheticforged"
FIRST_RECORD_ID = "record://synthetic/projection-integrity-0001"
GATE_CODE = "projection-unavailable"


def _operation(name: str, outcome: str = "complete") -> dict[str, str]:
    return {"name": name, "outcome": outcome}


def _surface_outcome(probe: Callable[[], object]) -> str:
    try:
        probe()
    except ValidationFailure as exc:
        return exc.code
    return "unexpected-success"


def _forge_inverted_index(index_path: Path) -> None:
    connection = sqlite3.connect(index_path)
    try:
        original_summary = connection.execute(
            "SELECT c1 FROM records_fts_content WHERE c0 = ?",
            (FIRST_RECORD_ID,),
        ).fetchone()[0]
        connection.execute(
            "UPDATE records_fts SET summary = ? WHERE record_id = ?",
            (FORGED_SUMMARY, FIRST_RECORD_ID),
        )
        connection.execute(
            "UPDATE records_fts_content SET c1 = ? WHERE c0 = ?",
            (original_summary, FIRST_RECORD_ID),
        )
        connection.commit()
    finally:
        connection.close()


def run_projection_integrity_slice(fixture_root: Path, workspace: Path) -> dict[str, Any]:
    """Run the checked-in fixture without emitting machine-local paths."""
    record_paths = sorted((fixture_root / "records").glob("*.json"))
    clean_output = workspace / "clean-projection"
    projection_receipt = project_records(record_paths, clean_output)
    clean_index = clean_output / "records.sqlite"

    clean_term_record_ids = search_records(clean_index, "canonical")
    forged_term_clean_record_ids = search_records(clean_index, FORGED_TERM)
    clean_metadata_digest_matches = (
        projection_metadata(clean_index)["source_record_set_digest"]
        == projection_receipt["source_record_set_digest"]
    )

    tampered_index = workspace / "tampered.sqlite"
    shutil.copyfile(clean_index, tampered_index)
    _forge_inverted_index(tampered_index)

    surfaces: dict[str, Callable[[], object]] = {
        "search": lambda: search_records(tampered_index, FORGED_TERM),
        "related": lambda: related_records(tampered_index, FIRST_RECORD_ID),
        "provenance": lambda: records_with_provenance(tampered_index, PROVENANCE_REF),
        "metadata": lambda: projection_metadata(tampered_index),
        "logical-snapshot": lambda: logical_projection_snapshot(tampered_index),
    }
    gated_surface_outcomes = {name: _surface_outcome(probe) for name, probe in surfaces.items()}
    clean_control_record_ids = search_records(clean_index, "canonical")

    operations = [
        _operation("project-synthetic-records", projection_receipt["outcome"]),
        _operation("query-clean-index", "complete" if clean_metadata_digest_matches and not forged_term_clean_record_ids else "failed"),
        _operation("forge-inverted-index-two-step"),
        *(_operation(f"gate-{name}", "verified" if outcome == GATE_CODE else "failed") for name, outcome in gated_surface_outcomes.items()),
        _operation("query-clean-control-after-forgery", "complete" if clean_control_record_ids == clean_term_record_ids else "failed"),
    ]
    outcome = (
        "complete"
        if all(operation["outcome"] in {"complete", "verified"} for operation in operations)
        and clean_term_record_ids == [FIRST_RECORD_ID]
        else "failed"
    )
    body = {
        "outcome": outcome,
        "operations": operations,
        "projection": {
            "source_record_set_digest": projection_receipt["source_record_set_digest"],
            "record_count": projection_receipt["record_count"],
            "clean_term_record_ids": clean_term_record_ids,
            "forged_term_clean_record_ids": forged_term_clean_record_ids,
            "clean_metadata_digest_matches": clean_metadata_digest_matches,
        },
        "integrity_gate": {
            "tamper_sequence": ["reindex-forged-summary-through-records_fts", "restore-records_fts_content-row"],
            "forged_term": FORGED_TERM,
            "gated_surface_outcomes": gated_surface_outcomes,
            "clean_control_record_ids": clean_control_record_ids,
        },
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": [
            "runtimes whose PRAGMA integrity_check cannot reach the FTS5 inverted index (SQLite < 3.44) fail closed as projection-unavailable instead of serving unverifiable projections (capable runtime verified on 3.52.0)",
            "the cross-SQLite determinism matrix remains unverified",
            "canonical records are unaffected; the gate protects a generated, replaceable projection",
        ],
    }
    receipt = receipt_with_digest(
        "artifact-memory/projection-integrity-slice-receipt/v1",
        "projection-integrity-receipt://synthetic/",
        body,
    )
    validate(receipt, load_schema("core", "projection-integrity-slice-receipt.v1.schema.json"))
    return receipt
