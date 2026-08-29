#!/usr/bin/env python3
"""Self-contained SQLite probe for the cross-runtime matrix.

Tier A (always runs): builds the canonical FTS5 table over fixed synthetic
rows, performs the two-step inverted-index forgery, and reports whether
PRAGMA integrity_check detects it, plus fixed query results for determinism
comparison.

Tier B (runs when the artifact-memory package is importable): exercises the
real library — projection digests, default/literal/ranked search results,
and the typed outcome for a tampered index. Below the 3.44 runtime floor the
clean read itself must fail closed; above it the tampered read must fail
typed while the clean read succeeds.

Prints one JSON object on stdout. No repository writes, synthetic data only.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path


ROWS = [
    ("record://synthetic/matrix-0001", "beta beta beta beta beta gamma alpha", ""),
    ("record://synthetic/matrix-0002", "beta gamma gamma gamma gamma alpha", ""),
    ("record://synthetic/matrix-0003", "gamma alpha", ""),
]
FORGED_SUMMARY = "forged summary containing syntheticforged"


def tier_a() -> dict:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "probe.sqlite"
        connection = sqlite3.connect(path)
        connection.execute(
            "CREATE VIRTUAL TABLE records_fts USING fts5("
            "record_id UNINDEXED, summary, labels)"
        )
        connection.executemany("INSERT INTO records_fts VALUES (?, ?, ?)", ROWS)
        connection.commit()
        clean_default = [
            row[0]
            for row in connection.execute(
                "SELECT record_id FROM records_fts WHERE records_fts MATCH ? "
                "ORDER BY record_id",
                ("beta gamma",),
            )
        ]
        clean_ranked = [
            row[0]
            for row in connection.execute(
                "SELECT record_id FROM records_fts WHERE records_fts MATCH ? "
                "ORDER BY bm25(records_fts), record_id",
                ("beta gamma",),
            )
        ]
        original = connection.execute(
            "SELECT c1 FROM records_fts_content WHERE c0 = ?", (ROWS[0][0],)
        ).fetchone()[0]
        connection.execute(
            "UPDATE records_fts SET summary = ? WHERE record_id = ?",
            (FORGED_SUMMARY, ROWS[0][0]),
        )
        connection.execute(
            "UPDATE records_fts_content SET c1 = ? WHERE c0 = ?", (original, ROWS[0][0])
        )
        connection.commit()
        forged_served = [
            row[0]
            for row in connection.execute(
                "SELECT record_id FROM records_fts WHERE records_fts MATCH ?",
                ("syntheticforged",),
            )
        ]
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        connection.close()
    return {
        "clean_default_order": clean_default,
        "clean_ranked_order": clean_ranked,
        "forged_served_before_gate": forged_served,
        "integrity_check_detects_forgery": integrity != ["ok"],
        "integrity_check_rows": integrity[:3],
    }


def tier_b() -> dict:
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from artifact_memory.projection import project_records, search_records
        from artifact_memory.validator import ValidationFailure
    except Exception as exc:  # package unavailable in this interpreter
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}

    def record(ordinal: int, summary: str) -> dict:
        return {
            "schema_id": "artifact-memory/knowledge-record/v1",
            "record_id": f"record://synthetic/matrix-lib-{ordinal:04d}",
            "record_type": "note",
            "lifecycle": "accepted",
            "meaning": {"summary": summary},
            "artifact_refs": [],
            "provenance": [
                {"kind": "author", "source_ref": "fixture://synthetic/matrix/v1"}
            ],
            "sensitivity": "public",
        }

    summaries = (
        "beta beta beta beta beta gamma alpha",
        "beta gamma gamma gamma gamma alpha",
        "gamma alpha",
    )
    records = [
        record(ordinal, summary) for ordinal, summary in enumerate(summaries, start=1)
    ]
    result: dict = {"available": True}
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        paths = []
        for ordinal, payload in enumerate(records, start=1):
            path = workspace / f"record-{ordinal:04d}.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            paths.append(path)
        output = workspace / "projection"
        receipt = project_records(paths, output)
        result["source_record_set_digest"] = receipt["source_record_set_digest"]
        index = output / "records.sqlite"
        try:
            result["clean_default_order"] = search_records(index, "beta gamma")
            result["clean_ranked_order"] = search_records(index, "beta gamma", rank=True)
            result["clean_read_succeeded"] = True
        except ValidationFailure as exc:
            result["clean_read_succeeded"] = False
            result["clean_read_code"] = exc.code

        tampered = workspace / "tampered.sqlite"
        tampered.write_bytes(index.read_bytes())
        connection = sqlite3.connect(tampered)
        original = connection.execute(
            "SELECT c1 FROM records_fts_content WHERE c0 = ?", (records[0]["record_id"],)
        ).fetchone()[0]
        connection.execute(
            "UPDATE records_fts SET summary = ? WHERE record_id = ?",
            (FORGED_SUMMARY, records[0]["record_id"]),
        )
        connection.execute(
            "UPDATE records_fts_content SET c1 = ? WHERE c0 = ?",
            (original, records[0]["record_id"]),
        )
        connection.commit()
        connection.close()
        try:
            served = search_records(tampered, "syntheticforged")
            result["tampered_outcome"] = "UNEXPECTED-SUCCESS"
            result["tampered_served"] = served
        except ValidationFailure as exc:
            result["tampered_outcome"] = exc.code
    return result


def main() -> int:
    report = {
        "python_version": sys.version.split()[0],
        "sqlite_version": sqlite3.sqlite_version,
    }
    report["tier_a"] = tier_a()
    report["tier_b"] = tier_b()
    json.dump(report, sys.stdout, sort_keys=True)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
