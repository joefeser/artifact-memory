"""Provider-free synthetic proof for scan, diff, and generated projections."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .canonical import receipt_with_digest
from .projection import (
    logical_projection_snapshot,
    project_records,
    records_with_provenance,
    related_records,
    search_records,
)
from .scan import diff_manifests, scan_path, verify_path
from .schema_resources import load_schema
from .validator import validate


PROVENANCE_REF = "fixture://synthetic/scan-projection/v1"
AUTHORITY_BOUNDARY = "informational-only/no-execution-authority"


def _operation(name: str, outcome: str = "complete") -> dict[str, str]:
    return {"name": name, "outcome": outcome}


def run_scan_projection_slice(fixture_root: Path, workspace: Path) -> dict[str, Any]:
    """Run the checked-in fixture without emitting machine-local paths."""
    before_manifest, before_scan = scan_path(fixture_root / "before")
    after_manifest, after_scan = scan_path(fixture_root / "after")
    before_verification = verify_path(fixture_root / "before", before_manifest)
    after_verification = verify_path(fixture_root / "after", after_manifest)
    diff = diff_manifests(before_manifest, after_manifest)

    record_paths = sorted((fixture_root / "records").glob("*.json"))
    first_output = workspace / "first-projection"
    second_output = workspace / "second-projection"
    first_receipt = project_records(reversed(record_paths), first_output)
    second_receipt = project_records(record_paths, second_output)
    first_ndjson = (first_output / "records.ndjson").read_bytes()
    first_snapshot = logical_projection_snapshot(first_output / "records.sqlite")
    order_independent = (
        first_receipt == second_receipt
        and first_ndjson == (second_output / "records.ndjson").read_bytes()
        and first_snapshot == logical_projection_snapshot(second_output / "records.sqlite")
    )

    search_result = search_records(first_output / "records.sqlite", "portable")
    relationship_result = related_records(
        first_output / "records.sqlite",
        "record://synthetic/scan-projection-0001",
    )
    provenance_result = records_with_provenance(first_output / "records.sqlite", PROVENANCE_REF)

    for name in ("records.ndjson", "records.sqlite", "projection-receipt.json"):
        (first_output / name).unlink()
    deleted_before_rebuild = not any(first_output.iterdir())
    rebuilt_receipt = project_records(record_paths, first_output)
    rebuild_equivalent = (
        rebuilt_receipt == first_receipt
        and (first_output / "records.ndjson").read_bytes() == first_ndjson
        and logical_projection_snapshot(first_output / "records.sqlite") == first_snapshot
    )

    operations = [
        _operation("scan-before", before_scan["outcome"]),
        _operation("scan-after", after_scan["outcome"]),
        _operation("verify-before", before_verification["outcome"]),
        _operation("verify-after", after_verification["outcome"]),
        _operation("content-tree-diff", diff["outcome"]),
        _operation("project-canonical-records", first_receipt["outcome"]),
        _operation("query-full-text-relationships-provenance"),
        _operation("delete-generated-views", "complete" if deleted_before_rebuild else "failed"),
        _operation("rebuild-generated-views", "complete" if rebuild_equivalent else "failed"),
    ]
    outcome = "complete" if all(operation["outcome"] in {"complete", "verified"} for operation in operations) and order_independent else "failed"
    body = {
        "outcome": outcome,
        "operations": operations,
        "before_manifest_ref": before_manifest["manifest_id"],
        "after_manifest_ref": after_manifest["manifest_id"],
        "diff": {
            "outcome": diff["outcome"],
            "added": diff["added"],
            "removed": diff["removed"],
            "changed": diff["changed"],
            "moved_candidates": diff["moved_candidates"],
        },
        "projection": {
            "source_record_set_digest": first_receipt["source_record_set_digest"],
            "record_count": first_receipt["record_count"],
            "order_independent": order_independent,
            "deleted_before_rebuild": deleted_before_rebuild,
            "logical_rebuild_equivalent": rebuild_equivalent,
            "full_text_record_ids": search_result,
            "relationships": relationship_result,
            "provenance_record_ids": [item["record_id"] for item in provenance_result],
        },
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": [
            "moved-candidate is content/tree evidence only and does not prove semantic continuity",
            "SQLite file bytes are replaceable and are not canonical identity",
        ],
    }
    receipt = receipt_with_digest(
        "artifact-memory/scan-projection-slice-receipt/v1",
        "scan-projection-receipt://synthetic/",
        body,
    )
    validate(receipt, load_schema("core", "scan-projection-slice-receipt.v1.schema.json"))
    return receipt
