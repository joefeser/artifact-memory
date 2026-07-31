"""Deterministic, rebuildable projections from canonical knowledge records."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .canonical import canonical_bytes
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, validate


_canonical = canonical_bytes


def _knowledge_schema() -> dict[str, Any]:
    return load_schema("core", "knowledge-record.v1.schema.json")


def canonical_records(record_paths: Iterable[Path]) -> list[dict[str, Any]]:
    records = []
    for record_path in record_paths:
        try:
            record = load_json(record_path)
            if not isinstance(record, dict):
                raise ValidationFailure("invalid-input", "canonical record must be an object")
            validate(record, _knowledge_schema())
        except ValidationFailure as exc:
            raise ValidationFailure("record-rejected", "canonical record failed projection validation") from exc
        records.append(record)
    records.sort(key=lambda record: record["record_id"])
    if len({record["record_id"] for record in records}) != len(records):
        raise ValidationFailure("duplicate-record-id", "canonical record IDs must be unique")
    return records


def _record_lines(records: list[dict[str, Any]]) -> bytes:
    return b"".join(_canonical(record) + b"\n" for record in records)


def _create_sqlite(path: Path, records: list[dict[str, Any]], source_digest: str) -> None:
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE records (
            record_id TEXT PRIMARY KEY,
            record_type TEXT NOT NULL,
            lifecycle TEXT NOT NULL,
            sensitivity TEXT,
            record_json TEXT NOT NULL,
            source_record_set_digest TEXT NOT NULL
        );
        CREATE TABLE relationships (
            source_record_id TEXT NOT NULL,
            relationship_type TEXT NOT NULL,
            target_ref TEXT NOT NULL,
            PRIMARY KEY (source_record_id, relationship_type, target_ref)
        );
        CREATE INDEX relationships_target_idx ON relationships(target_ref);
        CREATE VIRTUAL TABLE records_fts USING fts5(record_id UNINDEXED, summary, labels);
    """)
    for record in records:
        connection.execute("INSERT INTO records VALUES (?, ?, ?, ?, ?, ?)", (record["record_id"], record["record_type"], record["lifecycle"], record.get("sensitivity"), _canonical(record).decode("utf-8"), source_digest))
        meaning = record["meaning"]
        connection.execute("INSERT INTO records_fts VALUES (?, ?, ?)", (record["record_id"], meaning["summary"], " ".join(meaning.get("labels", []))))
        for relationship in record.get("relationships", []):
            connection.execute("INSERT INTO relationships VALUES (?, ?, ?)", (record["record_id"], relationship["type"], relationship["target_ref"]))
    connection.commit()
    connection.close()


def project_records(record_paths: Iterable[Path], output_dir: Path) -> dict[str, Any]:
    records = canonical_records(record_paths)
    lines = _record_lines(records)
    source_digest = "sha-256:" + hashlib.sha256(lines).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    receipt = {"schema_id": "artifact-memory/projection-receipt/v1", "outcome": "complete", "record_count": len(records), "source_record_set_digest": source_digest, "generated_views": ["ndjson", "sqlite", "fts", "relationships"], "diagnostics": []}
    with tempfile.TemporaryDirectory(prefix=".projection-", dir=output_dir) as temporary:
        staging = Path(temporary)
        (staging / "records.ndjson").write_bytes(lines)
        _create_sqlite(staging / "records.sqlite", records, source_digest)
        (staging / "projection-receipt.json").write_text(
            json.dumps(receipt, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        for name in ("records.ndjson", "records.sqlite", "projection-receipt.json"):
            os.replace(staging / name, output_dir / name)
    return receipt


def search_records(index_path: Path, query: str) -> list[str]:
    connection = sqlite3.connect(index_path)
    try:
        return [row[0] for row in connection.execute("SELECT record_id FROM records_fts WHERE records_fts MATCH ? ORDER BY record_id", (query,))]
    finally:
        connection.close()


def related_records(index_path: Path, record_id: str) -> list[dict[str, str]]:
    connection = sqlite3.connect(index_path)
    try:
        return [{"type": row[0], "target_ref": row[1]} for row in connection.execute("SELECT relationship_type, target_ref FROM relationships WHERE source_record_id = ? ORDER BY relationship_type, target_ref", (record_id,))]
    finally:
        connection.close()
