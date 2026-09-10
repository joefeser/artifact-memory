"""Provider-free synthetic proof for literal search mode and error-code classification."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .canonical import receipt_with_digest, sha256_bytes
from .projection import project_records, search_receipt, search_records
from .schema_resources import load_schema
from .validator import ValidationFailure, validate


AUTHORITY_BOUNDARY = "informational-only/no-execution-authority"
HYPHENATED_QUERY = "alpha-beta"
SPACED_QUERY = "alpha beta"
QUOTED_QUERY = 'five "inches'
CASEFOLD_PHRASE_QUERY = "straße"
CASEFOLD_SYMBOL_QUERY = "ss"
ADJACENT_RECORD_ID = "record://synthetic/search-literal-0001"
SPACED_RECORD_ID = "record://synthetic/search-literal-0004"
QUOTED_RECORD_ID = "record://synthetic/search-literal-0003"
CASEFOLD_PHRASE_RECORD_IDS = [
    "record://synthetic/search-literal-0005",
    "record://synthetic/search-literal-0006",
]
CASEFOLD_SYMBOL_RECORD_ID = "record://synthetic/search-literal-0007"


def _operation(name: str, outcome: str = "complete") -> dict[str, str]:
    return {"name": name, "outcome": outcome}


def _typed_outcome(probe) -> str:
    try:
        probe()
        return "unexpected-success"
    except ValidationFailure as exc:
        return exc.code


def run_search_literal_slice(fixture_root: Path, workspace: Path) -> dict[str, Any]:
    """Run the checked-in fixture without emitting machine-local paths."""
    record_paths = sorted((fixture_root / "records").glob("*.json"))
    output = workspace / "projection"
    projection_receipt = project_records(record_paths, output)
    index = output / "records.sqlite"

    literal_matches = search_records(index, HYPHENATED_QUERY, literal=True)
    literal_adjacent_only = literal_matches == [ADJACENT_RECORD_ID]
    spaced_matches = search_records(index, SPACED_QUERY, literal=True)
    punctuation_is_significant = (
        literal_adjacent_only
        and spaced_matches == [SPACED_RECORD_ID]
        and SPACED_RECORD_ID not in literal_matches
    )
    raw_hyphenated_outcome = _typed_outcome(lambda: search_records(index, HYPHENATED_QUERY))

    quoted_matches = search_records(index, QUOTED_QUERY, literal=True)
    quoted_literal_match = quoted_matches == [QUOTED_RECORD_ID]
    raw_quoted_outcome = _typed_outcome(lambda: search_records(index, QUOTED_QUERY))
    empty_literal_outcome = _typed_outcome(lambda: search_records(index, "", literal=True))
    casefold_phrase_matches = search_records(index, CASEFOLD_PHRASE_QUERY, literal=True)
    casefold_symbol_matches = search_records(index, CASEFOLD_SYMBOL_QUERY, literal=True)
    expanding_casefold_equivalence = (
        casefold_phrase_matches == CASEFOLD_PHRASE_RECORD_IDS
        and casefold_symbol_matches == [CASEFOLD_SYMBOL_RECORD_ID]
        and search_receipt(index, CASEFOLD_PHRASE_QUERY, literal=True)["record_ids"]
        == CASEFOLD_PHRASE_RECORD_IDS
    )

    literal_receipt = search_receipt(index, HYPHENATED_QUERY, literal=True)
    raw_receipt = search_receipt(index, "adjacent")
    receipt_binds_mode_and_typed_query = (
        literal_receipt["record_ids"] == [ADJACENT_RECORD_ID]
        and literal_receipt["query_mode"] == "literal"
        and literal_receipt["query_digest"] == sha256_bytes(HYPHENATED_QUERY.encode("utf-8"))
        and raw_receipt["query_mode"] == "raw"
        and literal_receipt["source_record_set_digest"] == projection_receipt["source_record_set_digest"]
    )

    operations = [
        _operation("project-synthetic-records", projection_receipt["outcome"]),
        _operation("literal-hyphenated-phrase-matches-adjacent-only", "complete" if literal_adjacent_only else "failed"),
        _operation("literal-punctuation-is-significant", "verified" if punctuation_is_significant else "failed"),
        _operation("raw-hyphenated-query-typed-invalid", "verified" if raw_hyphenated_outcome == "query-invalid" else "failed"),
        _operation("literal-embedded-quote-doubled", "complete" if quoted_literal_match else "failed"),
        _operation("raw-unterminated-quote-typed-invalid", "verified" if raw_quoted_outcome == "query-invalid" else "failed"),
        _operation("empty-literal-query-typed-invalid", "verified" if empty_literal_outcome == "query-invalid" else "failed"),
        _operation("literal-expanding-unicode-casefold-equivalent", "verified" if expanding_casefold_equivalence else "failed"),
        _operation("receipt-binds-mode-and-typed-query", "complete" if receipt_binds_mode_and_typed_query else "failed"),
    ]
    outcome = "complete" if all(operation["outcome"] in {"complete", "verified"} for operation in operations) else "failed"
    body = {
        "outcome": outcome,
        "operations": operations,
        "projection": {
            "source_record_set_digest": projection_receipt["source_record_set_digest"],
            "record_count": projection_receipt["record_count"],
        },
        "literal_search": {
            "hyphenated_query": HYPHENATED_QUERY,
            "adjacent_record_ids": literal_matches,
            "spaced_query_record_ids": spaced_matches,
            "raw_hyphenated_outcome": raw_hyphenated_outcome,
            "quoted_query_outcome": "matched-with-doubled-quotes" if quoted_literal_match else "failed",
            "raw_quoted_outcome": raw_quoted_outcome,
            "empty_literal_outcome": empty_literal_outcome,
            "casefold_phrase_query": CASEFOLD_PHRASE_QUERY,
            "casefold_phrase_record_ids": casefold_phrase_matches,
            "casefold_symbol_query": CASEFOLD_SYMBOL_QUERY,
            "casefold_symbol_record_ids": casefold_symbol_matches,
            "receipt_binds_mode_and_typed_query": receipt_binds_mode_and_typed_query,
        },
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": [
            "literal mode accepts one query string, including adjacent multiword phrases, and fully case-folds the validated indexed text so expanding Unicode folds remain equivalent while punctuation stays significant",
            "raw mode remains the default and still exposes full FTS5 query syntax",
            "only meaning.summary and labels are lexically indexed; other record fields are unreachable from search",
        ],
    }
    receipt_document = receipt_with_digest(
        "artifact-memory/search-literal-slice-receipt/v1",
        "search-literal-slice-receipt://synthetic/",
        body,
    )
    validate(receipt_document, load_schema("core", "search-literal-slice-receipt.v1.schema.json"))
    return receipt_document
