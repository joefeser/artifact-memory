"""Repository identity manifests and UUID-bound coordination references."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

from .coordination import (
    ACCESS_LABEL_SCHEMA_ID,
    TASK_PACKET_SCHEMA_ID,
    WORK_RECEIPT_SCHEMA_ID,
    validate_coordination_records,
)
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, load_json_bytes, validate


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


def _required_entry(path: Path, *, kind: str) -> os.stat_result:
    try:
        entry = path.stat(follow_symlinks=False)
    except FileNotFoundError as exc:
        raise ValidationFailure(
            "repo-identity-missing",
            "repository root has no .agent-memory/repo.json identity manifest",
            "$",
        ) from exc
    except OSError as exc:
        raise ValidationFailure(
            "repo-identity-unavailable",
            "repository identity path could not be inspected",
            "$",
        ) from exc
    expected = (
        stat.S_ISDIR(entry.st_mode)
        if kind == "directory"
        else stat.S_ISREG(entry.st_mode)
    )
    if stat.S_ISLNK(entry.st_mode) or not expected:
        raise ValidationFailure(
            "repo-identity-unsafe",
            "repository root, identity directory, and manifest must be real entries of the expected type",
            "$",
        )
    return entry


def _entry_identity(entry: os.stat_result) -> tuple[int, int, int]:
    return entry.st_dev, entry.st_ino, stat.S_IFMT(entry.st_mode)


def _read_manifest_bytes(repo_root: Path) -> bytes:
    identity_directory = repo_root / REPO_IDENTITY_RELATIVE_PATH.parent
    manifest_path = repo_root / REPO_IDENTITY_RELATIVE_PATH
    root_entry = _required_entry(repo_root, kind="directory")
    identity_entry = _required_entry(identity_directory, kind="directory")
    manifest_entry = _required_entry(manifest_path, kind="file")

    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(manifest_path, flags)
        try:
            opened_entry = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened_entry.st_mode)
                or _entry_identity(opened_entry) != _entry_identity(manifest_entry)
            ):
                raise ValidationFailure(
                    "repo-identity-unsafe",
                    "repository identity manifest changed while it was opened",
                    "$",
                )
            with os.fdopen(descriptor, "rb", closefd=True) as stream:
                descriptor = -1
                data = stream.read()
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except ValidationFailure:
        raise
    except OSError as exc:
        raise ValidationFailure(
            "repo-identity-unsafe",
            "repository identity manifest could not be opened without following links",
            "$",
        ) from exc

    stable_entries = (
        (repo_root, "directory", root_entry),
        (identity_directory, "directory", identity_entry),
        (manifest_path, "file", manifest_entry),
    )
    if any(
        _entry_identity(_required_entry(path, kind=kind))
        != _entry_identity(expected)
        for path, kind, expected in stable_entries
    ):
        raise ValidationFailure(
            "repo-identity-unsafe",
            "repository identity path changed while the manifest was read",
            "$",
        )
    return data


def load_repo_identity(repo_root: Path) -> dict[str, str]:
    """Load one strict, committed repository identity manifest."""
    candidate = load_json_bytes(_read_manifest_bytes(repo_root))
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
    identities = []
    for index, root in enumerate(repo_roots):
        try:
            identities.append(load_repo_identity(root))
        except ValidationFailure as exc:
            suffix = exc.path[1:] if exc.path.startswith("$") else f".{exc.path}"
            raise ValidationFailure(
                exc.code,
                exc.message,
                f"$.roots[{index}]{suffix}",
            ) from exc
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
