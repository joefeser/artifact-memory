"""Repository identity manifests and UUID-bound coordination references."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .coordination import (
    ACCESS_LABEL_SCHEMA_ID,
    TASK_PACKET_SCHEMA_ID,
    WORK_RECEIPT_SCHEMA_ID,
    validate_coordination_records,
)
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, validate


REPO_IDENTITY_RELATIVE_PATH = Path(".agent-memory/repo.json")
REPO_IDENTITY_SCHEMA = load_schema(
    "coordination", "repo-identity.v0.schema.json"
)
_LABEL_PERMISSION_FIELDS = (
    "claimProjects",
    "postReceipts",
    "readProjects",
    "syncTaskPackets",
    "syncWorkReceipts",
)


def load_repo_identity(repo_root: Path) -> dict[str, str]:
    """Load one strict, committed repository identity manifest."""
    manifest_path = repo_root / REPO_IDENTITY_RELATIVE_PATH
    if manifest_path.is_symlink():
        raise ValidationFailure(
            "repo-identity-unsafe",
            "repository identity manifest must not be a symbolic link",
            "$",
        )
    if not manifest_path.is_file():
        raise ValidationFailure(
            "repo-identity-missing",
            "repository root has no .agent-memory/repo.json identity manifest",
            "$",
        )
    try:
        candidate = load_json(manifest_path)
    except ValidationFailure as exc:
        raise ValidationFailure(exc.code, exc.message, "$") from exc
    validate(candidate, REPO_IDENTITY_SCHEMA)
    return {"uuid": candidate["uuid"], "humanName": candidate["humanName"]}


def load_repo_identity_registry(repo_roots: list[Path]) -> dict[str, Any]:
    """Load manifests keyed only by authoritative UUID.

    Human names are intentionally not unique. Repeated roots for one UUID are
    also permitted so a rename or multiple checkouts cannot create a false
    identity conflict.
    """
    if not repo_roots:
        raise ValidationFailure(
            "invalid-input", "at least one repository root is required", "$.repos"
        )
    identities = [load_repo_identity(root) for root in repo_roots]
    known_project_ids = {identity["uuid"] for identity in identities}
    return {
        "manifest_count": len(identities),
        "known_project_ids": known_project_ids,
        "human_names": [identity["humanName"] for identity in identities],
    }


def _project_references(record: dict[str, Any]) -> list[tuple[str, str]]:
    schema_id = record["schema_id"]
    if schema_id in {TASK_PACKET_SCHEMA_ID, WORK_RECEIPT_SCHEMA_ID}:
        return [(record["projectId"], "$.projectId")]
    if schema_id != ACCESS_LABEL_SCHEMA_ID:
        return []
    references = [
        (item["projectId"], f"$.projectNames[{index}].projectId")
        for index, item in enumerate(record["projectNames"])
    ]
    for field in _LABEL_PERMISSION_FIELDS:
        references.extend(
            (project_id, f"$.may.{field}[{index}]")
            for index, project_id in enumerate(record["may"][field])
        )
    references.extend(
        (project_id, f"$.mayNot.readProjects[{index}]")
        for index, project_id in enumerate(record["mayNot"]["readProjects"])
    )
    return references


def validate_coordination_project_references(
    records: list[dict[str, Any]], known_project_ids: set[str]
) -> int:
    """Fail typed when a strict coordination record names an unknown UUID."""
    checked = 0
    for record_index, record in enumerate(records):
        for project_id, path in _project_references(record):
            checked += 1
            if project_id not in known_project_ids:
                raise ValidationFailure(
                    "coordination-project-unknown",
                    "coordination project UUID is not present in the supplied repository identities",
                    f"$.records[{record_index}]{path[1:]}",
                )
    return checked


def validate_repo_bound_coordination_records(
    records: list[dict[str, Any]], repo_roots: list[Path]
) -> dict[str, Any]:
    """Validate coordination semantics plus authoritative project identities."""
    result = validate_coordination_records(records)
    registry = load_repo_identity_registry(repo_roots)
    checked = validate_coordination_project_references(
        records, registry["known_project_ids"]
    )
    return {
        **result,
        "repo_identity_verified": True,
        "repo_manifest_count": registry["manifest_count"],
        "known_project_count": len(registry["known_project_ids"]),
        "project_reference_count": checked,
    }


def validate_repo_bound_coordination_files(
    record_paths: list[Path], repo_roots: list[Path]
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for index, path in enumerate(record_paths):
        try:
            value = load_json(path)
        except ValidationFailure as exc:
            raise ValidationFailure(
                exc.code, exc.message, f"$.files[{index}]"
            ) from exc
        if not isinstance(value, dict):
            raise ValidationFailure(
                "invalid-input",
                "coordination record must be a JSON object",
                f"$.files[{index}]",
            )
        records.append(value)
    return validate_repo_bound_coordination_records(records, repo_roots)
