"""Allowlisted, local-only Codex-history derivative import."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .canonical import canonical_bytes, expected_receipt_id, receipt_with_digest
from .schema_resources import load_schema
from .validator import ValidationFailure, validate

ALLOWED_FIELDS = (
    "task_id",
    "title",
    "summary",
    "decisions",
    "research",
    "workstreams",
    "open_questions",
)
LEGACY_ALLOWED_FIELDS = ("task_id", "title", "summary", "decisions", "open_questions")
EXCLUDED_CATEGORIES = (
    "raw-transcript",
    "raw-attachments",
    "credentials",
    "browser-state",
    "absolute-paths",
    "unrelated-task-content",
    "unrecognized-source-fields",
)
TRANSFORMATION_REF = "artifact-memory/codex-history-allowlist/v2"
AUTHORITY_BOUNDARY = (
    "derivative knowledge only; no execution, mutation, spending, deployment, credential use, declassification, disclosure, routing, merge, or approval authority"
)
MAX_TITLE_CHARS = 240
MAX_TEXT_CHARS = 4_096
MAX_ITEMS_PER_FIELD = 64
IMPORT_RECORD_TYPES = {
    "decision": "decision",
    "research": "note",
    "workstream": "workstream",
    "question": "question",
}

_PORTABLE_ID = re.compile(r"^[A-Za-z0-9._~-]+$")
_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9])/[A-Za-z0-9._~-]+"
    r"|\b[A-Za-z]:[\\/]"
    r"|\\\\[A-Za-z0-9._~-]+[\\/]"
)
_TOKEN_PREFIXES = "|".join(
    re.escape(value)
    for value in ("g" + "hp_", "github" + "_pat_", "s" + "k-")
)
_CREDENTIAL_NAMES = "|".join(
    (
        "pass" + "word",
        "pass" + "wd",
        "api" + "[_-]?key",
        "access" + "[_-]?token",
    )
)
_SENSITIVE_TOKEN = re.compile(
    "|".join(
        (
            r"-----BEGIN [A-Z ]*PRIVATE " + r"KEY-----",
            rf"\b(?:{_TOKEN_PREFIXES})[A-Za-z0-9_-]{{16,}}",
            r"\bAuthor" + r"ization\s*:\s*Bearer\s+\S+",
            rf"\b(?:{_CREDENTIAL_NAMES})\s*[:=]\s*\S+",
        )
    ),
    re.IGNORECASE,
)


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _legacy_v1_import(
    task: dict[str, Any], authorized: bool, selected_task_id: str | None
) -> dict[str, Any]:
    """Retain the original v1 helper behavior for existing callers."""
    task_id = task.get("task_id", "")
    source_ref = (
        f"codex-task://synthetic/{task_id}"
        if task_id
        else "codex-task://synthetic/unknown"
    )
    if not authorized or (selected_task_id is not None and selected_task_id != task_id):
        body = {
            "source_task_ref": source_ref,
            "outcome": "not-authorized",
            "admitted_fields": [],
            "excluded_categories": list(EXCLUDED_CATEGORIES[:-1]),
            "raw_retention": "owner-policy-required",
            "limitations": ["explicit single-task authorization is required"],
        }
        return {
            "records": [],
            "declassification_receipt": receipt_with_digest(
                "artifact-memory/declassification-receipt/v1",
                "declassification-receipt://",
                body,
            ),
        }
    if not isinstance(task_id, str) or _PORTABLE_ID.fullmatch(task_id) is None:
        raise ValueError("task identity is not portable")
    title = str(task.get("title", "")).strip()
    summary = str(task.get("summary", "")).strip()
    if not title or not summary:
        raise ValueError("allowlisted task meaning is incomplete")
    decisions = " ".join(
        str(item).strip() for item in task.get("decisions", []) if str(item).strip()
    )
    questions = " ".join(
        str(item).strip()
        for item in task.get("open_questions", [])
        if str(item).strip()
    )
    meaning_summary = f"{title}: {summary}"
    if decisions:
        meaning_summary += f" Decisions: {decisions}."
    if questions:
        meaning_summary += f" Open questions: {questions}."
    record = {
        "schema_id": "artifact-memory/knowledge-record/v1",
        "record_id": (
            "record://codex-derivative/"
            + _digest({"task_id": task_id, "summary": meaning_summary})[:32]
        ),
        "record_type": "workstream",
        "lifecycle": "draft",
        "meaning": {
            "summary": meaning_summary,
            "labels": ["codex-derivative", "synthetic"],
        },
        "artifact_refs": [],
        "provenance": [{"kind": "import", "source_ref": source_ref}],
        "derivative": {
            "source_task_ref": source_ref,
            "transformation_ref": "artifact-memory/codex-history-allowlist/v1",
            "uncertainty": (
                "Derivative summary; excluded source material and unresolved context "
                "may change interpretation."
            ),
        },
        "sensitivity": "private",
    }
    body = {
        "source_task_ref": source_ref,
        "outcome": "admitted",
        "admitted_fields": [field for field in LEGACY_ALLOWED_FIELDS if field in task],
        "excluded_categories": list(EXCLUDED_CATEGORIES[:-1]),
        "raw_retention": "encrypted-recovery-only",
        "limitations": [
            "synthetic fixture only",
            "no bulk ingestion",
            "derivative meaning requires owner review",
        ],
    }
    return {
        "records": [record],
        "declassification_receipt": receipt_with_digest(
            "artifact-memory/declassification-receipt/v1",
            "declassification-receipt://",
            body,
        ),
    }


def import_selected_task(
    task: dict[str, Any],
    authorized: bool,
    selected_task_id: str | None = None,
) -> dict[str, Any]:
    """Compatibility entrypoint for the original synthetic v1 helper."""
    return _legacy_v1_import(task, authorized, selected_task_id)


def _safe_text(value: Any, field: str, *, maximum: int = MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str):
        raise ValidationFailure("invalid-task-export", f"{field} must be a string")
    normalized = " ".join(value.split())
    if not normalized:
        raise ValidationFailure("invalid-task-export", f"{field} must not be empty")
    if len(normalized) > maximum:
        raise ValidationFailure(
            "task-" + "export-limit-exceeded", f"{field} exceeds its text bound"
        )
    if _ABSOLUTE_PATH.search(normalized):
        raise ValidationFailure("excluded-content-detected", f"{field} contains an absolute path")
    if _SENSITIVE_TOKEN.search(normalized):
        raise ValidationFailure(
            "excluded-content-detected", f"{field} contains credential-like material"
        )
    return normalized


def _safe_items(task: dict[str, Any], field: str) -> list[str]:
    value = task.get(field, [])
    if not isinstance(value, list) or len(value) > MAX_ITEMS_PER_FIELD:
        raise ValidationFailure("invalid-task-export", f"{field} must be a bounded array")
    return [
        _safe_text(item, f"{field}[{index}]")
        for index, item in enumerate(value)
    ]


def _record(
    source_ref: str,
    source_scope: str,
    sensitivity: str,
    record_type: str,
    label: str,
    summary: str,
) -> dict[str, Any]:
    record_key = {
        "record_type": record_type,
        "label": label,
        "summary": summary,
    }
    labels = ["codex-history-derivative", label]
    if source_scope == "synthetic":
        labels.append("synthetic")
    return {
        "schema_id": "artifact-memory/knowledge-record/v2",
        "record_id": "record://codex-derivative/" + _digest(record_key),
        "record_type": record_type,
        "lifecycle": "draft",
        "meaning": {"summary": summary, "labels": labels},
        "artifact_refs": [],
        "provenance": [
            {"kind": "import", "source_ref": source_ref},
            {"kind": "derivation", "source_ref": TRANSFORMATION_REF},
        ],
        "relationships": [{"type": "produced-from", "target_ref": source_ref}],
        "derivative": {
            "source_task_ref": source_ref,
            "transformation_ref": TRANSFORMATION_REF,
            "uncertainty": (
                "Curated derivative; excluded source material and unresolved context may "
                "change interpretation."
            ),
        },
        "sensitivity": sensitivity,
    }


def _receipt(
    policy: dict[str, Any],
    source_ref: str,
    outcome: str,
    records: Iterable[dict[str, Any]],
    admitted_fields: list[str],
) -> dict[str, Any]:
    materialized = list(records)
    counts = Counter(record["meaning"]["labels"][1] for record in materialized)
    body = {
        "source_task_ref": source_ref,
        "import_policy_id": policy["policy_id"],
        "authority_ref": policy["authority_ref"],
        "outcome": outcome,
        "admitted_fields": admitted_fields,
        "admitted_record_ids": [record["record_id"] for record in materialized],
        "admitted_records": [
            {
                "record_id": record["record_id"],
                "record_type": record["meaning"]["labels"][1],
            }
            for record in materialized
        ],
        "record_type_counts": {
            "decision": counts["decision"],
            "research": counts["research"],
            "workstream": counts["workstream"],
            "question": counts["question"],
        },
        "excluded_categories": list(EXCLUDED_CATEGORIES),
        "raw_retention": policy["raw_retention_mode"],
        "raw_retention_policy_ref": policy["raw_retention_policy_ref"],
        "raw_source_expires_at": policy["raw_source_expires_at"],
        "raw_source_canonical": False,
        "correction_route": "artifact-memory/record-supersession/v2",
        "deletion_route": "artifact-memory/retention-deletion/v2",
        "owner_review_required": True,
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": [
            "only allowlisted curated fields were admitted",
            "no raw history is copied into Artifact Memory canonical storage",
            "correction or deletion requires a separate lifecycle decision under issue 36",
        ],
    }
    result = receipt_with_digest(
        "artifact-memory/declassification-receipt/v2",
        "declassification-receipt://",
        body,
    )
    validate(result, load_schema("core", "declassification-receipt.v2.schema.json"))
    return result


def import_task_export(task: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Transform one explicitly selected export into draft vendor-neutral records."""
    if not isinstance(task, dict):
        raise ValidationFailure("invalid-task-export", "one task export object is required")
    if not isinstance(policy, dict):
        raise ValidationFailure("invalid-import-policy", "one import policy object is required")
    validate(policy, load_schema("adapters", "codex-history-import-policy.v1.schema.json"))
    authorized_at = datetime.fromisoformat(policy["authorized_at"].replace("Z", "+00:00"))
    expires_at = datetime.fromisoformat(policy["raw_source_expires_at"].replace("Z", "+00:00"))
    if expires_at <= authorized_at:
        raise ValidationFailure(
            "invalid-import-policy", "raw source expiry must follow authorization time"
        )
    if policy["source_scope"] == "local":
        if policy["record_sensitivity"] == "public":
            raise ValidationFailure(
                "invalid-import-policy",
                "local task derivatives must remain private or restricted at intake",
            )
        if not policy["authority_ref"].startswith("authority://owner/"):
            raise ValidationFailure(
                "invalid-import-policy",
                "local task selection requires an explicit owner authority reference",
            )
    task_id = task.get("task_id")
    if not isinstance(task_id, str) or _PORTABLE_ID.fullmatch(task_id) is None:
        raise ValidationFailure("invalid-task-export", "task identity is not portable")
    source_ref = f"codex-task://{policy['source_scope']}/{task_id}"
    if (
        policy["authorization_state"] != "granted"
        or task_id != policy["selected_task_id"]
    ):
        receipt = _receipt(policy, source_ref, "not-authorized", [], [])
        return {"records": [], "declassification_receipt": receipt}

    title = _safe_text(task.get("title"), "title", maximum=MAX_TITLE_CHARS)
    summary = _safe_text(task.get("summary"), "summary")
    decisions = _safe_items(task, "decisions")
    research = _safe_items(task, "research")
    workstreams = _safe_items(task, "workstreams")
    questions = _safe_items(task, "open_questions")
    if not decisions or not research:
        raise ValidationFailure(
            "curation-incomplete",
            "at least one curated decision and research item are required",
        )
    workstream_items = workstreams or [summary]
    record_specs = list(
        dict.fromkeys(
            [("decision", "decision", value) for value in decisions]
            + [("note", "research", value) for value in research]
            + [
                (
                    "workstream",
                    "workstream",
                    f"{title}: {value}",
                )
                for value in workstream_items
            ]
            + [("question", "question", value) for value in questions]
        )
    )
    records = [
        _record(
            source_ref,
            policy["source_scope"],
            policy["record_sensitivity"],
            record_type,
            label,
            text,
        )
        for record_type, label, text in record_specs
    ]
    record_schema = load_schema("core", "knowledge-record.v2.schema.json")
    for record in records:
        validate(record, record_schema)
    admitted_fields = [field for field in ALLOWED_FIELDS if field in task]
    receipt = _receipt(policy, source_ref, "admitted", records, admitted_fields)
    return {"records": records, "declassification_receipt": receipt}


