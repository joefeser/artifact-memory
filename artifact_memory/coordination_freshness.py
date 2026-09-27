"""Repo-bound evaluation of the optional coordination freshness extension."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .coordination import (
    FRESHNESS_EXTENSION_ID,
    validate_coordination_record_body,
)
from .repo_identity import compare_commit_to_head


def evaluate_coordination_freshness(
    record: dict[str, Any],
    repo_root: Path,
    *,
    expected_project_id: str,
) -> dict[str, str] | None:
    """Evaluate one strict coordination body without interpreting other extensions."""
    validated, _ = validate_coordination_record_body(record)
    declaration = validated.get("extensions", {}).get(FRESHNESS_EXTENSION_ID)
    if declaration is None:
        return None
    return compare_commit_to_head(
        repo_root,
        declaration["value"]["trueAsOfCommit"],
        expected_project_id=expected_project_id,
    )
