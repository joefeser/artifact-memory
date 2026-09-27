"""Repository identity manifests and UUID-bound coordination references."""

from __future__ import annotations

import json
import os
import secrets
import stat
import subprocess
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
_GIT_REPOSITORY_ENVIRONMENT = frozenset(
    {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CEILING_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_CONFIG",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_NOSYSTEM",
        "GIT_CONFIG_PARAMETERS",
        "GIT_CONFIG_SYSTEM",
        "GIT_DIR",
        "GIT_DISCOVERY_ACROSS_FILESYSTEM",
        "GIT_GRAFT_FILE",
        "GIT_IMPLICIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_INTERNAL_SUPER_PREFIX",
        "GIT_NAMESPACE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_PREFIX",
        "GIT_REPLACE_REF_BASE",
        "GIT_SHALLOW_FILE",
        "GIT_SUPER_PREFIX",
        "GIT_WORK_TREE",
    }
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


def _observe_directory_path(directory_path: Path) -> list[os.stat_result]:
    observations: list[os.stat_result] = []
    for component in _path_components(directory_path):
        try:
            entry = os.lstat(component)
        except OSError as exc:
            raise ValidationFailure(
                "repo-identity-unavailable",
                "repository root could not be inspected safely",
                "$",
            ) from exc
        if _is_link_or_reparse(entry) or not stat.S_ISDIR(entry.st_mode):
            raise ValidationFailure(
                "repo-identity-unsafe",
                "repository root must not traverse links, reparse points, or non-directories",
                "$",
            )
        observations.append(entry)
    return observations


def _same_entry_chain(
    before: list[os.stat_result], after: list[os.stat_result]
) -> bool:
    return len(before) == len(after) and all(
        _entry_identity(left) == _entry_identity(right)
        for left, right in zip(before, after)
    )


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


def _git_output(repo_root: Path, *args: str) -> bytes:
    environment = os.environ.copy()
    for name in tuple(environment):
        if (
            name in _GIT_REPOSITORY_ENVIRONMENT
            or name.startswith("GIT_CONFIG_KEY_")
            or name.startswith("GIT_CONFIG_VALUE_")
        ):
            environment.pop(name)
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_SYSTEM"] = os.devnull
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    try:
        completed = subprocess.run(
            ["git", "--no-replace-objects", "-C", os.fspath(repo_root), *args],
            check=False,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise ValidationFailure(
            "repo-identity-unavailable",
            "repository identity could not be verified against Git",
            "$",
        ) from exc
    if completed.returncode != 0:
        raise ValidationFailure(
            "repo-identity-uncommitted",
            "repository identity manifest is not available from the pinned HEAD commit",
            "$",
        )
    return completed.stdout


def verify_repo_worktree_root(repo_root: Path) -> Path:
    """Return an exact, link-free Git worktree root without requiring HEAD."""
    absolute_root = _absolute_without_resolution(repo_root)
    before = _observe_directory_path(absolute_root)
    try:
        inside = _git_output(
            absolute_root, "rev-parse", "--is-inside-work-tree"
        ).strip()
        bare = _git_output(
            absolute_root, "rev-parse", "--is-bare-repository"
        ).strip()
        prefix = _git_output(absolute_root, "rev-parse", "--show-prefix")
        top_level_raw = _git_output(
            absolute_root,
            "rev-parse",
            "--path-format=absolute",
            "--show-toplevel",
        )
    except ValidationFailure as exc:
        if exc.code == "repo-identity-unavailable":
            raise
        raise ValidationFailure(
            "repo-identity-not-repository",
            "repository identity root must be the exact top level of a Git worktree",
            "$",
        ) from exc
    top_level_bytes = top_level_raw.rstrip(b"\r\n")
    if b"\n" in top_level_bytes or b"\r" in top_level_bytes:
        raise ValidationFailure(
            "repo-identity-unavailable",
            "Git returned an ambiguous repository worktree path",
            "$",
        )
    top_level = os.path.normcase(os.path.abspath(os.fsdecode(top_level_bytes)))
    expected_root = os.path.normcase(os.fspath(absolute_root))
    if (
        inside != b"true"
        or bare != b"false"
        or prefix.strip()
        or top_level != expected_root
    ):
        raise ValidationFailure(
            "repo-identity-not-repository",
            "repository identity root must be the exact top level of a Git worktree",
            "$",
        )
    after = _observe_directory_path(absolute_root)
    if not _same_entry_chain(before, after):
        raise ValidationFailure(
            "repo-identity-unsafe",
            "repository root changed while its identity boundary was verified",
            "$",
        )
    return absolute_root


def load_repo_identity_candidate(repo_root: Path) -> dict[str, str]:
    """Load a strict manifest without claiming that it is committed yet."""
    verify_repo_worktree_root(repo_root)
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


def _write_all(descriptor: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(descriptor, data[offset:])
        if written <= 0:
            raise OSError("repository identity write made no progress")
        offset += written


def _create_manifest_with_directory_descriptors(
    absolute_root: Path, data: bytes
) -> None:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(absolute_root.anchor, flags)
    try:
        for part in absolute_root.relative_to(absolute_root.anchor).parts:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        try:
            os.mkdir(REPO_IDENTITY_RELATIVE_PATH.parent.name, 0o755, dir_fd=descriptor)
            os.fsync(descriptor)
        except FileExistsError:
            pass
        identity_directory = os.open(
            REPO_IDENTITY_RELATIVE_PATH.parent.name,
            flags,
            dir_fd=descriptor,
        )
        try:
            temporary_name = f".repo.json.{secrets.token_hex(8)}.tmp"
            temporary_descriptor = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_NOFOLLOW
                | getattr(os, "O_CLOEXEC", 0),
                0o644,
                dir_fd=identity_directory,
            )
            try:
                _write_all(temporary_descriptor, data)
                os.fsync(temporary_descriptor)
            finally:
                os.close(temporary_descriptor)
            try:
                os.link(
                    temporary_name,
                    REPO_IDENTITY_RELATIVE_PATH.name,
                    src_dir_fd=identity_directory,
                    dst_dir_fd=identity_directory,
                    follow_symlinks=False,
                )
                os.fsync(identity_directory)
            finally:
                os.unlink(temporary_name, dir_fd=identity_directory)
        finally:
            os.close(identity_directory)
    finally:
        os.close(descriptor)


def _create_manifest_portable(absolute_root: Path, data: bytes) -> None:
    del absolute_root, data
    raise ValidationFailure(
        "repo-identity-create-unsupported",
        "safe repository identity creation is unsupported on this filesystem; "
        "create and commit repo.json through an independently trusted workflow",
        "$",
    )


def create_repo_identity_manifest(
    repo_root: Path, identity: dict[str, str]
) -> str:
    """Create one strict manifest without overwriting any existing path.

    The caller supplies the UUID selected by separately administered project
    registration. This function does not mint authorization or commit Git
    history. It returns ``created`` or ``existing``.
    """
    validate(identity, REPO_IDENTITY_SCHEMA)
    absolute_root = verify_repo_worktree_root(repo_root)
    manifest_path = absolute_root / REPO_IDENTITY_RELATIVE_PATH
    if manifest_path.exists() or manifest_path.is_symlink():
        existing = load_repo_identity_candidate(absolute_root)
        if existing != identity:
            raise ValidationFailure(
                "repo-identity-collision",
                "repository identity manifest already contains a different identity",
                "$",
            )
        return "existing"
    data = (json.dumps(identity, sort_keys=True, indent=2) + "\n").encode("utf-8")
    secure_directory_create = (
        os.open in os.supports_dir_fd
        and os.mkdir in os.supports_dir_fd
        and os.link in os.supports_dir_fd
        and os.unlink in os.supports_dir_fd
        and all(hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW"))
    )
    try:
        if secure_directory_create:
            _create_manifest_with_directory_descriptors(absolute_root, data)
        else:
            _create_manifest_portable(absolute_root, data)
    except FileExistsError as exc:
        try:
            existing = load_repo_identity_candidate(absolute_root)
        except ValidationFailure:
            raise ValidationFailure(
                "repo-identity-collision",
                "repository identity path appeared while the manifest was created",
                "$",
            ) from exc
        if existing == identity:
            return "existing"
        raise ValidationFailure(
            "repo-identity-collision",
            "repository identity path appeared with a different identity",
            "$",
        ) from exc
    except OSError as exc:
        raise ValidationFailure(
            "repo-identity-unavailable",
            "repository identity manifest could not be created safely",
            "$",
        ) from exc
    if _read_manifest_bytes(absolute_root) != data:
        raise ValidationFailure(
            "repo-identity-unsafe",
            "repository identity manifest changed while it was created",
            "$",
        )
    return "created"


def _verify_committed_manifest(repo_root: Path, manifest_bytes: bytes) -> None:
    absolute_root = verify_repo_worktree_root(repo_root)

    commit = _git_output(
        absolute_root, "rev-parse", "--verify", "HEAD^{commit}"
    ).strip()
    if not commit:
        raise ValidationFailure(
            "repo-identity-uncommitted",
            "repository identity manifest is not available from the pinned HEAD commit",
            "$",
        )
    try:
        commit_name = commit.decode("ascii", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValidationFailure(
            "repo-identity-unavailable",
            "Git returned an invalid repository commit identity",
            "$",
        ) from exc
    if len(commit_name) not in {40, 64} or any(
        character not in "0123456789abcdef" for character in commit_name
    ):
        raise ValidationFailure(
            "repo-identity-unavailable",
            "Git returned an invalid repository commit identity",
            "$",
        )
    relative_path = REPO_IDENTITY_RELATIVE_PATH.as_posix()
    tree_entry = _git_output(
        absolute_root,
        "--literal-pathspecs",
        "ls-tree",
        "-z",
        commit_name,
        "--",
        relative_path,
    )
    regular_prefixes = (b"100644 blob ", b"100755 blob ")
    expected_suffix = b"\t" + relative_path.encode("ascii") + b"\0"
    if (
        not tree_entry.startswith(regular_prefixes)
        or not tree_entry.endswith(expected_suffix)
        or tree_entry.count(b"\0") != 1
    ):
        raise ValidationFailure(
            "repo-identity-uncommitted",
            "repository identity manifest must be a regular file committed at the repository root",
            "$",
        )
    committed_bytes = _git_output(
        absolute_root, "show", f"{commit_name}:{relative_path}"
    )
    if committed_bytes != manifest_bytes:
        raise ValidationFailure(
            "repo-identity-uncommitted",
            "repository identity manifest differs from the pinned HEAD commit",
            "$",
        )


def load_repo_identity(repo_root: Path) -> dict[str, str]:
    """Load one strict, committed repository identity manifest."""
    try:
        manifest_bytes = _read_manifest_bytes(repo_root)
        _verify_committed_manifest(repo_root, manifest_bytes)
        candidate = load_json_bytes(manifest_bytes)
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
