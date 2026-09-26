"""Provider-free v0 coordination sync over a local synthetic hub directory.

The directory adapter proves the protocol seam without claiming WITS network
interoperability. Hub configuration is server-side policy state: callers name
an opaque session handle and cannot select a principal or AccessLabel revision.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .canonical import canonical_bytes, expected_receipt_id, receipt_with_digest, sha256_bytes
from .coordination import (
    ACCESS_LABEL_SCHEMA_ID,
    TASK_PACKET_SCHEMA_ID,
    WORK_RECEIPT_SCHEMA_ID,
    revision_digest,
    validate_coordination_record_body,
)
from .schema_resources import core_schemas
from .validator import ValidationFailure, load_json, load_json_bytes, validate


SYNC_RECEIPT_SCHEMA_ID = "artifact-memory/coordination-sync-receipt/v0"
MEMBERSHIP_PAGE_SCHEMA_ID = (
    "artifact-memory/coordination-authorized-membership-page/v0"
)
LOCAL_HUB_SCHEMA_ID = "artifact-memory/local-coordination-hub/v0"
AUTHORITY_BOUNDARY = (
    "sync receipt grants no execution, disclosure, authorization, or trust"
)
PENDING_OUTCOMES_SCHEMA_ID = "artifact-memory/local-coordination-pending-outcomes/v0"

# Normative source: docs/contracts/v0-coordination-plane.md, "V0 sync resource bounds".
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_SUBMITTED_RECORDS = 1_000
MAX_RECORD_BYTES = 1024 * 1024
MAX_NESTING_DEPTH = 64
MAX_STRING_BYTES = 1024 * 1024
MAX_PAGE_BYTES = 4 * 1024 * 1024
MAX_PAGE_RECORDS = 500


class SyncFailure(ValidationFailure):
    """Typed sync failure that must not advance local successful-sync state."""


@dataclass(frozen=True)
class StoredRecord:
    record_ref: dict[str, str]
    record: dict[str, Any]
    raw: bytes
    path: Path


@dataclass(frozen=True)
class PendingOutcomes:
    outcomes: list[dict[str, Any]]
    access_label_ref: dict[str, str]
    scope_generation: int


def _pair_key(reference: dict[str, str]) -> tuple[str, str]:
    return reference["record_id"], reference["revision_digest"]


def _pair(record: dict[str, Any], digest: str | None = None) -> dict[str, str]:
    return {
        "record_id": record["record_id"],
        "revision_digest": digest or revision_digest(record),
    }


def sorted_pairs(pairs: list[dict[str, str]]) -> list[dict[str, str]]:
    """Return canonical pair membership order without Unicode normalization."""
    return sorted(
        ({"record_id": item["record_id"], "revision_digest": item["revision_digest"]} for item in pairs),
        key=lambda item: (item["record_id"], item["revision_digest"]),
    )


def pair_set_digest(pairs: list[dict[str, str]]) -> str:
    return sha256_bytes(canonical_bytes(sorted_pairs(pairs)))


def _record_path(root: Path, record_ref: dict[str, str]) -> Path:
    identity_hash = hashlib.sha256(record_ref["record_id"].encode("utf-8")).hexdigest()
    digest_hex = record_ref["revision_digest"].removeprefix("sha-256:")
    return root / "canonical" / "coordination" / identity_hash / f"{digest_hex}.json"


def _policy_label_path(root: Path, label_ref: dict[str, str]) -> Path:
    identity_hash = hashlib.sha256(label_ref["record_id"].encode("utf-8")).hexdigest()
    digest_hex = label_ref["revision_digest"].removeprefix("sha-256:")
    return root / "policy" / "labels" / identity_hash / f"{digest_hex}.json"


def _retained_policy_label(
    hub: Path,
    label_ref: dict[str, str],
    *,
    failure_code: str,
    failure_message: str,
) -> dict[str, Any]:
    """Resolve one exact immutable AccessLabel revision from hub policy history."""
    path = _policy_label_path(hub, label_ref)
    try:
        relative = path.relative_to(hub)
        current = hub
        for part in relative.parts[:-1]:
            current = current / part
            if current.is_symlink() or not current.is_dir():
                raise SyncFailure(failure_code, failure_message)
        if path.is_symlink() or not path.is_file():
            raise SyncFailure(failure_code, failure_message)
        raw = path.read_bytes()
        _check_raw_depth(raw)
        materialized, digest = validate_coordination_record_body(load_json_bytes(raw))
    except (OSError, RecursionError, ValidationFailure) as exc:
        raise SyncFailure(failure_code, failure_message) from exc
    if (
        materialized["schema_id"] != ACCESS_LABEL_SCHEMA_ID
        or _pair(materialized, digest) != label_ref
    ):
        raise SyncFailure(failure_code, failure_message)
    return materialized


def _validate_storage_root(boundary: Path, *, create: bool) -> None:
    """Reject a storage root that is itself a symlink or non-directory."""
    if boundary.is_symlink():
        raise SyncFailure("sync-storage-unsafe", "sync storage root is a symlink")
    if boundary.exists():
        if not boundary.is_dir():
            raise SyncFailure("sync-storage-unsafe", "sync storage root is not a directory")
    else:
        if not create:
            return
        boundary.mkdir(parents=True, exist_ok=True)
        if boundary.is_symlink() or not boundary.is_dir():
            raise SyncFailure("sync-storage-unsafe", "sync storage root is unsafe")
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(boundary, flags)
    except OSError as exc:
        raise SyncFailure("sync-storage-unsafe", "sync storage root is unsafe") from exc
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise SyncFailure("sync-storage-unsafe", "sync storage root is not a directory")
    finally:
        os.close(descriptor)


def _prepare_parent(boundary: Path, path: Path) -> None:
    """Create only real directories beneath a caller-selected storage root."""
    try:
        relative = path.relative_to(boundary)
    except ValueError as exc:
        raise SyncFailure("sync-storage-escape", "sync storage path escapes its root") from exc
    _validate_storage_root(boundary, create=True)
    current = boundary
    for part in relative.parts[:-1]:
        current = current / part
        if current.exists() or current.is_symlink():
            if current.is_symlink() or not current.is_dir():
                raise SyncFailure(
                    "sync-storage-unsafe",
                    "sync storage contains a symlink or non-directory parent",
                )
        else:
            current.mkdir()


def _write_immutable(boundary: Path, path: Path, data: bytes) -> str:
    _prepare_parent(boundary, path)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
            raise SyncFailure(
                "immutable-record-collision",
                "an immutable coordination path contains different bytes",
            )
        return "duplicate"
    descriptor, temporary = tempfile.mkstemp(prefix=".partial-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise SyncFailure(
                    "immutable-record-collision",
                    "an immutable coordination path contains different bytes",
                )
            return "duplicate"
        return "created"
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _write_atomic(boundary: Path, path: Path, data: bytes) -> None:
    _prepare_parent(boundary, path)
    descriptor, temporary = tempfile.mkstemp(prefix=".partial-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def store_coordination_record(root: Path, record: dict[str, Any]) -> dict[str, str]:
    """Append one validated canonical revision to a local vault or hub."""
    materialized, digest = validate_coordination_record_body(record)
    reference = _pair(materialized, digest)
    _write_immutable(root, _record_path(root, reference), canonical_bytes(materialized))
    return reference


def _record_files(root: Path) -> list[Path]:
    _validate_storage_root(root, create=False)
    base = root / "canonical" / "coordination"
    if not base.exists():
        return []
    if base.is_symlink() or not base.is_dir():
        raise SyncFailure("sync-storage-unsafe", "canonical coordination storage is unsafe")
    identity_directories = sorted(base.iterdir())
    if any(path.is_symlink() or not path.is_dir() for path in identity_directories):
        raise SyncFailure("sync-storage-unsafe", "canonical coordination storage is unsafe")
    paths = sorted(
        item for directory in identity_directories for item in directory.glob("*.json")
    )
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise SyncFailure("sync-storage-unsafe", "canonical coordination storage is unsafe")
    return paths


def _check_raw_depth(raw: bytes) -> None:
    depth = 0
    in_string = False
    escaped = False
    for byte in raw:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in {0x7B, 0x5B}:
            depth += 1
            if depth > MAX_NESTING_DEPTH:
                raise SyncFailure("sync-depth-limit", "sync record nesting exceeds the v0 limit")
        elif byte in {0x7D, 0x5D}:
            depth -= 1


def _load_record_paths(root: Path, paths: list[Path]) -> list[StoredRecord]:
    records: list[StoredRecord] = []
    for path in paths:
        if len(path.stem) != 64 or any(
            character not in "0123456789abcdef" for character in path.stem
        ):
            raise SyncFailure(
                "local-record-path-mismatch",
                "canonical coordination storage has an invalid digest path",
            )
        try:
            raw = path.read_bytes()
            _check_raw_depth(raw)
            value = load_json_bytes(raw)
        except SyncFailure:
            raise
        except (OSError, RecursionError, ValidationFailure) as exc:
            raise SyncFailure(
                "local-record-invalid", "canonical coordination storage is unreadable"
            ) from exc
        if not isinstance(value, dict) or not isinstance(value.get("record_id"), str):
            raise SyncFailure(
                "local-record-invalid", "canonical coordination storage contains an invalid body"
            )
        claimed_digest = "sha-256:" + path.stem
        reference = _pair(value, claimed_digest)
        expected = _record_path(root, reference)
        if expected != path:
            raise SyncFailure(
                "local-record-path-mismatch",
                "canonical coordination storage path does not match its claimed pair",
            )
        records.append(StoredRecord(reference, value, raw, path))
    return records


def _scan_records(root: Path) -> list[StoredRecord]:
    return _load_record_paths(root, _record_files(root))


def _scan_record_identity(root: Path, record_id: str) -> list[StoredRecord]:
    """Read one record identity without traversing unrelated hub revisions."""
    _validate_storage_root(root, create=False)
    base = root / "canonical" / "coordination"
    if not base.exists():
        return []
    if base.is_symlink() or not base.is_dir():
        raise SyncFailure("sync-storage-unsafe", "canonical coordination storage is unsafe")
    identity_hash = hashlib.sha256(record_id.encode("utf-8")).hexdigest()
    directory = base / identity_hash
    if not directory.exists():
        return []
    if directory.is_symlink() or not directory.is_dir():
        raise SyncFailure("sync-storage-unsafe", "canonical coordination storage is unsafe")
    paths = sorted(directory.glob("*.json"))
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise SyncFailure("sync-storage-unsafe", "canonical coordination storage is unsafe")
    return _load_record_paths(root, paths)


def _validate_hub_config(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict) or set(config) != {
        "schema_id",
        "hub_id",
        "scope_generation",
        "bindings",
    }:
        raise SyncFailure("hub-config-invalid", "local hub configuration has an invalid shape")
    if config["schema_id"] != LOCAL_HUB_SCHEMA_ID:
        raise SyncFailure("hub-config-invalid", "local hub schema is unsupported")
    if not isinstance(config["hub_id"], str) or not config["hub_id"].startswith(
        "coordination-hub://"
    ):
        raise SyncFailure("hub-config-invalid", "hub_id is not a logical coordination hub ID")
    if (
        not isinstance(config["scope_generation"], int)
        or isinstance(config["scope_generation"], bool)
        or config["scope_generation"] < 0
    ):
        raise SyncFailure("hub-config-invalid", "scope_generation must be a non-negative integer")
    bindings = config["bindings"]
    if not isinstance(bindings, list):
        raise SyncFailure("hub-config-invalid", "bindings must be an array")
    principals: set[str] = set()
    sessions: set[str] = set()
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) != {
            "session_id",
            "principal_id",
            "access_label",
        }:
            raise SyncFailure("hub-config-invalid", "principal binding has an invalid shape")
        session_id = binding["session_id"]
        if (
            not isinstance(session_id, str)
            or not session_id.startswith("coordination-session://")
            or session_id in sessions
        ):
            raise SyncFailure("hub-config-invalid", "session binding is invalid or duplicated")
        sessions.add(session_id)
        principal = binding["principal_id"]
        if (
            not isinstance(principal, str)
            or not principal.startswith("coordination-principal://")
            or principal in principals
        ):
            raise SyncFailure("hub-config-invalid", "principal binding is invalid or duplicated")
        principals.add(principal)
        label, _ = validate_coordination_record_body(binding["access_label"])
        if label["schema_id"] != ACCESS_LABEL_SCHEMA_ID:
            raise SyncFailure("hub-config-invalid", "principal binding requires an AccessLabel")
    return deepcopy(config)


def configure_local_hub(
    hub: Path,
    *,
    hub_id: str,
    scope_generation: int,
    bindings: list[dict[str, Any]],
) -> None:
    """Write synthetic server-owned bindings and retain label revision history."""
    config = _validate_hub_config(
        {
            "schema_id": LOCAL_HUB_SCHEMA_ID,
            "hub_id": hub_id,
            "scope_generation": scope_generation,
            "bindings": bindings,
        }
    )
    for binding in config["bindings"]:
        label = binding["access_label"]
        reference = _pair(label)
        _write_immutable(
            hub,
            _policy_label_path(hub, reference),
            canonical_bytes(label),
        )
    _write_atomic(hub, hub / "hub-config.json", canonical_bytes(config))


def _binding(
    hub: Path, session_id: str
) -> tuple[dict[str, Any], dict[str, Any], str]:
    _validate_storage_root(hub, create=False)
    try:
        config = _validate_hub_config(load_json(hub / "hub-config.json"))
    except ValidationFailure as exc:
        if isinstance(exc, SyncFailure):
            raise
        raise SyncFailure("hub-config-invalid", "local hub configuration is unavailable") from exc
    matches = [item for item in config["bindings"] if item["session_id"] == session_id]
    if len(matches) != 1:
        raise SyncFailure(
            "principal-binding-invalid",
            "authenticated session must resolve to exactly one principal and AccessLabel",
        )
    return config, matches[0]["access_label"], matches[0]["principal_id"]


def _walk_bounds(value: Any, depth: int = 0) -> None:
    if depth > MAX_NESTING_DEPTH:
        raise SyncFailure("sync-depth-limit", "sync record nesting exceeds the v0 limit")
    if isinstance(value, str) and len(value.encode("utf-8")) > MAX_STRING_BYTES:
        raise SyncFailure("sync-field-too-large", "sync string field exceeds the v0 limit")
    if isinstance(value, list):
        for item in value:
            _walk_bounds(item, depth + 1)
    elif isinstance(value, dict):
        for key, item in value.items():
            _walk_bounds(key, depth + 1)
            _walk_bounds(item, depth + 1)


def _request_bounds(records: list[StoredRecord]) -> None:
    if len(records) > MAX_SUBMITTED_RECORDS:
        raise SyncFailure("sync-record-limit", "sync request exceeds the v0 record limit")
    if sum(len(item.raw) for item in records) > MAX_REQUEST_BYTES:
        raise SyncFailure("sync-request-too-large", "sync request exceeds the v0 byte limit")
    for item in records:
        if len(item.raw) > MAX_RECORD_BYTES:
            raise SyncFailure("sync-record-too-large", "sync record exceeds the v0 byte limit")
        _walk_bounds(item.record)


@contextmanager
def _advisory_lock(
    root: Path,
    identity: str,
    *,
    busy_code: str,
    busy_message: str,
) -> Iterator[None]:
    """Hold a crash-released OS lock; the persistent lock file is not state."""
    lock = (
        root
        / "locks"
        / f"{hashlib.sha256(identity.encode('utf-8')).hexdigest()}.lock"
    )
    _prepare_parent(root, lock)
    if lock.is_symlink() or (lock.exists() and not lock.is_file()):
        raise SyncFailure("sync-storage-unsafe", "sync lock storage is unsafe")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock, flags, 0o600)
    except OSError as exc:
        raise SyncFailure("sync-storage-unsafe", "sync lock storage is unavailable") from exc
    locked = False
    try:
        try:
            if os.name == "nt":
                import msvcrt

                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b"\0")
                    os.fsync(descriptor)
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except (BlockingIOError, OSError) as exc:
            raise SyncFailure(busy_code, busy_message) from exc
        yield
    finally:
        if locked:
            try:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(descriptor)


@contextmanager
def _principal_lock(hub: Path, principal_id: str) -> Iterator[None]:
    with _advisory_lock(
        hub,
        f"principal:{principal_id}",
        busy_code="sync-principal-busy",
        busy_message="one sync request is already in flight for this principal",
    ):
        yield


@contextmanager
def _task_admission_lock(hub: Path, record_id: str) -> Iterator[None]:
    """Serialize competing revisions of one TaskPacket identity across principals."""
    with _advisory_lock(
        hub,
        f"task-admission:{record_id}",
        busy_code="sync-task-admission-busy",
        busy_message="one task identity is already being admitted",
    ):
        yield


def _label_declares_project(label: dict[str, Any], project_id: str) -> bool:
    """Match record projects to UUID provenance carried by the bound label."""
    return any(item["projectId"] == project_id for item in label["projectNames"])


@contextmanager
def _projection_apply_lock(vault: Path) -> Iterator[None]:
    with _advisory_lock(
        vault,
        "projection-apply",
        busy_code="sync-local-apply-busy",
        busy_message="one pull response is already being applied to this vault",
    ):
        yield


def _submission_code(
    stored: StoredRecord,
    label: dict[str, Any],
    principal_id: str,
    hub_by_pair: dict[tuple[str, str], StoredRecord],
) -> str:
    record = stored.record
    try:
        materialized, actual_digest = validate_coordination_record_body(record)
    except ValidationFailure as exc:
        return (
            "unsupported-required-extension"
            if exc.code == "required-extension-unsupported"
            else "schema-invalid"
        )
    if actual_digest != stored.record_ref["revision_digest"]:
        return "digest-mismatch"
    schema_id = materialized["schema_id"]
    if schema_id == ACCESS_LABEL_SCHEMA_ID:
        return "unauthorized-record-type"
    effective_label = _pair(label)
    if materialized.get("accessLabelRef") != effective_label:
        return "label-mismatch"
    project_id = materialized["projectId"]
    permission = (
        "syncTaskPackets"
        if schema_id == TASK_PACKET_SCHEMA_ID
        else "syncWorkReceipts"
    )
    if project_id not in label["may"][permission]:
        return "unauthorized-project"
    if not _label_declares_project(label, project_id):
        return "schema-invalid"
    if schema_id == TASK_PACKET_SCHEMA_ID:
        if materialized["status"] != "open":
            return "principal-mismatch"
        key = _pair_key(stored.record_ref)
        if key not in hub_by_pair and any(
            candidate.record_ref["record_id"] == materialized["record_id"]
            for candidate in hub_by_pair.values()
        ):
            return "schema-invalid"
    if schema_id == WORK_RECEIPT_SCHEMA_ID:
        if materialized["writer"] != principal_id:
            return "principal-mismatch"
        task_key = _pair_key(materialized["taskRef"])
        task_entry = hub_by_pair.get(task_key)
        if task_entry is None:
            return "schema-invalid"
        try:
            task, task_digest = validate_coordination_record_body(task_entry.record)
        except ValidationFailure:
            return "schema-invalid"
        if (
            task_digest != task_entry.record_ref["revision_digest"]
            or task["schema_id"] != TASK_PACKET_SCHEMA_ID
            or task["status"] != "claimed"
            or task["projectId"] != project_id
            or task["accessLabelRef"] != materialized["accessLabelRef"]
            or task["assignedWriter"] != principal_id
        ):
            return "schema-invalid"
        if any(
            candidate.record.get("schema_id") == TASK_PACKET_SCHEMA_ID
            and candidate.record.get("predecessor") == materialized["taskRef"]
            for candidate in hub_by_pair.values()
        ):
            return "schema-invalid"
    return "admitted"


def _expected_outcome(code: str) -> str:
    if code == "admitted":
        return "admitted"
    if code == "same-pair-different-bytes":
        return "quarantined"
    return "rejected"


def _validate_submission_outcomes(
    outcomes: Any, *, require_order: bool
) -> None:
    outcome_schema = core_schemas()[SYNC_RECEIPT_SCHEMA_ID]["properties"][
        "submission_outcomes"
    ]
    try:
        validate(outcomes, outcome_schema)
    except ValidationFailure as exc:
        raise SyncFailure(
            "sync-outcomes-invalid", "submission outcomes are invalid"
        ) from exc
    if require_order and outcomes != sorted(
        outcomes, key=lambda item: _pair_key(item["record_ref"])
    ):
        raise SyncFailure("sync-outcomes-order-invalid", "submission outcomes are not canonical")
    if len({_pair_key(item["record_ref"]) for item in outcomes}) != len(outcomes):
        raise SyncFailure("sync-outcomes-duplicate", "submission outcomes contain a duplicate pair")
    if any(item["outcome"] != _expected_outcome(item["code"]) for item in outcomes):
        raise SyncFailure(
            "sync-outcome-code-mismatch",
            "submission outcome does not match its typed outcome code",
        )


def _outcome(reference: dict[str, str], code: str) -> dict[str, Any]:
    return {
        "record_ref": deepcopy(reference),
        "outcome": _expected_outcome(code),
        "code": code,
    }


def _canonical_record_bytes(stored: StoredRecord) -> bytes:
    return canonical_bytes(stored.record)


def _quarantine_collision(
    hub: Path, existing: StoredRecord, incoming: StoredRecord
) -> None:
    report = {
        "claimed_pair": deepcopy(incoming.record_ref),
        "observed_content_digests": sorted(
            {
                sha256_bytes(_canonical_record_bytes(existing)),
                sha256_bytes(_canonical_record_bytes(incoming)),
            }
        ),
        "outcome": "quarantined",
        "code": "same-pair-different-bytes",
    }
    name = sha256_bytes(canonical_bytes(report)).removeprefix("sha-256:") + ".json"
    _write_immutable(
        hub,
        hub / "quarantine" / "coordination" / name,
        canonical_bytes(report),
    )


def _admit_submission(
    hub: Path,
    stored: StoredRecord,
    label: dict[str, Any],
    principal_id: str,
    hub_by_pair: dict[tuple[str, str], StoredRecord],
) -> dict[str, Any]:
    key = _pair_key(stored.record_ref)
    existing = hub_by_pair.get(key)
    if (
        existing is not None
        and _canonical_record_bytes(existing) != _canonical_record_bytes(stored)
    ):
        _quarantine_collision(hub, existing, stored)
        return _outcome(stored.record_ref, "same-pair-different-bytes")
    code = _submission_code(stored, label, principal_id, hub_by_pair)
    if code != "admitted" or existing is not None:
        return _outcome(stored.record_ref, code)
    materialized, _ = validate_coordination_record_body(stored.record)
    canonical_raw = canonical_bytes(materialized)
    path = _record_path(hub, stored.record_ref)
    _write_immutable(hub, path, canonical_raw)
    hub_by_pair[key] = StoredRecord(
        stored.record_ref,
        materialized,
        canonical_raw,
        path,
    )
    return _outcome(stored.record_ref, code)


def _known_hub_pairs(
    vault: Path, hub_id: str, principal_id: str
) -> set[tuple[str, str]]:
    """Recover acknowledged hub membership only from verified prior projections."""
    _validate_storage_root(vault, create=False)
    roots = vault / "generated" / "coordination-sync" / "projections"
    known: set[tuple[str, str]] = set()
    if not roots.exists():
        return known
    if roots.is_symlink() or not roots.is_dir():
        raise SyncFailure("sync-storage-unsafe", "sync projection storage is unsafe")
    projections = sorted(roots.iterdir())
    if any(item.is_symlink() or not item.is_dir() for item in projections):
        raise SyncFailure("sync-storage-unsafe", "sync projection storage is unsafe")
    for projection in projections:
        try:
            receipt = load_json(projection / "receipt.json")
            pairs = load_json(projection / "authorized-membership.json")
        except (KeyError, TypeError, ValueError, ValidationFailure):
            continue
        if not isinstance(receipt, dict) or not isinstance(pairs, list):
            continue
        try:
            validate_sync_receipt(receipt)
            if (
                receipt["hub_id"] != hub_id
                or receipt["principal_id"] != principal_id
                or len(pairs) != receipt["authorized_membership"]["pair_count"]
                or pair_set_digest(pairs)
                != receipt["authorized_membership"]["pair_set_digest"]
            ):
                continue
        except ValidationFailure:
            continue
        known.update(_pair_key(pair) for pair in pairs)
        known.update(
            _pair_key(item["record_ref"])
            for item in receipt["submission_outcomes"]
            if item["outcome"] == "admitted"
        )
    return known


def _pending_outcomes_path(vault: Path) -> Path:
    return vault / "generated" / "coordination-sync" / "pending-submission-outcomes.json"


def _pending_outcomes_envelope(
    *,
    config: dict[str, Any],
    label: dict[str, Any],
    principal_id: str,
    session_id: str,
    outcomes: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_id": PENDING_OUTCOMES_SCHEMA_ID,
        "hub_id": config["hub_id"],
        "principal_id": principal_id,
        "session_id": session_id,
        "access_label_ref": _pair(label),
        "scope_generation": config["scope_generation"],
        "submission_outcomes": deepcopy(outcomes),
    }


def _load_pending_outcomes(
    vault: Path,
    *,
    hub: Path,
    config: dict[str, Any],
    label: dict[str, Any],
    principal_id: str,
    session_id: str,
) -> PendingOutcomes:
    _validate_storage_root(vault, create=False)
    path = _pending_outcomes_path(vault)
    if not path.exists():
        return PendingOutcomes([], _pair(label), config["scope_generation"])
    if path.is_symlink() or not path.is_file():
        raise SyncFailure("sync-storage-unsafe", "pending sync outcome storage is unsafe")
    try:
        value = load_json(path)
    except ValidationFailure as exc:
        raise SyncFailure("sync-outcomes-invalid", "pending submission outcomes are invalid") from exc
    required = {
        "schema_id",
        "hub_id",
        "principal_id",
        "session_id",
        "access_label_ref",
        "scope_generation",
        "submission_outcomes",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise SyncFailure("sync-outcomes-invalid", "pending submission outcomes are invalid")
    expected_binding = {
        "schema_id": PENDING_OUTCOMES_SCHEMA_ID,
        "hub_id": config["hub_id"],
        "principal_id": principal_id,
        "session_id": session_id,
    }
    if any(value[field] != expected for field, expected in expected_binding.items()):
        raise SyncFailure(
            "sync-pending-binding-mismatch",
            "pending submission outcomes belong to another authenticated binding",
        )
    pending_label_ref = value["access_label_ref"]
    pending_generation = value["scope_generation"]
    current_label_ref = _pair(label)
    if (
        not isinstance(pending_label_ref, dict)
        or set(pending_label_ref) != {"record_id", "revision_digest"}
        or not isinstance(pending_label_ref.get("record_id"), str)
        or not isinstance(pending_label_ref.get("revision_digest"), str)
        or not isinstance(pending_generation, int)
        or isinstance(pending_generation, bool)
        or pending_generation < 0
        or pending_generation > config["scope_generation"]
    ):
        raise SyncFailure(
            "sync-pending-binding-mismatch",
            "pending submission outcomes have an invalid label generation binding",
        )
    try:
        validate(
            pending_label_ref,
            core_schemas()[SYNC_RECEIPT_SCHEMA_ID]["properties"]["access_label_ref"],
        )
    except ValidationFailure as exc:
        raise SyncFailure(
            "sync-pending-binding-mismatch",
            "pending submission outcomes have an invalid AccessLabel reference",
        ) from exc
    if pending_label_ref != current_label_ref:
        if pending_label_ref["record_id"] != current_label_ref["record_id"]:
            raise SyncFailure(
                "sync-pending-binding-mismatch",
                "pending submission outcomes belong to another AccessLabel identity",
            )
        _retained_policy_label(
            hub,
            pending_label_ref,
            failure_code="sync-pending-binding-mismatch",
            failure_message=(
                "pending submission outcomes do not match retained AccessLabel history"
            ),
        )
    outcomes = value["submission_outcomes"]
    _validate_submission_outcomes(outcomes, require_order=True)
    return PendingOutcomes(
        deepcopy(outcomes), deepcopy(pending_label_ref), pending_generation
    )


def push(
    vault: Path,
    hub: Path,
    *,
    session_id: str,
) -> list[dict[str, Any]]:
    """Push every local pair through server-owned policy as an idempotent union."""
    config, label, principal_id = _binding(hub, session_id)
    known = _known_hub_pairs(vault, config["hub_id"], principal_id)
    # A pending receipt is binding-specific. Refuse to overwrite another
    # authenticated session's unacknowledged evidence.
    pending = _load_pending_outcomes(
        vault,
        hub=hub,
        config=config,
        label=label,
        principal_id=principal_id,
        session_id=session_id,
    )
    if pending.outcomes and (
        pending.access_label_ref != _pair(label)
        or pending.scope_generation != config["scope_generation"]
    ):
        raise SyncFailure(
            "sync-pending-reconciliation-required",
            "pull must acknowledge pending submission outcomes before pushing under a rotated scope",
        )
    outcomes: list[dict[str, Any]] = []
    with _principal_lock(hub, principal_id):
        known_paths = {
            _record_path(
                vault,
                {"record_id": record_id, "revision_digest": revision_digest},
            )
            for record_id, revision_digest in known
        }
        submission_paths = [
            path for path in _record_files(vault) if path not in known_paths
        ]
        if len(submission_paths) > MAX_SUBMITTED_RECORDS:
            raise SyncFailure("sync-record-limit", "sync request exceeds the v0 record limit")
        sizes = [path.stat().st_size for path in submission_paths]
        if any(size > MAX_RECORD_BYTES for size in sizes):
            raise SyncFailure("sync-record-too-large", "sync record exceeds the v0 byte limit")
        if sum(sizes) > MAX_REQUEST_BYTES:
            raise SyncFailure("sync-request-too-large", "sync request exceeds the v0 byte limit")
        submissions = _load_record_paths(vault, submission_paths)
        _request_bounds(submissions)
        hub_by_pair = {_pair_key(item.record_ref): item for item in _scan_records(hub)}
        for stored in submissions:
            if (
                stored.record.get("schema_id") == TASK_PACKET_SCHEMA_ID
                and isinstance(stored.record.get("record_id"), str)
            ):
                record_id = stored.record["record_id"]
                with _task_admission_lock(hub, record_id):
                    for existing in _scan_record_identity(hub, record_id):
                        hub_by_pair[_pair_key(existing.record_ref)] = existing
                    outcomes.append(
                        _admit_submission(
                            hub, stored, label, principal_id, hub_by_pair
                        )
                    )
            else:
                outcomes.append(
                    _admit_submission(hub, stored, label, principal_id, hub_by_pair)
                )
    outcomes.sort(key=lambda item: _pair_key(item["record_ref"]))
    _write_atomic(
        vault,
        _pending_outcomes_path(vault),
        canonical_bytes(
            _pending_outcomes_envelope(
                config=config,
                label=label,
                principal_id=principal_id,
                session_id=session_id,
                outcomes=outcomes,
            )
        ),
    )
    return outcomes


def _authorized_records(
    hub: Path, label: dict[str, Any]
) -> tuple[list[StoredRecord], int]:
    allowed = set(label["may"]["readProjects"])
    denied = set(label["mayNot"]["readProjects"])
    authorized: list[StoredRecord] = []
    policy_labels: dict[tuple[str, str], dict[str, Any]] = {}
    all_records = _scan_records(hub)
    for stored in all_records:
        try:
            record, digest = validate_coordination_record_body(stored.record)
        except ValidationFailure as exc:
            raise SyncFailure("hub-record-invalid", "hub contains an invalid record") from exc
        if digest != stored.record_ref["revision_digest"]:
            raise SyncFailure("hub-record-invalid", "hub record digest does not match its pair")
        if record.get("schema_id") == ACCESS_LABEL_SCHEMA_ID:
            continue
        project_id = record.get("projectId")
        bound_ref = record["accessLabelRef"]
        bound_key = _pair_key(bound_ref)
        if bound_key not in policy_labels:
            policy_labels[bound_key] = _retained_policy_label(
                hub,
                bound_ref,
                failure_code="hub-record-invalid",
                failure_message=(
                    "hub record names an unavailable or invalid AccessLabel revision"
                ),
            )
        bound_label = policy_labels[bound_key]
        bound_allowed = set(bound_label["may"]["readProjects"])
        bound_denied = set(bound_label["mayNot"]["readProjects"])
        if (
            project_id in allowed
            and project_id not in denied
            and project_id in bound_allowed
            and project_id not in bound_denied
        ):
            authorized.append(stored)
    authorized.sort(key=lambda item: _pair_key(item.record_ref))
    policy_label_root = hub / "policy" / "labels"
    protected_label_count = (
        len(list(policy_label_root.glob("*/*.json")))
        if policy_label_root.exists()
        else 0
    )
    return authorized, len(all_records) - len(authorized) + protected_label_count


def _page_pair_groups(pairs: list[dict[str, str]]) -> list[list[dict[str, str]]]:
    if not pairs:
        return [[]]
    groups: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    for pair in pairs:
        candidate = current + [pair]
        # The real page adds bounded fixed metadata; reserve 1 KiB for it.
        if current and (
            len(current) >= MAX_PAGE_RECORDS
            or len(canonical_bytes(candidate)) + 1024 > MAX_PAGE_BYTES
        ):
            groups.append(current)
            current = [pair]
        else:
            current = candidate
    groups.append(current)
    return groups


def _record_page_groups(records: list[StoredRecord]) -> list[list[StoredRecord]]:
    if not records:
        return [[]]
    groups: list[list[StoredRecord]] = []
    current: list[StoredRecord] = []
    for record in records:
        candidate = current + [record]
        candidate_body = {
            "pairs": [item.record_ref for item in candidate],
            "records": [item.record for item in candidate],
        }
        if current and (
            len(current) >= MAX_PAGE_RECORDS
            or len(canonical_bytes(candidate_body)) + 1024 > MAX_PAGE_BYTES
        ):
            groups.append(current)
            current = [record]
        else:
            current = candidate
    groups.append(current)
    return groups


def _continuation_token(
    receipt_id: str, principal_id: str, generation: int, next_page: int
) -> str:
    return "continuation://sha-256/" + hashlib.sha256(
        canonical_bytes(
            {
                "receipt_ref": receipt_id,
                "principal_id": principal_id,
                "scope_generation": generation,
                "next_page": next_page,
            }
        )
    ).hexdigest()


def build_membership_pages(
    pairs: list[dict[str, str]], receipt_id: str, principal_id: str, generation: int
) -> list[dict[str, Any]]:
    return _membership_pages_from_groups(
        _page_pair_groups(pairs), receipt_id, principal_id, generation
    )


def _membership_pages_from_groups(
    groups: list[list[dict[str, str]]],
    receipt_id: str,
    principal_id: str,
    generation: int,
) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for index, group in enumerate(groups):
        token = None
        if index + 1 < len(groups):
            token = _continuation_token(
                receipt_id, principal_id, generation, index + 1
            )
        pages.append(
            {
                "schema_id": MEMBERSHIP_PAGE_SCHEMA_ID,
                "receipt_ref": receipt_id,
                "page_index": index,
                "page_count": len(groups),
                "pairs": deepcopy(group),
                "next_token": token,
            }
        )
    return pages


def validate_sync_receipt(receipt: dict[str, Any]) -> None:
    validate(receipt, core_schemas()[SYNC_RECEIPT_SCHEMA_ID])
    expected = expected_receipt_id(receipt, "coordination-sync-receipt://sha-256/")
    if receipt["receipt_id"] != expected:
        raise SyncFailure("sync-receipt-identity-mismatch", "sync receipt identity is invalid")
    _validate_submission_outcomes(receipt["submission_outcomes"], require_order=True)


def validate_membership_pages(
    receipt: dict[str, Any], pages: list[dict[str, Any]]
) -> list[dict[str, str]]:
    validate_sync_receipt(receipt)
    membership = receipt["authorized_membership"]
    if len(pages) != membership["page_count"]:
        raise SyncFailure("sync-page-missing", "membership page count is incomplete")
    seen_indexes: set[int] = set()
    pairs: list[dict[str, str]] = []
    for page in pages:
        validate(page, core_schemas()[MEMBERSHIP_PAGE_SCHEMA_ID])
        index = page["page_index"]
        if index in seen_indexes:
            raise SyncFailure("sync-page-duplicate", "membership page index is duplicated")
        seen_indexes.add(index)
        if page["receipt_ref"] != receipt["receipt_id"]:
            raise SyncFailure("sync-page-receipt-mismatch", "membership page names another receipt")
        if page["page_count"] != membership["page_count"]:
            raise SyncFailure("sync-page-count-mismatch", "membership page count conflicts")
        expected_token = (
            None
            if index + 1 == membership["page_count"]
            else _continuation_token(
                receipt["receipt_id"],
                receipt["principal_id"],
                receipt["scope_generation"],
                index + 1,
            )
        )
        if page["next_token"] != expected_token:
            raise SyncFailure("sync-page-token-invalid", "membership continuation state is invalid")
        if len(canonical_bytes(page)) > MAX_PAGE_BYTES:
            raise SyncFailure("sync-page-too-large", "membership page exceeds the v0 byte limit")
        pairs.extend(page["pairs"])
    if seen_indexes != set(range(membership["page_count"])):
        raise SyncFailure("sync-page-missing", "membership page indexes are incomplete")
    keys = [_pair_key(item) for item in pairs]
    if len(set(keys)) != len(keys):
        raise SyncFailure("sync-membership-duplicate", "membership contains a duplicate pair")
    canonical = sorted_pairs(pairs)
    if len(canonical) != membership["pair_count"]:
        raise SyncFailure("sync-membership-count-mismatch", "membership pair count is invalid")
    if pair_set_digest(canonical) != membership["pair_set_digest"]:
        raise SyncFailure("sync-membership-digest-mismatch", "membership pair-set digest is invalid")
    return canonical


def build_pull_response(
    hub: Path,
    *,
    session_id: str,
    completed_at: str,
    submission_outcomes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    config, label, principal_id = _binding(hub, session_id)
    with _principal_lock(hub, principal_id):
        records, excluded_count = _authorized_records(hub, label)
    pairs = [item.record_ref for item in records]
    record_groups = _record_page_groups(records)
    pair_groups = [[item.record_ref for item in group] for group in record_groups]
    outcomes = deepcopy(submission_outcomes or [])
    _validate_submission_outcomes(outcomes, require_order=False)
    body = {
        "hub_id": config["hub_id"],
        "principal_id": principal_id,
        "access_label_ref": _pair(label),
        "scope_generation": config["scope_generation"],
        "completed_at": completed_at,
        "authorized_membership": {
            "pair_count": len(pairs),
            "pair_set_digest": pair_set_digest(pairs),
            "page_count": len(pair_groups),
        },
        "excluded_count": excluded_count,
        "submission_outcomes": sorted(outcomes, key=lambda item: _pair_key(item["record_ref"])),
        "transport_state": "authenticated",
        "issuer_state": "unverified",
        "authority_boundary": AUTHORITY_BOUNDARY,
    }
    receipt = receipt_with_digest(
        SYNC_RECEIPT_SCHEMA_ID,
        "coordination-sync-receipt://sha-256/",
        body,
    )
    pages = _membership_pages_from_groups(
        pair_groups,
        receipt["receipt_id"],
        principal_id,
        config["scope_generation"],
    )
    validate_membership_pages(receipt, pages)
    return {
        "receipt": receipt,
        "pages": pages,
        "record_pages": [
            [deepcopy(item.record) for item in group] for group in record_groups
        ],
    }


def _projection_root(vault: Path, receipt_id: str) -> Path:
    return (
        vault
        / "generated"
        / "coordination-sync"
        / "projections"
        / receipt_id.rsplit("/", 1)[-1]
    )


def _load_current_projection(
    vault: Path,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, str]]]:
    _validate_storage_root(vault, create=False)
    marker_path = vault / "generated" / "coordination-sync" / "last-successful.json"
    try:
        marker = load_json(marker_path)
    except ValidationFailure as exc:
        raise SyncFailure("sync-marker-invalid", "successful sync marker is invalid") from exc
    required_marker_fields = {
        "receipt_ref",
        "pair_count",
        "pair_set_digest",
        "scope_generation",
        "access_label_ref",
    }
    if not isinstance(marker, dict) or set(marker) != required_marker_fields:
        raise SyncFailure("sync-marker-invalid", "successful sync marker is invalid")
    receipt_ref = marker["receipt_ref"]
    prefix = "coordination-sync-receipt://sha-256/"
    if (
        not isinstance(receipt_ref, str)
        or not receipt_ref.startswith(prefix)
        or len(receipt_ref.removeprefix(prefix)) != 64
        or any(
            character not in "0123456789abcdef"
            for character in receipt_ref.removeprefix(prefix)
        )
    ):
        raise SyncFailure("sync-marker-invalid", "successful sync marker is invalid")
    projection = _projection_root(vault, receipt_ref)
    receipt_path = projection / "receipt.json"
    manifest_path = projection / "authorized-membership.json"
    if receipt_path.is_symlink() or manifest_path.is_symlink():
        raise SyncFailure("sync-storage-unsafe", "sync projection storage is unsafe")
    try:
        receipt = load_json(receipt_path)
        pairs = load_json(manifest_path)
    except ValidationFailure as exc:
        raise SyncFailure("sync-projection-invalid", "authorized projection is invalid") from exc
    if not isinstance(receipt, dict) or not isinstance(pairs, list):
        raise SyncFailure("sync-projection-invalid", "authorized projection is invalid")
    validate_sync_receipt(receipt)
    membership = receipt["authorized_membership"]
    if (
        marker["receipt_ref"] != receipt["receipt_id"]
        or marker["scope_generation"] != receipt["scope_generation"]
        or marker["access_label_ref"] != receipt["access_label_ref"]
        or marker["pair_count"] != membership["pair_count"]
        or marker["pair_set_digest"] != membership["pair_set_digest"]
        or len(pairs) != membership["pair_count"]
        or pair_set_digest(pairs) != membership["pair_set_digest"]
    ):
        raise SyncFailure(
            "sync-projection-mismatch",
            "successful marker, receipt, and authorized membership do not agree",
        )
    return marker, receipt, sorted_pairs(pairs)


def _parse_receipt_time(value: str) -> datetime:
    try:
        normalized = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
        return datetime.fromisoformat(normalized)
    except (AttributeError, TypeError, ValueError) as exc:
        raise SyncFailure(
            "sync-receipt-time-invalid", "sync receipt completed_at is invalid"
        ) from exc


def _apply_verified_pull(
    vault: Path,
    receipt: dict[str, Any],
    pairs: list[dict[str, str]],
    by_pair: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    marker_path = vault / "generated" / "coordination-sync" / "last-successful.json"
    if marker_path.exists():
        _, prior_receipt, prior_manifest = _load_current_projection(vault)
        if (
            prior_receipt["hub_id"] != receipt["hub_id"]
            or prior_receipt["principal_id"] != receipt["principal_id"]
        ):
            raise SyncFailure(
                "sync-binding-mismatch",
                "pull response does not match the vault's successful hub and principal binding",
            )
        if receipt["scope_generation"] < prior_receipt["scope_generation"]:
            raise SyncFailure(
                "sync-generation-stale",
                "pull response uses a prior scope generation",
            )
        prior_completed = _parse_receipt_time(prior_receipt["completed_at"])
        current_completed = _parse_receipt_time(receipt["completed_at"])
        if current_completed < prior_completed:
            raise SyncFailure(
                "sync-receipt-stale",
                "pull response predates the last successful sync receipt",
            )
        same_scope = (
            prior_receipt["access_label_ref"] == receipt["access_label_ref"]
            and prior_receipt["scope_generation"] == receipt["scope_generation"]
        )
        if same_scope and not {
            _pair_key(pair) for pair in prior_manifest
        }.issubset({_pair_key(pair) for pair in pairs}):
            raise SyncFailure(
                "sync-membership-regression",
                "an unchanged scope generation cannot remove authorized membership",
            )
        if (
            same_scope
            and prior_receipt["authorized_membership"]
            == receipt["authorized_membership"]
            and prior_receipt["excluded_count"] == receipt["excluded_count"]
            and not receipt["submission_outcomes"]
        ):
            # A no-op is valid only if the local authorized material still
            # matches the previously verified marker and projection.
            load_authorized_projection(vault)
            try:
                _pending_outcomes_path(vault).unlink()
            except FileNotFoundError:
                pass
            return {
                "outcome": "no-op",
                "receipt": prior_receipt,
                "authorized_pairs": prior_manifest,
            }

    # Canonical history is append-only and is never pruned by label rotation.
    for pair in pairs:
        record = by_pair[_pair_key(pair)]
        _write_immutable(vault, _record_path(vault, pair), canonical_bytes(record))

    projection = _projection_root(vault, receipt["receipt_id"])
    _write_immutable(vault, projection / "receipt.json", canonical_bytes(receipt))
    _write_immutable(
        vault,
        projection / "authorized-membership.json",
        canonical_bytes(pairs),
    )
    marker = {
        "receipt_ref": receipt["receipt_id"],
        "pair_count": len(pairs),
        "pair_set_digest": pair_set_digest(pairs),
        "scope_generation": receipt["scope_generation"],
        "access_label_ref": receipt["access_label_ref"],
    }
    _write_atomic(vault, marker_path, canonical_bytes(marker))
    try:
        _pending_outcomes_path(vault).unlink()
    except FileNotFoundError:
        pass
    return {"outcome": "complete", "receipt": receipt, "authorized_pairs": pairs}


def apply_pull_response(vault: Path, response: dict[str, Any]) -> dict[str, Any]:
    """Verify a complete pull before appending records and advancing the marker."""
    if not isinstance(response, dict) or set(response) != {
        "receipt",
        "pages",
        "record_pages",
    }:
        raise SyncFailure("sync-response-invalid", "pull response has an invalid shape")
    receipt = response["receipt"]
    pages = response["pages"]
    record_pages = response["record_pages"]
    if (
        not isinstance(receipt, dict)
        or not isinstance(pages, list)
        or not isinstance(record_pages, list)
    ):
        raise SyncFailure("sync-response-invalid", "pull response has invalid field types")
    pairs = validate_membership_pages(receipt, pages)
    if len(record_pages) != len(pages) or any(
        not isinstance(page, list) for page in record_pages
    ):
        raise SyncFailure("sync-record-page-mismatch", "pull record pages are incomplete")
    by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for page, record_page in zip(pages, record_pages):
        if len(record_page) > MAX_PAGE_RECORDS or len(
            canonical_bytes({"pairs": page["pairs"], "records": record_page})
        ) + 1024 > MAX_PAGE_BYTES:
            raise SyncFailure("sync-page-too-large", "pull record page exceeds the v0 limit")
        page_keys: set[tuple[str, str]] = set()
        for record in record_page:
            materialized, digest = validate_coordination_record_body(record)
            if materialized["schema_id"] == ACCESS_LABEL_SCHEMA_ID:
                raise SyncFailure(
                    "sync-record-type-unauthorized",
                    "restricted sync responses cannot contain AccessLabel bodies",
                )
            reference = _pair(materialized, digest)
            key = _pair_key(reference)
            if key in by_pair:
                raise SyncFailure("sync-record-duplicate", "pull response contains a duplicate record")
            page_keys.add(key)
            by_pair[key] = materialized
        if page_keys != {_pair_key(item) for item in page["pairs"]}:
            raise SyncFailure(
                "sync-record-page-mismatch",
                "pull record page does not match its authorized membership page",
            )
    if set(by_pair) != {_pair_key(item) for item in pairs}:
        raise SyncFailure("sync-record-set-mismatch", "pull records do not match authorized membership")
    with _projection_apply_lock(vault):
        return _apply_verified_pull(vault, receipt, pairs, by_pair)


def pull(
    vault: Path,
    hub: Path,
    *,
    session_id: str,
    completed_at: str,
) -> dict[str, Any]:
    config, label, principal_id = _binding(hub, session_id)
    pending = _load_pending_outcomes(
        vault,
        hub=hub,
        config=config,
        label=label,
        principal_id=principal_id,
        session_id=session_id,
    )
    response = build_pull_response(
        hub,
        session_id=session_id,
        completed_at=completed_at,
        submission_outcomes=pending.outcomes,
    )
    return apply_pull_response(vault, response)


def sync(
    vault: Path,
    hub: Path,
    *,
    session_id: str,
    completed_at: str,
    phase: str = "both",
) -> dict[str, Any]:
    if phase not in {"push", "pull", "both"}:
        raise SyncFailure("sync-phase-invalid", "sync phase must be push, pull, or both")
    result: dict[str, Any] = {"outcome": "complete", "phase": phase}
    if phase in {"push", "both"}:
        result["submission_outcomes"] = push(vault, hub, session_id=session_id)
    if phase in {"pull", "both"}:
        pulled = pull(
            vault,
            hub,
            session_id=session_id,
            completed_at=completed_at,
        )
        result.update(pulled)
        result["phase"] = phase
    return result


def load_authorized_projection(vault: Path) -> list[dict[str, Any]]:
    """Load only the verified generated authorization view for context consumers."""
    _validate_storage_root(vault, create=False)
    if not (vault / "generated" / "coordination-sync" / "last-successful.json").exists():
        raise SyncFailure("sync-marker-missing", "no successful authorized sync projection exists")
    _, _, pairs = _load_current_projection(vault)
    records: list[dict[str, Any]] = []
    for pair in sorted_pairs(pairs):
        path = _record_path(vault, pair)
        if path.is_symlink():
            raise SyncFailure("sync-storage-unsafe", "authorized local record path is unsafe")
        try:
            record = load_json(path)
        except ValidationFailure as exc:
            raise SyncFailure("sync-local-record-missing", "authorized local record is unavailable") from exc
        if not isinstance(record, dict):
            raise SyncFailure("sync-local-record-mismatch", "authorized local record has changed")
        try:
            materialized, digest = validate_coordination_record_body(record)
        except ValidationFailure as exc:
            raise SyncFailure("sync-local-record-mismatch", "authorized local record has changed") from exc
        if _pair(materialized, digest) != pair:
            raise SyncFailure("sync-local-record-mismatch", "authorized local record has changed")
        records.append(materialized)
    return records


def export_authorized_coordination_context(vault: Path) -> dict[str, Any]:
    """Generated informational view; AM-5 owns rendered kickoff-pack behavior."""
    records = load_authorized_projection(vault)
    return {
        "records": records,
        "record_count": len(records),
        "authority_boundary": (
            "informational only; no execution, mutation, routing, disclosure, "
            "credential, spending, deployment, approval, or merge authority"
        ),
    }


def directory_digest(root: Path) -> str:
    """Stable test helper for byte-identical no-op assertions."""
    entries: list[dict[str, str]] = []
    if root.exists():
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            entries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "digest": sha256_bytes(path.read_bytes()),
                }
            )
    return sha256_bytes(canonical_bytes(entries))