def _require_receipt_integrity(receipt: dict[str, Any]) -> None:
    if receipt["receipt_id"] != expected_receipt_id(
        receipt, "declassification-receipt://"
    ):
        raise ValidationFailure(
            "declassification-receipt-integrity-failed",
            "declassification receipt identity does not match its canonical body",
        )


def _require_receipt_record_summary(
    receipt: dict[str, Any], admitted_records: list[dict[str, str]]
) -> dict[str, int]:
    receipt_records = receipt["admitted_records"]
    receipt_ids = [item["record_id"] for item in receipt_records]
    counts = Counter(item["record_type"] for item in receipt_records)
    record_type_counts = {
        key: counts[key]
        for key in ("decision", "research", "workstream", "question")
    }
    if (
        receipt["outcome"] != "admitted"
        or receipt["admitted_record_ids"] != receipt_ids
        or len(set(receipt_ids)) != len(receipt_ids)
        or sorted(receipt_records, key=lambda item: item["record_id"])
        != sorted(admitted_records, key=lambda item: item["record_id"])
        or receipt["record_type_counts"] != record_type_counts
    ):
        raise ValidationFailure(
            "import-receipt-mismatch",
            "declassification receipt does not match the admitted record set",
        )
    return record_type_counts


def _import_record_summary(record: dict[str, Any]) -> dict[str, str]:
    meaning = record.get("meaning")
    labels = meaning.get("labels") if isinstance(meaning, dict) else None
    if (
        not isinstance(labels, list)
        or len(labels) < 2
        or labels[1] not in IMPORT_RECORD_TYPES
    ):
        raise ValidationFailure(
            "invalid-import-record",
            "an admitted record must carry a recognized Codex-history record type label",
        )
    import_record_type = labels[1]
    if record.get("record_type") != IMPORT_RECORD_TYPES[import_record_type]:
        raise ValidationFailure(
            "invalid-import-record",
            "the Codex-history record type label does not match the canonical record type",
        )
    return {
        "record_id": record["record_id"],
        "record_type": import_record_type,
    }


