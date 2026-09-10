"""Deterministic, rebuildable projections from canonical knowledge records."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Iterator

from .canonical import canonical_bytes, sha256_bytes
from .extensions import (
    ExtensionFailure,
    is_required_declaration,
    preserve_extensions,
    validate_extension_identifiers,
)
from .knowledge import knowledge_schema
from .schema_resources import load_contract_text, load_schema
from .validator import ValidationFailure, load_json, validate


_canonical = canonical_bytes
PROJECTION_SCHEMA_ID = "artifact-memory/sqlite-projection/v1"
PROJECTION_USER_VERSION = 1
CANONICAL_JSON_PROFILE = "artifact-memory/canonical-json/v0"
_LEGACY_RECORD_SCHEMA_ID = "artifact-memory/knowledge-record/v1"
_DIGEST_PATTERN = re.compile(r"^sha-256:[0-9a-f]{64}$")
_REQUIRED_COLUMNS = {
    "projection_metadata": ["singleton_id", "projection_schema_id", "canonical_json_profile", "source_record_set_digest", "record_count"],
    "records": ["record_id", "record_type", "lifecycle", "sensitivity", "record_json", "source_record_set_digest"],
    "provenance": ["record_id", "ordinal", "provenance_kind", "source_ref"],
    "relationships": ["source_record_id", "relationship_type", "target_ref"],
    "records_fts": ["record_id", "summary", "labels"],
}
_REQUIRED_INDEXES = {
    "records_type_idx": ["record_type", "record_id"],
    "records_lifecycle_idx": ["lifecycle", "record_id"],
    "provenance_source_idx": ["source_ref", "record_id"],
    "relationships_target_idx": ["target_ref", "source_record_id"],
}


_knowledge_schema = knowledge_schema
_FTS_DECLARATION_PATTERN = re.compile(
    r"CREATE\s+VIRTUAL\s+TABLE\s+records_fts\s+USING\s+fts5\s*\([^;]*\)",
    re.IGNORECASE | re.DOTALL,
)


def _normalized_declaration(statement: str) -> str:
    """Normalize SQL spelling without changing quoted-token semantics.

    The packaged contract and sqlite_master may differ in keyword case or
    insignificant whitespace. Quoted strings and identifiers are opaque:
    their case, whitespace, and doubled-quote escapes remain exact so a future
    semantic literal cannot be normalized into a different value.
    """
    normalized: list[str] = []
    closing_quote: str | None = None
    index = 0
    while index < len(statement):
        character = statement[index]
        if closing_quote is not None:
            normalized.append(character)
            if character == closing_quote:
                doubled_quote = (
                    closing_quote != "]"
                    and index + 1 < len(statement)
                    and statement[index + 1] == closing_quote
                )
                if doubled_quote:
                    normalized.append(statement[index + 1])
                    index += 1
                else:
                    closing_quote = None
        elif character in {"'", '"', "`"}:
            closing_quote = character
            normalized.append(character)
        elif character == "[":
            closing_quote = "]"
            normalized.append(character)
        elif not character.isspace():
            normalized.append(character.lower())
        index += 1
    return "".join(normalized)


@lru_cache(maxsize=1)
def _contract_schema_objects() -> tuple[dict[str, tuple[str, str | None]], dict[str, str]]:
    """Materialize the packaged contract through this SQLite runtime.

    SQLite owns autoindexes and FTS5 shadow-table declarations. Their names and
    object types are still part of the expected generated database, while only
    the ordinary application tables and explicit indexes have declarations
    authored by this package that can be compared byte-semantically after
    whitespace normalization.
    """
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(load_contract_text("core", "index-sqlite.v1.sql"))
        rows = connection.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_autoindex_%' ORDER BY type, name"
        ).fetchall()
    finally:
        connection.close()
    objects = {name: (object_type, sql) for object_type, name, sql in rows}
    authored_names = {
        "projection_metadata",
        "records",
        "provenance",
        "relationships",
        *list(_REQUIRED_INDEXES),
    }
    declarations = {
        name: _normalized_declaration(objects[name][1] or "")
        for name in authored_names
    }
    return objects, declarations


_CONTRACT_FTS_DECLARATION_MATCH = _FTS_DECLARATION_PATTERN.search(
    load_contract_text("core", "index-sqlite.v1.sql")
)
assert _CONTRACT_FTS_DECLARATION_MATCH is not None, "packaged projection contract lacks the records_fts declaration"
_CANONICAL_FTS_DECLARATION = _normalized_declaration(_CONTRACT_FTS_DECLARATION_MATCH.group(0))


@lru_cache(maxsize=1)
def _runtime_verifies_fts5_integrity() -> bool:
    """Prove this loaded SQLite/FTS5 combination detects the known forgery."""
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE VIRTUAL TABLE integrity_probe USING fts5(record_id UNINDEXED, summary)")
        connection.execute("INSERT INTO integrity_probe VALUES ('record://synthetic/probe', 'original')")
        original = connection.execute(
            "SELECT c1 FROM integrity_probe_content WHERE c0 = 'record://synthetic/probe'"
        ).fetchone()[0]
        connection.execute(
            "UPDATE integrity_probe SET summary = 'forged synthetic probe' "
            "WHERE record_id = 'record://synthetic/probe'"
        )
        connection.execute(
            "UPDATE integrity_probe_content SET c1 = ? WHERE c0 = 'record://synthetic/probe'",
            (original,),
        )
        rows = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        return rows != ["ok"]
    except sqlite3.Error:
        return False
    finally:
        connection.close()


def _validate_projection_contract(connection: sqlite3.Connection) -> None:
    user_version = connection.execute("PRAGMA user_version").fetchone()[0]
    if type(user_version) is not int or user_version != PROJECTION_USER_VERSION:
        raise ValidationFailure("projection-schema-mismatch", "generated index uses an unsupported SQLite projection version")
    schema_rows = connection.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_autoindex_%' ORDER BY type, name"
    ).fetchall()
    actual_objects = {name: (object_type, sql) for object_type, name, sql in schema_rows}
    contract_objects, contract_declarations = _contract_schema_objects()
    expected_object_types = {name: object_type for name, (object_type, _) in contract_objects.items()}
    actual_object_types = {
        name: object_type for name, (object_type, _) in actual_objects.items()
    }
    if actual_object_types != expected_object_types:
        raise ValidationFailure("projection-unavailable", "generated SQLite projection object set is incomplete or invalid")
    for name, expected_declaration in contract_declarations.items():
        if _normalized_declaration(actual_objects[name][1] or "") != expected_declaration:
            raise ValidationFailure("projection-unavailable", "generated SQLite projection object definition is invalid")
    for table, expected_columns in _REQUIRED_COLUMNS.items():
        actual_columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
        if actual_columns != expected_columns:
            raise ValidationFailure("projection-unavailable", "generated SQLite projection schema is incomplete or invalid")
    fts_declaration = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'records_fts'"
    ).fetchone()
    declaration = (fts_declaration[0] if fts_declaration is not None and fts_declaration[0] else "") or ""
    # The exact FTS declaration is part of the projection contract: a recreated
    # table with the same columns but altered indexing options (labels
    # UNINDEXED, a different tokenizer, prefix or detail options) passes
    # table_info, module, and integrity checks while silently steering bm25
    # and match semantics, so only the canonical declaration is certifiable.
    if _normalized_declaration(declaration) != _CANONICAL_FTS_DECLARATION:
        raise ValidationFailure("projection-unavailable", "generated SQLite projection schema is incomplete or invalid")
    actual_indexes = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_autoindex_%'"
        )
    }
    if not set(_REQUIRED_INDEXES).issubset(actual_indexes):
        raise ValidationFailure("projection-unavailable", "generated SQLite projection indexes are incomplete")
    for index, expected_columns in _REQUIRED_INDEXES.items():
        actual_columns = [row[2] for row in connection.execute(f'PRAGMA index_info("{index}")')]
        if actual_columns != expected_columns:
            raise ValidationFailure("projection-unavailable", "generated SQLite projection index definition is invalid")
    metadata_rows = connection.execute(
        "SELECT projection_schema_id, canonical_json_profile, source_record_set_digest, record_count FROM projection_metadata WHERE singleton_id = 1"
    ).fetchall()
    metadata_count = connection.execute("SELECT COUNT(*) FROM projection_metadata").fetchone()[0]
    if len(metadata_rows) != 1 or metadata_count != 1:
        raise ValidationFailure("projection-unavailable", "generated SQLite projection metadata is missing or ambiguous")
    schema_id, canonical_profile, source_digest, record_count = metadata_rows[0]
    if schema_id != PROJECTION_SCHEMA_ID or canonical_profile != CANONICAL_JSON_PROFILE:
        raise ValidationFailure("projection-schema-mismatch", "generated index metadata does not match the supported projection contract")
    if not isinstance(source_digest, str) or _DIGEST_PATTERN.fullmatch(source_digest) is None:
        raise ValidationFailure("projection-unavailable", "generated index source-record-set digest is invalid")
    if type(record_count) is not int or record_count < 0:
        raise ValidationFailure("projection-unavailable", "generated index record count is invalid")
    record_rows = connection.execute(
        "SELECT record_id, record_type, lifecycle, sensitivity, record_json, source_record_set_digest FROM records ORDER BY record_id"
    ).fetchall()
    if len(record_rows) != record_count:
        raise ValidationFailure("projection-unavailable", "generated index record count does not match its rows")
    canonical_lines: list[bytes] = []
    expected_provenance: list[tuple[str, int, str, str]] = []
    expected_relationships: list[tuple[str, str, str]] = []
    expected_search_rows: list[tuple[str, str, str]] = []
    for record_id, record_type, lifecycle, sensitivity, record_json, row_source_digest in record_rows:
        if not isinstance(record_json, str) or row_source_digest != source_digest:
            raise ValidationFailure("projection-unavailable", "generated index rows do not match the declared source record set")
        try:
            record = json.loads(record_json)
            if not isinstance(record, dict):
                raise ValueError
            validate(record, _knowledge_schema(record))
            canonical = _canonical(record)
        except (json.JSONDecodeError, UnicodeError, ValueError, ValidationFailure) as exc:
            raise ValidationFailure("projection-unavailable", "generated index contains an invalid canonical record") from exc
        if canonical.decode("utf-8") != record_json:
            raise ValidationFailure("projection-unavailable", "generated index record JSON is not canonical")
        if (
            record["record_id"] != record_id
            or record["record_type"] != record_type
            or record["lifecycle"] != lifecycle
            or record.get("sensitivity") != sensitivity
        ):
            raise ValidationFailure("projection-unavailable", "generated index record columns disagree with canonical record JSON")
        canonical_lines.append(canonical + b"\n")
        expected_provenance.extend(
            (record_id, ordinal, item["kind"], item["source_ref"])
            for ordinal, item in enumerate(record["provenance"])
        )
        expected_relationships.extend(
            (record_id, item["type"], item["target_ref"])
            for item in record.get("relationships", [])
        )
        meaning = record["meaning"]
        expected_search_rows.append((record_id, meaning["summary"], " ".join(meaning.get("labels", []))))
    calculated_source_digest = "sha-256:" + hashlib.sha256(b"".join(canonical_lines)).hexdigest()
    if calculated_source_digest != source_digest:
        raise ValidationFailure("projection-unavailable", "generated index source-record-set digest does not match canonical rows")
    actual_provenance = connection.execute(
        "SELECT record_id, ordinal, provenance_kind, source_ref FROM provenance ORDER BY record_id, ordinal"
    ).fetchall()
    if actual_provenance != expected_provenance:
        raise ValidationFailure("projection-unavailable", "generated index provenance rows disagree with canonical records")
    actual_relationships = connection.execute(
        "SELECT source_record_id, relationship_type, target_ref FROM relationships ORDER BY source_record_id, relationship_type, target_ref"
    ).fetchall()
    if actual_relationships != sorted(expected_relationships):
        raise ValidationFailure("projection-unavailable", "generated index relationship rows disagree with canonical records")
    actual_search_rows = connection.execute(
        "SELECT record_id, summary, labels FROM records_fts ORDER BY record_id"
    ).fetchall()
    if actual_search_rows != expected_search_rows:
        raise ValidationFailure("projection-unavailable", "generated index search rows disagree with canonical records")


@contextmanager
def _read_index(index_path: Path) -> Iterator[sqlite3.Connection]:
    """Yield a read-only connection only after contract and physical-integrity checks pass.

    Physical integrity is checked last because canonical-row validation cannot
    see the FTS5 inverted index: restoring records_fts_content after reindexing
    through records_fts leaves forged terms searchable while every content row
    still matches its canonical record. All checks and the caller's query run
    in one read transaction, so the caller only ever sees the snapshot that was
    verified. Runtimes whose integrity_check cannot reach the inverted index
    are rejected outright: their `ok` is absence of evidence.
    """
    if not _runtime_verifies_fts5_integrity():
        raise ValidationFailure("projection-unavailable", "generated SQLite projection requires demonstrated FTS5 integrity verification capability")
    if Path(str(index_path) + "-wal").exists() or Path(str(index_path) + "-shm").exists():
        raise ValidationFailure("projection-unavailable", "generated SQLite projection has uncheckpointed sidecars")
    try:
        connection = sqlite3.connect(index_path.resolve().as_uri() + "?mode=ro", uri=True)
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise ValidationFailure("projection-unavailable", "generated SQLite projection is unavailable or invalid") from exc
    try:
        connection.execute("BEGIN")
        try:
            _validate_projection_contract(connection)
        except sqlite3.Error as exc:
            raise ValidationFailure("projection-unavailable", "generated SQLite projection is unavailable or invalid") from exc
        try:
            integrity_rows = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        except sqlite3.Error as exc:
            raise ValidationFailure("projection-unavailable", "generated SQLite projection is unavailable or invalid") from exc
        if integrity_rows != ["ok"]:
            raise ValidationFailure("projection-unavailable", "generated SQLite projection failed integrity verification")
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
            validate(record, _knowledge_schema(record))
            extensions = record.get("extensions", {})
            if extensions and record.get("schema_id") != _LEGACY_RECORD_SCHEMA_ID:
                validate_extension_identifiers(extensions)
            required_extensions = {
                identifier: declaration
                for identifier, declaration in extensions.items()
                if is_required_declaration(identifier, declaration)
            }
            if required_extensions:
                preserve_extensions(
                    {"extensions": {}},
                    {
                        "schema_id": "artifact-memory/extension-bundle/v1",
                        "extensions": required_extensions,
                    },
                )
        except ExtensionFailure as exc:
            raise ValidationFailure(exc.code, exc.message, exc.path) from exc
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
    try:
        connection = sqlite3.connect(path)
        try:
            connection.executescript(load_contract_text("core", "index-sqlite.v1.sql"))
            user_version = connection.execute("PRAGMA user_version").fetchone()[0]
            if user_version != PROJECTION_USER_VERSION:
                raise ValidationFailure("projection-schema-mismatch", "packaged SQLite projection contract has an unsupported version")
            connection.execute(
                "INSERT INTO projection_metadata VALUES (1, ?, ?, ?, ?)",
                (PROJECTION_SCHEMA_ID, CANONICAL_JSON_PROFILE, source_digest, len(records)),
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
    except sqlite3.Error as exc:
        raise ValidationFailure(
            "projection-unavailable",
            "generated SQLite projection could not be created by the loaded runtime",
        ) from exc


def project_records(record_paths: Iterable[Path], output_dir: Path, *, revocation_receipts: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    all_records = canonical_records(record_paths)
    from .revocation import validated_suppressions

    suppressed = validated_suppressions(all_records, revocation_receipts)
    records = [record for record in all_records if record["record_id"] not in suppressed]
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
    if suppressed:
        receipt["extensions"] = {
            "https://artifact-memory.dev/extensions/revocation-suppression/v1": {
                "suppressed_record_count": len(suppressed),
                "suppressed_record_set_digest": sha256_bytes(canonical_bytes(sorted(suppressed))),
            }
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


_SEARCH_MATCH_QUERY = "SELECT record_id FROM records_fts WHERE records_fts MATCH ? ORDER BY record_id"
_SEARCH_MATCH_EXCLUDING_SUPERSEDED_QUERY = (
    "SELECT records_fts.record_id FROM records_fts "
    "JOIN records ON records.record_id = records_fts.record_id "
    "WHERE records_fts MATCH ? AND records.lifecycle != 'superseded' "
    "ORDER BY records_fts.record_id"
)
_RANKED_MATCH_QUERY = "SELECT record_id FROM records_fts WHERE records_fts MATCH ? ORDER BY bm25(records_fts), record_id"
_RANKED_MATCH_EXCLUDING_SUPERSEDED_QUERY = (
    "SELECT records_fts.record_id FROM records_fts "
    "JOIN records ON records.record_id = records_fts.record_id "
    "WHERE records_fts MATCH ? AND records.lifecycle != 'superseded' "
    "ORDER BY bm25(records_fts), records_fts.record_id"
)
_LITERAL_SOURCE_QUERY = (
    "SELECT records_fts.record_id, records_fts.summary, records_fts.labels, records.lifecycle "
    "FROM records_fts JOIN records ON records.record_id = records_fts.record_id "
    "ORDER BY records_fts.record_id"
)
_LITERAL_FOLDED_MATCH_QUERY = (
    "SELECT record_id, summary, labels FROM temp.literal_records_fts "
    "WHERE literal_records_fts MATCH ? ORDER BY record_id"
)
_LITERAL_FOLDED_RANKED_MATCH_QUERY = (
    "SELECT record_id, summary, labels FROM temp.literal_records_fts "
    "WHERE literal_records_fts MATCH ? ORDER BY bm25(literal_records_fts), record_id"
)


def _classify_search_failure(exc: sqlite3.Error) -> ValidationFailure:
    if getattr(exc, "sqlite_errorcode", 0) & 0xFF == 1:
        return ValidationFailure("query-invalid", "full-text query is invalid or unsupported")
    return ValidationFailure("projection-unavailable", "generated SQLite projection is unavailable or invalid")


def _matched_record_ids(
    connection: sqlite3.Connection,
    query: str,
    *,
    literal: bool,
    exclude_superseded: bool = False,
    rank: bool = False,
) -> list[str]:
    """Run one match in the caller's grammar.

    Raw mode passes the query to FTS5 unmodified. Literal mode case-folds both
    the query and the already-validated search rows into a connection-local
    FTS5 table, then quotes the query as one FTS5 string — doubling embedded
    double quotes, FTS5's only string escape — so tokens must appear as an
    adjacent phrase. The same case-folded bytes are retained as a punctuation
    post-filter. Building the temporary table is necessary because SQLite's
    default tokenizer does not implement expanding Unicode folds such as
    Straße/STRASSE, and using the durable FTS table as a prefilter could discard
    a valid literal match before Python's full case fold sees it. With
    exclude_superseded, matched records whose lifecycle column is superseded
    are dropped; the default keeps them. With rank, results are ordered by the
    explicit bm25(literal_records_fts) relevance with a record_id tiebreak
    instead of record_id alone. That ranked order is corpus-dependent and never
    authoritative.
    """
    if literal:
        folded = query.casefold()
        expression = '"' + folded.replace('"', '""') + '"'
        source_rows = connection.execute(_LITERAL_SOURCE_QUERY).fetchall()
        lifecycle_by_id = {row[0]: row[3] for row in source_rows}
        connection.execute(
            "CREATE VIRTUAL TABLE temp.literal_records_fts "
            "USING fts5(record_id UNINDEXED, summary, labels)"
        )
        connection.executemany(
            "INSERT INTO temp.literal_records_fts VALUES (?, ?, ?)",
            ((row[0], row[1].casefold(), row[2].casefold()) for row in source_rows),
        )
        match_query = _LITERAL_FOLDED_RANKED_MATCH_QUERY if rank else _LITERAL_FOLDED_MATCH_QUERY
        return [
            row[0]
            for row in connection.execute(match_query, (expression,))
            if (folded in row[1] or folded in row[2])
            and (not exclude_superseded or lifecycle_by_id[row[0]] != "superseded")
        ]
    if exclude_superseded:
        match_query = _RANKED_MATCH_EXCLUDING_SUPERSEDED_QUERY if rank else _SEARCH_MATCH_EXCLUDING_SUPERSEDED_QUERY
    else:
        match_query = _RANKED_MATCH_QUERY if rank else _SEARCH_MATCH_QUERY
    return [row[0] for row in connection.execute(match_query, (query,))]


def search_records(
    index_path: Path,
    query: str,
    *,
    literal: bool = False,
    exclude_superseded: bool = False,
    rank: bool = False,
) -> list[str]:
    if literal and not query:
        raise ValidationFailure("query-invalid", "full-text query is invalid or unsupported")
    try:
        with _read_index(index_path) as connection:
            return _matched_record_ids(
                connection,
                query,
                literal=literal,
                exclude_superseded=exclude_superseded,
                rank=rank,
            )
    except sqlite3.Error as exc:
        raise _classify_search_failure(exc) from exc


def search_receipt(
    index_path: Path,
    query: str,
    *,
    literal: bool = False,
    exclude_superseded: bool = False,
    rank: bool = False,
) -> dict[str, Any]:
    """Return search results pinned to the exact source record set and gate state.

    Additive beside search_records: the raw record-ID surface and every existing
    receipt keep their shapes. This receipt carries the source_record_set_digest
    and the integrity-gate outcome so query evidence is pinnable (WITS 1151);
    a tampered index cannot be vouched for because the read gate raises first.
    The query_digest pins the query exactly as the caller typed it, and
    query_mode and — when a parameter is active — exclude_superseded and
    result_order record every result-affecting parameter, so the receipt is
    replayable in either mode with or without supersession filtering or bm25
    ranking. Ranked receipts label their order as bm25 with a record_id
    tiebreak, explicitly non-authoritative and corpus-dependent; default
    receipts omit both fields to keep the pre-filter v1 shape for consumers
    pinned to the earlier schema.
    """
    if literal and not query:
        raise ValidationFailure("query-invalid", "full-text query is invalid or unsupported")
    try:
        with _read_index(index_path) as connection:
            record_ids = _matched_record_ids(
                connection,
                query,
                literal=literal,
                exclude_superseded=exclude_superseded,
                rank=rank,
            )
            source_digest = connection.execute(
                "SELECT source_record_set_digest FROM projection_metadata WHERE singleton_id = 1"
            ).fetchone()[0]
    except sqlite3.Error as exc:
        raise _classify_search_failure(exc) from exc
    receipt = {
        "schema_id": "artifact-memory/search-receipt/v1",
        "outcome": "complete",
        "query_mode": "literal" if literal else "raw",
        "query_digest": sha256_bytes(query.encode("utf-8")),
        "record_ids": record_ids,
        "source_record_set_digest": source_digest,
        "integrity_gate": "verified",
    }
    if exclude_superseded:
        receipt["exclude_superseded"] = True
    if rank:
        receipt["result_order"] = {
            "ranking": "bm25",
            "tiebreak": "record-id",
            "authoritative": False,
            "corpus_dependent": True,
        }
    validate(receipt, load_schema("core", "search-receipt.v1.schema.json"))
    return receipt


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
