"""Provider-free synthetic proof for digest-bearing search receipts."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from .canonical import receipt_with_digest
from .cli import main as cli_main
from .projection import (
    project_records,
    search_receipt,
    search_records,
)
from .schema_resources import load_schema
from .validator import ValidationFailure, validate


AUTHORITY_BOUNDARY = "informational-only/no-execution-authority"
PINNED_TERM = "pinned"
FIRST_RECORD_ID = "record://synthetic/search-receipt-0001"


def _operation(name: str, outcome: str = "complete") -> dict[str, str]:
    return {"name": name, "outcome": outcome}


def _cli_capture(*args: str) -> tuple[int, str]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exit_code = cli_main(list(args))
    return exit_code, buffer.getvalue()


def _forge_inverted_index(index_path: Path) -> None:
    connection = sqlite3.connect(index_path)
    try:
        original_summary = connection.execute(
            "SELECT c1 FROM records_fts_content WHERE c0 = ?",
            (FIRST_RECORD_ID,),
        ).fetchone()[0]
        connection.execute(
            "UPDATE records_fts SET summary = ? WHERE record_id = ?",
            ("synthetic forged summary advertising syntheticforged", FIRST_RECORD_ID),
        )
        connection.execute(
            "UPDATE records_fts_content SET c1 = ? WHERE c0 = ?",
            (original_summary, FIRST_RECORD_ID),
        )
        connection.commit()
    finally:
        connection.close()


def run_search_receipt_slice(fixture_root: Path, workspace: Path) -> dict[str, Any]:
    """Run the checked-in fixture without emitting machine-local paths."""
    record_paths = sorted((fixture_root / "records").glob("*.json"))
    output = workspace / "projection"
    projection_receipt = project_records(record_paths, output)
    index = output / "records.sqlite"

    receipt = search_receipt(index, PINNED_TERM)
    raw_record_ids = search_records(index, PINNED_TERM)
    digest_matches_projection = (
        receipt["source_record_set_digest"] == projection_receipt["source_record_set_digest"]
    )
    matches_raw_search = receipt["record_ids"] == raw_record_ids and raw_record_ids == [FIRST_RECORD_ID]

    cli_exit_code, cli_json_out = _cli_capture("search-receipt", str(index), PINNED_TERM, "--json")
    cli_json_receipt_equals_library = cli_exit_code == 0 and json.loads(cli_json_out) == receipt
    human_exit_code, cli_human_out = _cli_capture("search-receipt", str(index), PINNED_TERM)
    cli_human_receipt_names_digest = (
        human_exit_code == 0 and f"source_record_set_digest: {receipt['source_record_set_digest']}" in cli_human_out
    )

    rejected_exit_code, rejected_json_out = _cli_capture("search-receipt", str(index), '"', "--json")
    invalid_query_typed = (
        rejected_exit_code == 2
        and json.loads(rejected_json_out)["diagnostics"][0]["code"] == "query-invalid"
    )

    tampered_index = workspace / "tampered.sqlite"
    shutil.copyfile(index, tampered_index)
    _forge_inverted_index(tampered_index)
    try:
        search_receipt(tampered_index, "syntheticforged")
        tampered_outcome = "unexpected-success"
    except ValidationFailure as exc:
        tampered_outcome = exc.code

    operations = [
        _operation("project-synthetic-records", projection_receipt["outcome"]),
        _operation("issue-digest-bearing-search-receipt", "complete" if digest_matches_projection and matches_raw_search else "failed"),
        _operation("pin-receipt-through-cli", "complete" if cli_json_receipt_equals_library and cli_human_receipt_names_digest else "failed"),
        _operation("reject-invalid-query-typed", "verified" if invalid_query_typed else "failed"),
        _operation("refuse-tampered-index", "verified" if tampered_outcome == "projection-unavailable" else "failed"),
    ]
    outcome = "complete" if all(operation["outcome"] in {"complete", "verified"} for operation in operations) else "failed"
    body = {
        "outcome": outcome,
        "operations": operations,
        "projection": {
            "source_record_set_digest": projection_receipt["source_record_set_digest"],
            "record_count": projection_receipt["record_count"],
        },
        "search_receipt": {
            "query": PINNED_TERM,
            "record_ids": receipt["record_ids"],
            "integrity_gate": receipt["integrity_gate"],
            "digest_matches_projection": digest_matches_projection,
            "matches_raw_search": matches_raw_search,
            "cli_json_receipt_equals_library_receipt": cli_json_receipt_equals_library,
            "cli_human_receipt_names_digest": cli_human_receipt_names_digest,
        },
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": [
            "the receipt pins results to the exact canonical record set that produced the index; it does not certify record truth",
            "the raw search_records surface is deliberately unchanged; the receipt is additive only",
            "relevance ordering remains record_id-only until conditional bm25 lands",
        ],
    }
    receipt_document = receipt_with_digest(
        "artifact-memory/search-receipt-slice-receipt/v1",
        "search-receipt-slice-receipt://synthetic/",
        body,
    )
    validate(receipt_document, load_schema("core", "search-receipt-slice-receipt.v1.schema.json"))
    return receipt_document
