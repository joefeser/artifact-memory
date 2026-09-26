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


def _is_link_or_reparse(entry: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(entry.st_mode) or bool(
        getattr(entry, "st_file_attributes", 0) & reparse_flag
    )


def _entry_identity(entry: os.stat_result) -> tuple[int, int, int]:
    return entry.st_dev, entry.st_ino, stat.S_IFMT(entry.st_mode)


def _file_observation(entry: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        *_entry_identity(entry),
        entry.st_size,
        entry.st_mtime_ns,
        entry.st_ctime_ns,
    )


def _absolute_without_resolution(path: Path) -> Path:
    if ".." in path.parts:
        raise ValidationFailure(
            "repo-identity-unsafe",
            "repository identity path must not contain parent-directory traversal",
            "$",
        )
    return Path(os.path.abspath(os.fspath(path)))


def _path_components(path: Path) -> list[Path]:
    anchor = Path(path.anchor)
    current = anchor
    components: list[Path] = []
    for part in path.relative_to(anchor).parts:
        current /= part
        components.append(current)
    return components


def _observe_manifest_path(manifest_path: Path) -> list[os.stat_result]:
    components = _path_components(manifest_path)
    observations: list[os.stat_result] = []
    for index, component in enumerate(components):
        try:
            entry = os.lstat(component)
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
        final = index == len(components) - 1
        expected_type = (
            stat.S_ISREG(entry.st_mode) if final else stat.S_ISDIR(entry.st_mode)
        )
        if _is_link_or_reparse(entry) or not expected_type:
            raise ValidationFailure(
                "repo-identity-unsafe",
                "repository identity path must not traverse links, reparse points, or unexpected entry types",
                "$",
            )
        observations.append(entry)
    return observations


def _read_with_held_directories(
    manifest_path: Path,
) -> tuple[bytes, os.stat_result, os.stat_result]:
    anchor = Path(manifest_path.anchor)
    descriptor = os.open(
        anchor,
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        relative_parts = manifest_path.relative_to(anchor).parts
        for index, part in enumerate(relative_parts):
            final = index == len(relative_parts) - 1
            flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_BINARY", 0) if final else os.O_DIRECTORY
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise OSError("repository identity manifest is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read()
        return data, opened, os.fstat(descriptor)
    finally:
        os.close(descriptor)


def _read_with_identity_checks(
    manifest_path: Path,
) -> tuple[bytes, os.stat_result, os.stat_result]:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(manifest_path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise OSError("repository identity manifest is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read()
        return data, opened, os.fstat(descriptor)
    finally:
        os.close(descriptor)


def _read_manifest_bytes(repo_root: Path) -> bytes:
    absolute_root = _absolute_without_resolution(repo_root)
    manifest_path = absolute_root / REPO_IDENTITY_RELATIVE_PATH
    before = _observe_manifest_path(manifest_path)
    secure_directory_open = os.open in os.supports_dir_fd and all(
        hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW")
    )
    try:
        if secure_directory_open:
            data, opened, opened_after = _read_with_held_directories(manifest_path)
        else:
            data, opened, opened_after = _read_with_identity_checks(manifest_path)
    except OSError as exc:
        raise ValidationFailure(
            "repo-identity-unsafe",
            "repository identity manifest could not be opened without following links",
            "$",
        ) from exc
    after = _observe_manifest_path(manifest_path)
    if (
        len(before) != len(after)
        or any(
            _entry_identity(left) != _entry_identity(right)
            for left, right in zip(before, after)
        )
        or _file_observation(before[-1]) != _file_observation(opened)
        or _file_observation(opened) != _file_observation(opened_after)
        or _file_observation(opened_after) != _file_observation(after[-1])
    ):
        raise ValidationFailure(
            "repo-identity-unsafe",
            "repository identity path changed while the manifest was read",
            "$",
        )
    return data


def load_repo_identity(repo_root: Path) -> dict[str, str]:
    """Load one strict, committed repository identity manifest."""
    try:
        candidate = load_json_bytes(_read_manifest_bytes(repo_root))
        validate(candidate, REPO_IDENTITY_SCHEMA)
    except RecursionError as exc:
        raise ValidationFailure(
            "invalid-json",
            "repository identity manifest exceeds supported JSON nesting",
            "$",
        ) from exc
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
        except RecursionError as exc:
            raise ValidationFailure(
                "invalid-json",
                "coordination record exceeds supported JSON nesting",
                f"$.files[{index}]",
            ) from exc
        if not isinstance(value, dict):
            raise ValidationFailure(
                "invalid-input",
                "coordination record must be a JSON object",
                f"$.files[{index}]",
            )
        records.append(value)
    try:
        return validate_repo_bound_coordination_records(records, repo_roots)
    except RecursionError as exc:
        raise ValidationFailure(
            "invalid-json",
            "coordination record exceeds supported validation nesting",
            "$.records",
        ) from exc