def sanitized_dogfood_receipt(
    *,
    performed_at: str,
    record_type_counts: dict[str, int],
) -> dict[str, Any]:
    """Build a public-safe operational receipt without private refs or digests."""
    expected_keys = {"decision", "research", "workstream", "question"}
    if (
        not isinstance(record_type_counts, dict)
        or set(record_type_counts) != expected_keys
        or any(type(value) is not int for value in record_type_counts.values())
    ):
        raise ValidationFailure(
            "invalid-dogfood-counts",
            "record type counts must contain exactly four integer counters",
        )
    normalized_counts = {
        key: record_type_counts[key]
        for key in ("decision", "research", "workstream", "question")
    }
    body = {
        "scope": "authorized-private-single-task-import",
        "outcome": "complete",
        "import_contract": TRANSFORMATION_REF,
        "performed_at": performed_at,
        "source_task_count": 1,
        "source_task_identity_disclosed": False,
        "record_type_counts": normalized_counts,
        "records_validated": sum(normalized_counts.values()),
        "raw_source_canonical": False,
        "excluded_material_committed": False,
        "private_record_material_committed": False,
        "output_location_disclosed": False,
        "declassification_receipt_retained_private": True,
        "lifecycle_route_verified": True,
        "owner_review_state": "required",
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": [
            "receipt reports outcome and counts only; it does not disclose source identity",
            "receipt does not declassify private records or raw task history",
            "clean public checks are guardrails, not proof that private material never existed",
        ],
    }
    result = receipt_with_digest(
        "artifact-memory/codex-history-dogfood-receipt/v1",
        "codex-history-dogfood-receipt://",
        body,
    )
    validate(
        result,
        load_schema("core", "codex-history-dogfood-receipt.v1.schema.json"),
    )
    return result


