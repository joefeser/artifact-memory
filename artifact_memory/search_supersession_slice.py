"""Provider-free synthetic proof for the supersession search filter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .canonical import receipt_with_digest
from .projection import project_records, search_receipt, search_records
from .schema_resources import load_schema
from .validator import validate


AUTHORITY_BOUNDARY = "informational-only/no-execution-authority"
LEDGER_QUERY = "ledger"
SURVIVOR_RECORD_ID = "record://synthetic/search-supersession-0001"
SUPERSEDED_RECORD_ID = "record://synthetic/search-supersession-0002"


def _operation(name: str, outcome: str = "complete") -> dict[str, str]:
    return {"name": name, "outcome": outcome}


def run_search_supersession_slice(fixture_root: Path, workspace: Path) -> dict[str, Any]:
    """Run the checked-in fixture without emitting machine-local paths."""
    record_paths = sorted((fixture_root / "records").glob("*.json"))
    output = workspace / "projection"
    projection_receipt = project_records(record_paths, output)
    index = output / "records.sqlite"

    default_ids = search_records(index, LEDGER_QUERY)
    default_returns_both = default_ids == [SURVIVOR_RECORD_ID, SUPERSEDED_RECORD_ID]
    filtered_ids = search_records(index, LEDGER_QUERY, exclude_superseded=True)
    filtered_returns_survivor = filtered_ids == [SURVIVOR_RECORD_ID]
    literal_filtered_ids = search_records(index, LEDGER_QUERY, literal=True, exclude_superseded=True)

    default_receipt = search_receipt(index, LEDGER_QUERY)
    filtered_receipt = search_receipt(index, LEDGER_QUERY, exclude_superseded=True)
    receipts_bind_exclusion = (
        default_receipt["exclude_superseded"] is False
        and default_receipt["record_ids"] == default_ids
        and filtered_receipt["exclude_superseded"] is True
        and filtered_receipt["record_ids"] == filtered_ids
        and filtered_receipt["source_record_set_digest"] == projection_receipt["source_record_set_digest"]
        and filtered_receipt["query_digest"] == default_receipt["query_digest"]
    )

    operations = [
        _operation("project-synthetic-records", projection_receipt["outcome"]),
        _operation("default-search-returns-both-lifecycles", "complete" if default_returns_both else "failed"),
        _operation("exclude-superseded-returns-survivor", "verified" if filtered_returns_survivor else "failed"),
        _operation("literal-mode-composes-with-exclusion", "complete" if literal_filtered_ids == [SURVIVOR_RECORD_ID] else "failed"),
        _operation("receipts-bind-exclusion", "complete" if receipts_bind_exclusion else "failed"),
    ]
    outcome = "complete" if all(operation["outcome"] in {"complete", "verified"} for operation in operations) else "failed"
    body = {
        "outcome": outcome,
        "operations": operations,
        "projection": {
            "source_record_set_digest": projection_receipt["source_record_set_digest"],
            "record_count": projection_receipt["record_count"],
        },
        "supersession_filter": {
            "query": LEDGER_QUERY,
            "default_record_ids": default_ids,
            "filtered_record_ids": filtered_ids,
            "literal_filtered_record_ids": literal_filtered_ids,
            "receipt_default_exclude_superseded": default_receipt["exclude_superseded"],
            "receipt_filtered_exclude_superseded": filtered_receipt["exclude_superseded"],
        },
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": [
            "exclusion is a read-time lifecycle filter; it is not revocation, which remains a projection-build input",
            "superseded records remain first-class hits by default; callers must opt in",
            "only lifecycle superseded is excluded; other non-current lifecycles are unaffected",
        ],
    }
    receipt_document = receipt_with_digest(
        "artifact-memory/search-supersession-slice-receipt/v1",
        "search-supersession-slice-receipt://synthetic/",
        body,
    )
    validate(receipt_document, load_schema("core", "search-supersession-slice-receipt.v1.schema.json"))
    return receipt_document
