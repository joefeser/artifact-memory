"""Deterministic, rebuildable projections from canonical knowledge records."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from .canonical import canonical_bytes
from .schema_resources import load_contract_text, load_schema
from .validator import ValidationFailure, load_json, validate


_canonical = canonical_bytes
PROJECTION_SCHEMA_ID = "artifact-memory/sqlite-projection/v1"
PROJECTION_USER_VERSION = 1


def _knowledge_schema() -> dict[str, Any]:
    return load_schema("core", "knowledge-record.v1.schema.json")


@contextmanager
def _read_index(index_path: Path) -> Iterator[sqlite3.Connection]:
    try:
        connection = sqlite3.connect(index_path.resolve().as_uri() + "?mode=ro", uri=True)
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise ValidationFailure("projection-unavailable", "generated SQLite projection is unavailable or invalid") from exc
    try:
        yield connection
    finally:
        connection.close()


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
    try:
        connection.executescript(load_contract_text("core", "index-sqlite.v1.sql"))
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        if user_version != PROJECTION_USER_VERSION:
            raise ValidationFailure("projection-schema-mismatch", "packaged SQLite projection contract has an unsupported version")
        connection.execute(
            "INSERT INTO projection_metadata VALUES (1, ?, ?, ?, ?)",
            (PROJECTION_SCHEMA_ID, "artifact-memory/canonical-json/v0", source_digest, len(records)),
        )
        for record in records:
            connection.execute(
                "INSERT INTO records VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record["record_id"],
                    record["record_type"],
                    record["lifecycle"],
                    record.get("sensitivity"),
                    _canonical(record).decode("utf-8"),
                    source_digest,
                ),
            )
            meaning = record["meaning"]
            connection.execute(
                "INSERT INTO records_fts VALUES (?, ?, ?)",
                (record["record_id"], meaning["summary"], " ".join(meaning.get("labels", []))),
            )
            for ordinal, provenance in enumerate(record["provenance"]):
                connection.execute(
                    "INSERT INTO provenance VALUES (?, ?, ?, ?)",
                    (record["record_id"], ordinal, provenance["kind"], provenance["source_ref"]),
                )
            for relationship in record.get("relationships", []):
                connection.execute(
                    "INSERT INTO relationships VALUES (?, ?, ?)",
                    (record["record_id"], relationship["type"], relationship["target_ref"]),
                )
        connection.commit()
    finally:
        connection.close()


def project_records(record_paths: Iterable[Path], output_dir: Path) -> dict[str, Any]:
    records = canonical_records(record_paths)
    lines = _record_lines(records)
    source_digest = "sha-256:" + hashlib.sha256(lines).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema_id": "artifact-memory/projection-receipt/v1",
        "outcome": "complete",
        "record_count": len(records),
        "source_record_set_digest": source_digest,
        "generated_views": ["ndjson", "sqlite", "metadata", "provenance", "fts", "relationships"],
        "diagnostics": [],
    }
    validate(receipt, load_schema("core", "projection-receipt.v1.schema.json"))
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
    try:
        with _read_index(index_path) as connection:
            return [row[0] for row in connection.execute("SELECT record_id FROM records_fts WHERE records_fts MATCH ? ORDER BY record_id", (query,))]
    except sqlite3.Error as exc:
        raise ValidationFailure("query-invalid", "full-text query is invalid or unsupported") from exc


def related_records(index_path: Path, record_id: str) -> list[dict[str, str]]:
    try:
        with _read_index(index_path) as connection:
            return [{"type": row[0], "target_ref": row[1]} for row in connection.execute("SELECT relationship_type, target_ref FROM relationships WHERE source_record_id = ? ORDER BY relationship_type, target_ref", (record_id,))]
    except sqlite3.Error as exc:
        raise ValidationFailure("projection-unavailable", "generated SQLite projection is unavailable or invalid") from exc


def records_with_provenance(index_path: Path, source_ref: str) -> list[dict[str, str]]:
    try:
        with _read_index(index_path) as connection:
            return [
                {"record_id": row[0], "kind": row[1], "source_ref": row[2]}
                for row in connection.execute(
                    "SELECT record_id, provenance_kind, source_ref FROM provenance WHERE source_ref = ? ORDER BY record_id, ordinal",
                    (source_ref,),
                )
            ]
    except sqlite3.Error as exc:
        raise ValidationFailure("projection-unavailable", "generated SQLite projection is unavailable or invalid") from exc


def projection_metadata(index_path: Path) -> dict[str, Any]:
    try:
        with _read_index(index_path) as connection:
            user_version = connection.execute("PRAGMA user_version").fetchone()[0]
            row = connection.execute(
                "SELECT projection_schema_id, canonical_json_profile, source_record_set_digest, record_count FROM projection_metadata WHERE singleton_id = 1"
            ).fetchone()
            if row is None:
                raise ValidationFailure("projection-metadata-missing", "generated index has no projection metadata")
            return {
                "projection_schema_id": row[0],
                "user_version": user_version,
                "canonical_json_profile": row[1],
                "source_record_set_digest": row[2],
                "record_count": row[3],
            }
    except sqlite3.Error as exc:
        raise ValidationFailure("projection-unavailable", "generated SQLite projection is unavailable or invalid") from exc


def logical_projection_snapshot(index_path: Path) -> dict[str, Any]:
    """Return stable logical rows for delete-and-rebuild conformance checks."""
    try:
        with _read_index(index_path) as connection:
            user_version = connection.execute("PRAGMA user_version").fetchone()[0]
            metadata = connection.execute(
                "SELECT projection_schema_id, canonical_json_profile, source_record_set_digest, record_count FROM projection_metadata WHERE singleton_id = 1"
            ).fetchall()
            records = connection.execute(
                "SELECT record_id, record_type, lifecycle, sensitivity, record_json, source_record_set_digest FROM records ORDER BY record_id"
            ).fetchall()
            provenance = connection.execute(
                "SELECT record_id, ordinal, provenance_kind, source_ref FROM provenance ORDER BY record_id, ordinal"
            ).fetchall()
            relationships = connection.execute(
                "SELECT source_record_id, relationship_type, target_ref FROM relationships ORDER BY source_record_id, relationship_type, target_ref"
            ).fetchall()
            search_rows = connection.execute(
                "SELECT record_id, summary, labels FROM records_fts ORDER BY record_id"
            ).fetchall()
            return {
                "user_version": user_version,
                "metadata": [list(row) for row in metadata],
                "records": [list(row) for row in records],
                "provenance": [list(row) for row in provenance],
                "relationships": [list(row) for row in relationships],
                "search_rows": [list(row) for row in search_rows],
            }
    except sqlite3.Error as exc:
        raise ValidationFailure("projection-unavailable", "generated SQLite projection is unavailable or invalid") from exc
