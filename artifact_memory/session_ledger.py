"""Bounded import of dated session-ledger entries into a private vault."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, receipt_with_digest
from .coordination_sync import (
    SyncFailure,
    _advisory_lock,
    _prepare_parent,
    _read_local_regular_file,
    _validate_storage_root,
    _write_immutable,
)
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json_bytes, validate


PROVENANCE_SOURCE_REF = "session-ledger"
CONFORMANCE_SCHEMA_ID = (
    "artifact-memory/session-ledger-import-conformance-receipt/v0"
)
AUTHORITY_BOUNDARY = (
    "session-ledger imports are informational draft records and grant no execution, "
    "mutation, routing, disclosure, credential, spending, deployment, approval, or "
    "merge authority"
)
MAX_SOURCE_BYTES = 1_048_576
MAX_ENTRIES = 1_000
MAX_SUMMARY_CHARS = 4_096

_ENTRY_PREFIX = re.compile(r"^(?:[-*+]\s+|#{1,6}\s+)")
_ENTRY = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})(?:(?:\s*[:\-]\s*)|\s+)"
    r"(?P<summary>\S(?:.*\S)?)$"
)
_HEADING = re.compile(r"^#{1,6}\s+\S.*$")
_TOKEN_PREFIXES = "|".join(
    re.escape(value)
    for value in (
        "g" + "hp_",
        "g" + "hs_",
        "github" + "_pat_",
        "s" + "k-",
    )
)
_NAME_GAP = r"[ _-]*"
_CREDENTIAL_NAMES = "|".join(
    (
        "pass" + _NAME_GAP + "word",
        "pass" + _NAME_GAP + "wd",
        "api" + _NAME_GAP + "key",
        "access" + _NAME_GAP + "token",
        "refresh" + _NAME_GAP + "token",
        "client" + _NAME_GAP + "secret",
        "github" + _NAME_GAP + "token",
        "aws" + _NAME_GAP + "secret" + _NAME_GAP + "access" + _NAME_GAP + "key",
        "secret" + _NAME_GAP + "access" + _NAME_GAP + "key",
    )
)
_SENSITIVE_TOKEN = re.compile(
    "|".join(
        (
            r"-----BEGIN [A-Z ]*PRIVATE " + r"KEY-----",
            rf"\b(?:{_TOKEN_PREFIXES})[A-Za-z0-9_-]{{16,}}",
            r"\bAuthor" + r"ization\s*:\s*Bearer\s+\S+",
            rf"(?<![A-Za-z0-9])(?:{_CREDENTIAL_NAMES})\s*[:=]\s*\S+",
        )
    ),
    re.IGNORECASE,
)
_RECORD_SCHEMA = load_schema("core", "knowledge-record.v3.schema.json")
_CONFORMANCE_SCHEMA = load_schema(
    "core", "session-ledger-import-conformance-receipt.v0.schema.json"
)


def _source_bytes(source: Path) -> bytes:
    try:
        if source.lstat().st_size > MAX_SOURCE_BYTES:
            raise ValidationFailure(
                "session-ledger-source-too-large",
                "session ledger exceeds the one MiB source bound",
            )
    except FileNotFoundError:
        pass
    raw = _read_local_regular_file(
        source.parent,
        source,
        missing_code="session-ledger-source-missing",
        missing_message="session ledger source is missing",
        maximum_bytes=MAX_SOURCE_BYTES,
    )
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValidationFailure(
            "session-ledger-source-too-large",
            "session ledger exceeds the one MiB source bound",
        )
    return raw


def _parse_entries(raw: bytes) -> list[dict[str, Any]]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationFailure(
            "session-ledger-invalid-encoding",
            "session ledger must be UTF-8 text",
        ) from exc
    if "\x00" in text:
        raise ValidationFailure(
            "session-ledger-invalid-text",
            "session ledger must not contain NUL characters",
        )

    occurrences: Counter[tuple[str, str]] = Counter()
    entries: list[dict[str, Any]] = []
    for line_number, original in enumerate(text.splitlines(), start=1):
        stripped = original.strip()
        if not stripped:
            continue
        candidate = _ENTRY_PREFIX.sub("", stripped, count=1)
        match = _ENTRY.fullmatch(candidate)
        if match is None:
            if _HEADING.fullmatch(stripped):
                continue
            raise ValidationFailure(
                "session-ledger-entry-invalid",
                "every non-heading content line must be one ISO-dated entry",
                f"$.lines[{line_number}]",
            )
        entry_date = match.group("date")
        try:
            date.fromisoformat(entry_date)
        except ValueError as exc:
            raise ValidationFailure(
                "session-ledger-date-invalid",
                "session ledger entry date must be a valid ISO calendar date",
                f"$.lines[{line_number}]",
            ) from exc
        summary = " ".join(match.group("summary").split())
        if len(summary) > MAX_SUMMARY_CHARS:
            raise ValidationFailure(
                "session-ledger-summary-too-large",
                "session ledger entry exceeds the summary bound",
                f"$.lines[{line_number}]",
            )
        if _SENSITIVE_TOKEN.search(summary):
            raise ValidationFailure(
                "session-ledger-sensitive-content",
                "session ledger entries must not contain credential-like material",
                f"$.lines[{line_number}]",
            )
        key = (entry_date, summary)
        occurrence = occurrences[key]
        occurrences[key] += 1
        entries.append(
            {
                "line": line_number,
                "entry_date": entry_date,
                "summary": summary,
                "occurrence": occurrence,
            }
        )
        if len(entries) > MAX_ENTRIES:
            raise ValidationFailure(
                "session-ledger-entry-limit",
                "session ledger exceeds the 1,000-entry bound",
            )
    if not entries:
        raise ValidationFailure(
            "session-ledger-empty",
            "session ledger contains no dated entries",
        )
    return entries


def _record(entry: dict[str, Any]) -> dict[str, Any]:
    identity = {
        "entry_date": entry["entry_date"],
        "summary": entry["summary"],
        "occurrence": entry["occurrence"],
    }
    digest = hashlib.sha256(canonical_bytes(identity)).hexdigest()
    record = {
        "schema_id": "artifact-memory/knowledge-record/v3",
        "record_id": f"record://session-ledger/{digest}",
        "record_type": "workstream",
        "lifecycle": "draft",
        "meaning": {
            "summary": f"{entry['entry_date']}: {entry['summary']}",
            "labels": ["session-ledger", f"dated:{entry['entry_date']}"],
        },
        "artifact_refs": [],
        "provenance": [
            {"kind": "import", "source_ref": PROVENANCE_SOURCE_REF}
        ],
        "sensitivity": "private",
    }
    validate(record, _RECORD_SCHEMA)
    canonical_bytes(record)
    return record


def _record_path(vault: Path, record: dict[str, Any]) -> Path:
    return (
        vault
        / "records"
        / "session-ledger"
        / f"{record['record_id'].rsplit('/', 1)[-1]}.json"
    )


def _record_bytes(record: dict[str, Any]) -> bytes:
    return (json.dumps(record, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _preflight_record(vault: Path, path: Path, data: bytes) -> str:
    """Prove one immutable target before any record in the batch is published."""
    _prepare_parent(vault, path)
    if not path.exists() and not path.is_symlink():
        return "created"
    observed = _read_local_regular_file(
        vault,
        path,
        missing_code="immutable-record-collision",
        missing_message="immutable record target changed during preflight",
        maximum_bytes=len(data),
    )
    if observed != data:
        raise SyncFailure(
            "immutable-record-collision",
            "immutable record target already contains different bytes",
        )
    return "duplicate"


def import_session_ledger(
    source: Path,
    vault: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Map one bounded done log to deterministic draft records."""
    entries = _parse_entries(_source_bytes(source))
    records = [_record(entry) for entry in entries]
    mapping: list[dict[str, Any]] = []
    created = existing = 0

    if dry_run:
        _validate_storage_root(
            vault,
            create=False,
            reject_linked_ancestors=True,
        )
        dispositions = ["planned"] * len(records)
    else:
        _validate_storage_root(
            vault,
            create=True,
            reject_linked_ancestors=True,
        )
        prepared = [
            (_record_path(vault, record), _record_bytes(record))
            for record in records
        ]
        with _advisory_lock(
            vault,
            "session-ledger-import",
            busy_code="session-ledger-import-busy",
            busy_message="another session-ledger import is in progress",
            blocking=True,
        ):
            dispositions = [
                _preflight_record(vault, path, data)
                for path, data in prepared
            ]
            for (path, data), expected in zip(prepared, dispositions):
                observed = _write_immutable(vault, path, data)
                if observed != expected:
                    raise SyncFailure(
                        "immutable-record-collision",
                        "immutable record target changed after batch preflight",
                    )
        created = dispositions.count("created")
        existing = dispositions.count("duplicate")

    for entry, record, disposition in zip(entries, records, dispositions):
        mapping.append(
            {
                "line": entry["line"],
                "entry_date": entry["entry_date"],
                "record_id": record["record_id"],
                "disposition": disposition,
            }
        )
    return {
        "outcome": "complete",
        "mode": "dry-run" if dry_run else "write",
        "source_entry_count": len(entries),
        "created_record_count": created,
        "existing_record_count": existing,
        "mapping": mapping,
        "provenance_source_ref": PROVENANCE_SOURCE_REF,
        "raw_source_copied": False,
        "source_text_disclosed": False,
        "authority_boundary": AUTHORITY_BOUNDARY,
    }


