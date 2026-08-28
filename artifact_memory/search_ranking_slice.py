"""Provider-free synthetic proof for conditional bm25 ranking."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .canonical import receipt_with_digest
from .projection import project_records, search_receipt, search_records
from .schema_resources import load_schema
from .validator import validate


AUTHORITY_BOUNDARY = "informational-only/no-execution-authority"
RANKING_QUERY = "beta gamma"
FIRST_RECORD_ID = "record://synthetic/search-ranking-0001"
SECOND_RECORD_ID = "record://synthetic/search-ranking-0002"
RESULT_ORDER_LABELS = {
    "ranking": "bm25",
    "tiebreak": "record-id",
    "authoritative": False,
    "corpus_dependent": True,
}


def _operation(name: str, outcome: str = "complete") -> dict[str, str]:
    return {"name": name, "outcome": outcome}


def run_search_ranking_slice(fixture_root: Path, workspace: Path) -> dict[str, Any]:
    """Run the checked-in fixture without emitting machine-local paths."""
    record_paths = sorted((fixture_root / "records").glob("*.json"))
    paired_output = workspace / "paired-projection"
    paired_receipt = project_records(record_paths[:3], paired_output)
    paired_index = paired_output / "records.sqlite"
    full_output = workspace / "full-projection"
    full_receipt = project_records(record_paths, full_output)
    full_index = full_output / "records.sqlite"

    unranked_ids = search_records(paired_index, RANKING_QUERY)
    paired_ranked_ids = search_records(paired_index, RANKING_QUERY, rank=True)
    relevance_inverts_record_order = (
        unranked_ids == [FIRST_RECORD_ID, SECOND_RECORD_ID]
        and paired_ranked_ids == [SECOND_RECORD_ID, FIRST_RECORD_ID]
    )

    full_ranked_ids = search_records(full_index, RANKING_QUERY, rank=True)
    corpus_growth_flips_ranking = (
        full_ranked_ids == [FIRST_RECORD_ID, SECOND_RECORD_ID]
        and full_ranked_ids != paired_ranked_ids
        and full_receipt["record_count"] == paired_receipt["record_count"] + 3
    )

    default_receipt = search_receipt(paired_index, RANKING_QUERY)
    ranked_receipt = search_receipt(paired_index, RANKING_QUERY, rank=True)
    receipts_label_order = (
        "result_order" not in default_receipt
        and ranked_receipt["result_order"] == RESULT_ORDER_LABELS
        and ranked_receipt["record_ids"] == paired_ranked_ids
        and ranked_receipt["source_record_set_digest"] == paired_receipt["source_record_set_digest"]
    )

    operations = [
        _operation("project-paired-and-full-corpora", "complete" if full_receipt["outcome"] == "complete" else "failed"),
        _operation("bm25-inverts-record-id-order", "verified" if relevance_inverts_record_order else "failed"),
        _operation("corpus-growth-flips-ranked-order", "verified" if corpus_growth_flips_ranking else "failed"),
        _operation("receipts-label-order-non-authoritative", "complete" if receipts_label_order else "failed"),
    ]
    outcome = "complete" if all(operation["outcome"] in {"complete", "verified"} for operation in operations) else "failed"
    body = {
        "outcome": outcome,
        "operations": operations,
        "projection": {
            "paired_source_record_set_digest": paired_receipt["source_record_set_digest"],
            "full_source_record_set_digest": full_receipt["source_record_set_digest"],
            "paired_record_count": paired_receipt["record_count"],
            "full_record_count": full_receipt["record_count"],
        },
        "ranked_search": {
            "query": RANKING_QUERY,
            "unranked_record_ids": unranked_ids,
            "paired_ranked_record_ids": paired_ranked_ids,
            "full_ranked_record_ids": full_ranked_ids,
            "receipt_result_order": RESULT_ORDER_LABELS,
            "default_receipt_omits_result_order": "result_order" not in default_receipt,
        },
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": [
            "ranked order is corpus-dependent: adding three lexically unrelated records (no query terms) changed the order in this proof, and any result's rank can shift when the vault changes",
            "ranked order is a findability aid, never an authority or relevance claim about record truth",
            "bm25 cost and flip reachability at vault scale remain unmeasured; ties break deterministically by record_id",
        ],
    }
    receipt_document = receipt_with_digest(
        "artifact-memory/search-ranking-slice-receipt/v1",
        "search-ranking-slice-receipt://synthetic/",
        body,
    )
    validate(receipt_document, load_schema("core", "search-ranking-slice-receipt.v1.schema.json"))
    return receipt_document