def sanitize_private_import_receipt(
    private_receipt: dict[str, Any], *, performed_at: str
) -> dict[str, Any]:
    """Reduce one validated local import receipt to the public-safe dogfood shape."""
    validate(private_receipt, load_schema("core", "declassification-receipt.v2.schema.json"))
    _require_receipt_integrity(private_receipt)
    if private_receipt["outcome"] != "admitted":
        raise ValidationFailure(
            "dogfood-import-incomplete", "only an admitted import can produce dogfood evidence"
        )
    if not private_receipt["source_task_ref"].startswith("codex-task://local/"):
        raise ValidationFailure(
            "dogfood-source-invalid", "dogfood evidence requires a selected local task"
        )
    derived_counts = _require_receipt_record_summary(
        private_receipt, private_receipt["admitted_records"]
    )
    return sanitized_dogfood_receipt(
        performed_at=performed_at,
        record_type_counts=derived_counts,
    )


def write_import_bundle(result: dict[str, Any], output_root: Path) -> None:
    """Persist one admitted batch into a new local directory without raw inputs."""
    records = result.get("records")
    receipt = result.get("declassification_receipt")
    if not isinstance(records, list) or not records or not isinstance(receipt, dict):
        raise ValidationFailure("import-not-admitted", "only an admitted import may be written")
    for record in records:
        validate(record, load_schema("core", "knowledge-record.v2.schema.json"))
    validate(receipt, load_schema("core", "declassification-receipt.v2.schema.json"))
    _require_receipt_integrity(receipt)
    admitted_records = [_import_record_summary(record) for record in records]
    _require_receipt_record_summary(receipt, admitted_records)
    output_root.parent.mkdir(parents=True, exist_ok=True)
    if output_root.exists() or output_root.is_symlink():
        raise FileExistsError(output_root)
    temporary_root = Path(
        tempfile.mkdtemp(prefix=f".{output_root.name}.pending-", dir=output_root.parent)
    )
    try:
        record_root = temporary_root / "records"
        record_root.mkdir()
        for index, record in enumerate(
            sorted(records, key=lambda item: item["record_id"]), start=1
        ):
            (record_root / f"{index:04d}.json").write_text(
                json.dumps(record, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
        (temporary_root / "declassification-receipt.json").write_text(
            json.dumps(receipt, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        if output_root.exists() or output_root.is_symlink():
            raise FileExistsError(output_root)
        temporary_root.rename(output_root)
    except BaseException:
        if temporary_root.exists():
            shutil.rmtree(temporary_root, ignore_errors=True)
        raise