def exercise_session_ledger_fixture(fixture: Path) -> dict[str, Any]:
    """Run AM-1's synthetic dry-run, write, and idempotent replay proof."""
    import tempfile

    with tempfile.TemporaryDirectory() as temporary:
        vault = Path(temporary).resolve() / "vault"
        source = fixture / "synthetic-done-log.md"
        source_before = _source_bytes(source)
        dry_run = import_session_ledger(source, vault, dry_run=True)
        dry_run_created_vault = vault.exists()
        written = import_session_ledger(source, vault)
        replay = import_session_ledger(source, vault)
        record_paths = sorted((vault / "records" / "session-ledger").glob("*.json"))
        records = [load_json_bytes(path.read_bytes()) for path in record_paths]
        for record in records:
            validate(record, _RECORD_SCHEMA)
        source_text_disclosed = any(
            entry["summary"] in json.dumps(dry_run, sort_keys=True)
            for entry in _parse_entries(source_before)
        )
        copied_raw_source = any(
            path.is_file() and path.read_bytes() == source_before
            for path in vault.rglob("*")
        )
        source_unchanged = _source_bytes(source) == source_before
        synthetic_value = "synthetic-value"
        sensitive_fragments = (
            "api" + " key" + ": " + synthetic_value,
            "client" + "_secret" + "=" + synthetic_value,
            "azure" + "_client_secret" + "=" + synthetic_value,
            "aws" + "_secret_access_key" + "=" + synthetic_value,
            "github" + "_token" + "=" + synthetic_value,
            "session=" + "g" + "hs_" + "syntheticvalue1234",
        )
        sensitive_rejections = 0
        for index, fragment in enumerate(sensitive_fragments):
            sensitive_source = Path(temporary) / f"sensitive-{index}.md"
            sensitive_source.write_text(
                f"2026-09-27 {fragment}\n",
                encoding="utf-8",
            )
            try:
                import_session_ledger(sensitive_source, vault, dry_run=True)
            except ValidationFailure as exc:
                if exc.code == "session-ledger-sensitive-content":
                    sensitive_rejections += 1
                    continue
                raise
            raise ValidationFailure(
                "session-ledger-conformance-failed",
                "synthetic credential assignment was not rejected",
            )

    body = {
        "outcome": "passed",
        "dated_entry_count": dry_run["source_entry_count"],
        "dry_run_created_vault": dry_run_created_vault,
        "dry_run_mapping_count": len(dry_run["mapping"]),
        "initial_created_count": written["created_record_count"],
        "replay_created_count": replay["created_record_count"],
        "replay_existing_count": replay["existing_record_count"],
        "validated_record_count": len(records),
        "sensitive_assignment_rejection_count": sensitive_rejections,
        "provenance_source_ref": PROVENANCE_SOURCE_REF,
        "raw_source_copied": copied_raw_source,
        "source_text_disclosed": source_text_disclosed,
        "source_unchanged": source_unchanged,
        "authority_boundary": AUTHORITY_BOUNDARY,
    }
    receipt = receipt_with_digest(
        CONFORMANCE_SCHEMA_ID,
        "session-ledger-import-conformance-receipt://sha-256/",
        body,
    )
    validate(receipt, _CONFORMANCE_SCHEMA)
    return receipt


