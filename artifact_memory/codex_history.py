"""Allowlisted, local-only Codex-history derivative import."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


ALLOWED_FIELDS = ("task_id", "title", "summary", "decisions", "open_questions")
EXCLUDED_CATEGORIES = ("raw-transcript", "raw-attachments", "credentials", "browser-state", "absolute-paths", "unrelated-task-content")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def import_selected_task(task: dict[str, Any], authorized: bool, selected_task_id: str | None = None) -> dict[str, Any]:
    task_id = task.get("task_id", "")
    source_ref = f"codex-task://synthetic/{task_id}" if task_id else "codex-task://synthetic/unknown"
    if not authorized or (selected_task_id is not None and selected_task_id != task_id):
        receipt_body = {"source_task_ref": source_ref, "outcome": "not-authorized", "admitted_fields": [], "excluded_categories": list(EXCLUDED_CATEGORIES), "raw_retention": "owner-policy-required", "limitations": ["explicit single-task authorization is required"]}
        return {"records": [], "declassification_receipt": {"schema_id": "artifact-memory/declassification-receipt/v1", "receipt_id": "declassification-receipt://" + _digest(receipt_body), **receipt_body}}
    if not re.fullmatch(r"[A-Za-z0-9._~-]+", task_id):
        raise ValueError("task identity is not portable")
    title = str(task.get("title", "")).strip()
    summary = str(task.get("summary", "")).strip()
    if not title or not summary:
        raise ValueError("allowlisted task meaning is incomplete")
    decision_text = " ".join(str(item).strip() for item in task.get("decisions", []) if str(item).strip())
    question_text = " ".join(str(item).strip() for item in task.get("open_questions", []) if str(item).strip())
    meaning_summary = f"{title}: {summary}"
    if decision_text:
        meaning_summary += f" Decisions: {decision_text}."
    if question_text:
        meaning_summary += f" Open questions: {question_text}."
    record = {"schema_id": "artifact-memory/knowledge-record/v1", "record_id": f"record://codex-derivative/{_digest({'task_id': task_id, 'summary': meaning_summary})[:32]}", "record_type": "workstream", "lifecycle": "draft", "meaning": {"summary": meaning_summary, "labels": ["codex-derivative", "synthetic"]}, "artifact_refs": [], "provenance": [{"kind": "import", "source_ref": source_ref}], "derivative": {"source_task_ref": source_ref, "transformation_ref": "artifact-memory/codex-history-allowlist/v1", "uncertainty": "Derivative summary; excluded source material and unresolved context may change interpretation."}, "sensitivity": "private"}
    receipt_body = {"source_task_ref": source_ref, "outcome": "admitted", "admitted_fields": [field for field in ALLOWED_FIELDS if field in task], "excluded_categories": list(EXCLUDED_CATEGORIES), "raw_retention": "encrypted-recovery-only", "limitations": ["synthetic fixture only", "no bulk ingestion", "derivative meaning requires owner review"]}
    return {"records": [record], "declassification_receipt": {"schema_id": "artifact-memory/declassification-receipt/v1", "receipt_id": "declassification-receipt://" + _digest(receipt_body), **receipt_body}}