def render_session_ledger_conformance_receipt(receipt: dict[str, Any]) -> str:
    return (
        "# Session-ledger import conformance receipt\n\n"
        f"- Outcome: `{receipt['outcome']}`\n"
        f"- Dated entries: `{receipt['dated_entry_count']}`\n"
        f"- Dry-run mappings: `{receipt['dry_run_mapping_count']}`\n"
        f"- Dry-run created vault: `{str(receipt['dry_run_created_vault']).lower()}`\n"
        f"- Initial records created: `{receipt['initial_created_count']}`\n"
        f"- Replay records created: `{receipt['replay_created_count']}`\n"
        f"- Replay records reused: `{receipt['replay_existing_count']}`\n"
        f"- Records validated: `{receipt['validated_record_count']}`\n"
        f"- Sensitive assignment forms rejected: `{receipt['sensitive_assignment_rejection_count']}`\n"
        f"- Provenance: `{receipt['provenance_source_ref']}`\n"
        f"- Raw source copied: `{str(receipt['raw_source_copied']).lower()}`\n"
        f"- Source text disclosed by mapping: `{str(receipt['source_text_disclosed']).lower()}`\n"
        f"- Source unchanged: `{str(receipt['source_unchanged']).lower()}`\n"
        f"- Receipt: `{receipt['receipt_id']}`\n\n"
        f"Authority boundary: {receipt['authority_boundary']}.\n"
    )
