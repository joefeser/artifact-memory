"""Reproducible synthetic performance and resource-safety baseline."""

from __future__ import annotations

import gc
import hashlib
import io
import json
import platform
import tempfile
import time
import tracemalloc
import zipfile
from pathlib import Path
from typing import Any, Callable, TypeVar

from .archive import inspect_zip
from .canonical import (
    canonical_bytes,
    expected_receipt_id,
    receipt_with_digest,
    sha256_bytes,
)
from .projection import _create_sqlite, _record_lines, canonical_records, project_records
from .scan import ScanLimits, scan_path
from .scan_conformance import run_scan_conformance
from .schema_resources import load_schema
from .validator import ValidationFailure, validate


T = TypeVar("T")
MAX_BENCHMARK_BYTES = 512 * 1024 * 1024
MAX_BENCHMARK_FILES = 100_000
MAX_BENCHMARK_DEPTH = 64
MAX_BENCHMARK_RECORDS = 100_000
SUPPORTED_RUNTIME_FAMILIES = {
    "Darwin": "darwin",
    "Linux": "linux",
    "Windows": "windows",
}
DEFAULT_PROFILE = {
    "schema_id": "artifact-memory/benchmark-profile/v1",
    "profile_id": "synthetic-v0-resource-baseline",
    "file_count": 1_024,
    "small_file_size_bytes": 4_096,
    "large_file_size_bytes": 8 * 1024 * 1024,
    "depth": 32,
    "projection_record_count": 1_024,
    "scan_byte_limit": 16_384,
    "scan_entry_limit": 16,
    "archive_max_entries": 16,
    "archive_max_uncompressed_bytes": 1_048_576,
    "nested_archive_depth": 8,
}
AUTHORITY_BOUNDARY = (
    "benchmark evidence grants no capacity guarantee, execution, mutation, "
    "deployment, spending, disclosure, or approval authority"
)


def _record(index: int) -> dict[str, Any]:
    suffix = f"{index:06d}"
    return {
        "schema_id": "artifact-memory/knowledge-record/v1",
        "record_id": f"record://synthetic/benchmark-{suffix}",
        "record_type": "note",
        "lifecycle": "accepted",
        "meaning": {
            "summary": "Synthetic benchmark record.",
            "labels": ["synthetic", "benchmark"],
        },
        "artifact_refs": [f"artifact://synthetic/benchmark-{suffix}"],
        "provenance": [
            {
                "kind": "observation",
                "source_ref": "fixture://synthetic/benchmarks/v1/profile.json",
            }
        ],
        "sensitivity": "public",
    }


def _positive_integer(profile: dict[str, Any], name: str, maximum: int) -> int:
    value = profile.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > maximum:
        raise ValidationFailure(
            "benchmark-profile-invalid",
            f"{name} must be a positive integer no greater than {maximum}",
            f"$.{name}",
        )
    return value


def validate_profile(profile: Any) -> dict[str, Any]:
    """Fail closed before a caller-controlled profile can consume resources."""
    try:
        validate(profile, load_schema("core", "benchmark-profile.v1.schema.json"))
    except ValidationFailure as exc:
        raise ValidationFailure(
            "benchmark-profile-invalid",
            "benchmark profile does not satisfy the supported contract",
            exc.path,
        ) from exc
    file_count = _positive_integer(profile, "file_count", MAX_BENCHMARK_FILES)
    small_size = _positive_integer(profile, "small_file_size_bytes", MAX_BENCHMARK_BYTES)
    large_size = _positive_integer(profile, "large_file_size_bytes", MAX_BENCHMARK_BYTES)
    _positive_integer(profile, "depth", MAX_BENCHMARK_DEPTH)
    record_count = _positive_integer(
        profile, "projection_record_count", MAX_BENCHMARK_RECORDS
    )
    scan_byte_limit = _positive_integer(profile, "scan_byte_limit", MAX_BENCHMARK_BYTES)
    scan_entry_limit = _positive_integer(
        profile, "scan_entry_limit", MAX_BENCHMARK_FILES
    )
    _positive_integer(profile, "archive_max_entries", MAX_BENCHMARK_FILES)
    archive_max_uncompressed_bytes = _positive_integer(
        profile, "archive_max_uncompressed_bytes", MAX_BENCHMARK_BYTES
    )
    nested_archive_depth = _positive_integer(
        profile, "nested_archive_depth", MAX_BENCHMARK_DEPTH
    )
    corpus_bytes = max(file_count - 1, 0) * small_size + large_size
    if corpus_bytes > MAX_BENCHMARK_BYTES:
        raise ValidationFailure(
            "benchmark-profile-invalid",
            "benchmark corpus exceeds the harness byte ceiling",
            "$.large_file_size_bytes",
        )
    if scan_byte_limit >= corpus_bytes:
        raise ValidationFailure(
            "benchmark-profile-invalid",
            "scan byte limit must exercise a partial result",
            "$.scan_byte_limit",
        )
    if scan_entry_limit >= file_count:
        raise ValidationFailure(
            "benchmark-profile-invalid",
            "scan entry limit must exercise a partial result",
            "$.scan_entry_limit",
        )
    if file_count + record_count > MAX_BENCHMARK_FILES:
        raise ValidationFailure(
            "benchmark-profile-invalid",
            "benchmark corpus and projection records exceed the aggregate file ceiling",
            "$.projection_record_count",
        )
    _, _, nested_entry_size = _nested_archive_payload(nested_archive_depth)
    if archive_max_uncompressed_bytes < nested_entry_size:
        raise ValidationFailure(
            "benchmark-profile-invalid",
            "archive byte limit cannot admit the generated outer archive entry",
            "$.archive_max_uncompressed_bytes",
        )
    return dict(profile)


def _repeat_to_size(seed: bytes, byte_size: int) -> bytes:
    return (seed * ((byte_size + len(seed) - 1) // len(seed)))[:byte_size]


def _make_corpus(
    root: Path,
    *,
    file_count: int,
    small_file_size: int,
    large_file_size: int,
    depth: int,
) -> int:
    repeated = (
        _repeat_to_size(b"synthetic-repeat\n", small_file_size)
        if file_count > 1
        else b""
    )
    for index in range(file_count - 1):
        if index == 0:
            directory = root.joinpath(*(f"d{level:02d}" for level in range(depth)))
        else:
            directory = root / f"shard-{index % 32:02d}"
        directory.mkdir(parents=True, exist_ok=True)
        payload = (
            repeated
            if index % 2 == 0
            else _repeat_to_size(hashlib.sha256(f"synthetic-{index}".encode()).digest(), small_file_size)
        )
        (directory / f"item-{index:06d}.bin").write_bytes(payload)
    large_path = root / "large" / "large-synthetic.bin"
    large_path.parent.mkdir(parents=True, exist_ok=True)
    chunk = _repeat_to_size(b"synthetic-large-file\n", min(1024 * 1024, large_file_size))
    remaining = large_file_size
    with large_path.open("wb") as stream:
        while remaining:
            written = min(remaining, len(chunk))
            stream.write(chunk[:written])
            remaining -= written
    return max(file_count - 1, 0) * small_file_size + large_file_size


def _measure(action: Callable[[], T]) -> tuple[T, float, int]:
    gc.collect()
    tracemalloc.start()
    started = time.perf_counter()
    try:
        result = action()
        elapsed = max(time.perf_counter() - started, 1e-9)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return result, elapsed, peak


def _nested_archive_payload(depth: int) -> tuple[bytes, str, int]:
    payload = b"synthetic nested archive leaf\n"
    entry_name = "leaf.txt"
    embedded_size = len(payload)
    for level in range(depth):
        buffer = io.BytesIO()
        embedded_size = len(payload)
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(entry_name, payload)
        payload = buffer.getvalue()
        entry_name = f"level-{level:02d}.zip"
    return payload, entry_name, embedded_size


def _nested_archive(
    path: Path,
    depth: int,
    *,
    max_entries: int,
    max_uncompressed_bytes: int,
) -> dict[str, Any]:
    payload, _, _ = _nested_archive_payload(depth)
    path.write_bytes(payload)
    receipt = inspect_zip(
        path,
        max_entries=max_entries,
        max_uncompressed_bytes=max_uncompressed_bytes,
    )
    return {
        "outcome": receipt["outcome"],
        "accepted_entry_count": len(receipt["entries"]),
        "recursion": "not-attempted",
        "inspection_completeness": receipt["inspection_completeness"],
    }


def _synthetic_concurrent_change(temporary_root: Path) -> dict[str, str]:
    """Replay a deterministic observer event; do not claim host race coverage."""
    vector_path = temporary_root / "concurrent-change-vector.json"
    vector_path.write_text(
        json.dumps(
            {
                "synthetic": True,
                "started_at": "2026-01-01T00:00:00Z",
                "ended_at": "2026-01-01T00:00:01Z",
                "cases": [
                    {
                        "id": "complete-control",
                        "observation": "file",
                        "relative_path": "stable.bin",
                        "byte_size": 0,
                        "content_digest": "sha-256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                        "expected_outcome": "complete",
                    },
                    {
                        "id": "concurrent-change",
                        "observation": "file-failure",
                        "relative_path": "changing.bin",
                        "failure_code": "unstable",
                        "expected_outcome": "partial",
                    },
                    {
                        "id": "unavailable-control",
                        "observation": "root-failure",
                        "failure_code": "unreadable",
                        "expected_outcome": "failed",
                    },
                    {
                        "id": "cancelled-control",
                        "observation": "cancelled",
                        "expected_outcome": "cancelled",
                    },
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    receipt = run_scan_conformance(vector_path)
    observed = next(
        (
            case
            for case in receipt["cases"]
            if case["id"] == "concurrent-change"
        ),
        None,
    )
    if observed is None:
        raise ValidationFailure(
            "benchmark-conformance-case-missing",
            "scan conformance did not return the concurrent-change case",
        )
    return {
        "evidence_kind": "synthetic-observer-event",
        "outcome": observed["outcome"],
        "diagnostic": observed["failure_codes"][0],
    }


def _profile_digest(profile: dict[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(profile))


def _runtime_family() -> str:
    observed = platform.system()
    runtime_family = SUPPORTED_RUNTIME_FAMILIES.get(observed)
    if runtime_family is None:
        raise ValidationFailure(
            "benchmark-unsupported-platform",
            f"benchmark runtime platform is unsupported: {observed or '<empty>'}",
        )
    return runtime_family


def _bounded_outcome(
    receipt: dict[str, Any],
    *,
    name: str,
    expected_outcome: str,
    expected_diagnostic: str,
) -> dict[str, str]:
    diagnostics = receipt.get("diagnostics")
    if (
        receipt.get("outcome") != expected_outcome
        or not isinstance(diagnostics, list)
        or not diagnostics
        or not isinstance(diagnostics[0], dict)
        or diagnostics[0].get("code") != expected_diagnostic
    ):
        raise ValidationFailure(
            "benchmark-run-failed",
            f"{name} did not produce the required bounded outcome",
        )
    return {
        "outcome": expected_outcome,
        "diagnostic": expected_diagnostic,
    }


def _benchmark_claims(receipt_body: dict[str, Any]) -> list[dict[str, Any]]:
    corpus = receipt_body["corpus"]
    profile_digest = receipt_body["profile_digest"]
    authenticity = "integrity-verified / issuer-unverified"
    return [
        {
            "claim_id": "synthetic-corpus-coverage",
            "summary": (
                f"the synthetic corpus contains {corpus['file_count']} files, "
                f"one designated {corpus['large_file_size_bytes']}-byte file, "
                f"{corpus['directory_depth']} directory levels, and repeated content"
            ),
            "evidence_refs": [
                "$.corpus.file_count",
                "$.corpus.large_file_size_bytes",
                "$.corpus.directory_depth",
                "$.corpus.repeated_content",
            ],
            "provenance_ref": profile_digest,
            "authenticity": authenticity,
        },
        {
            "claim_id": "measured-resource-use",
            "summary": "scan, projection, and SQLite measurements include traced Python allocation peaks",
            "evidence_refs": [
                "$.measurements.scan_peak_traced_memory_bytes",
                "$.measurements.projection_peak_traced_memory_bytes",
                "$.measurements.sqlite_rebuild_peak_traced_memory_bytes",
            ],
            "provenance_ref": profile_digest,
            "authenticity": authenticity,
        },
        {
            "claim_id": "distinct-bounded-outcomes",
            "summary": "resource limits, cancellation, unavailable roots, unstable observations, and nested archives retain distinct outcomes",
            "evidence_refs": [
                "$.bounded_outcomes.byte_limit",
                "$.bounded_outcomes.entry_limit",
                "$.bounded_outcomes.cancellation",
                "$.bounded_outcomes.unavailable_root",
                "$.bounded_outcomes.concurrent_change",
                "$.bounded_outcomes.nested_archive",
            ],
            "provenance_ref": profile_digest,
            "authenticity": authenticity,
        },
        {
            "claim_id": "complete-byte-hashing",
            "summary": "every admitted regular-file byte is hashed without a large-file exemption",
            "evidence_refs": [
                "$.measurements.hashing_bytes",
                "$.corpus.total_file_bytes",
                "$.resource_policy.large_file_hash_exemption_bytes",
            ],
            "provenance_ref": profile_digest,
            "authenticity": authenticity,
        },
    ]


def run_baseline_v2(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the bounded v2 profile without exposing temporary machine paths."""
    profile = validate_profile(DEFAULT_PROFILE if profile is None else profile)
    runtime_family = _runtime_family()
    file_count = profile["file_count"]
    small_size = profile["small_file_size_bytes"]
    large_size = profile["large_file_size_bytes"]
    record_count = profile["projection_record_count"]
    with tempfile.TemporaryDirectory(prefix="artifact-memory-benchmark-") as temporary:
        temporary_root = Path(temporary)
        root = temporary_root / "tree"
        root.mkdir()
        expected_bytes = _make_corpus(
            root,
            file_count=file_count,
            small_file_size=small_size,
            large_file_size=large_size,
            depth=profile["depth"],
        )

        (manifest, scan_receipt), scan_seconds, scan_peak = _measure(lambda: scan_path(root))
        scanned_bytes = sum(
            entry.get("byte_size", 0) for entry in manifest["entries"] if entry["kind"] == "file"
        )
        if scan_receipt["outcome"] != "complete" or scanned_bytes != expected_bytes:
            raise ValidationFailure("benchmark-run-failed", "unbounded synthetic scan was incomplete")
        file_paths = [
            entry["path"]
            for entry in manifest["entries"]
            if entry["kind"] == "file"
        ]
        deepest_path_components = max(
            len(relative_path.split("/")) for relative_path in file_paths
        )
        directory_depth = deepest_path_components - 1

        _, byte_limited = scan_path(root, ScanLimits(max_bytes=profile["scan_byte_limit"]))
        _, entry_limited = scan_path(root, ScanLimits(max_entries=profile["scan_entry_limit"]))
        _, cancelled = scan_path(root, ScanLimits(cancellation_check=lambda: True))
        _, missing = scan_path(temporary_root / "missing-root")
        missing_diagnostics = missing.get("diagnostics")
        if (
            not isinstance(missing_diagnostics, list)
            or not missing_diagnostics
            or not isinstance(missing_diagnostics[0], dict)
            or missing_diagnostics[0].get("code")
            not in {"unreadable", "resolver-unavailable"}
        ):
            raise ValidationFailure(
                "benchmark-run-failed",
                "unavailable root did not produce the required bounded outcome",
            )
        missing_diagnostic = missing_diagnostics[0]["code"]
        concurrent = _synthetic_concurrent_change(temporary_root)

        records_dir = temporary_root / "records"
        records_dir.mkdir()
        record_paths: list[Path] = []
        for index in range(record_count):
            path = records_dir / f"record-{index:06d}.json"
            path.write_text(json.dumps(_record(index), sort_keys=True) + "\n", encoding="utf-8")
            record_paths.append(path)
        projection_dir = temporary_root / "projection"
        projection_receipt, projection_seconds, projection_peak = _measure(
            lambda: project_records(record_paths, projection_dir)
        )

        records = canonical_records(record_paths)
        source_digest = sha256_bytes(_record_lines(records))
        rebuilt_index = temporary_root / "rebuilt.sqlite"
        _, sqlite_seconds, sqlite_peak = _measure(
            lambda: _create_sqlite(rebuilt_index, records, source_digest)
        )
        sqlite_size = rebuilt_index.stat().st_size

        nested = _nested_archive(
            temporary_root / "nested.zip",
            profile["nested_archive_depth"],
            max_entries=profile["archive_max_entries"],
            max_uncompressed_bytes=profile["archive_max_uncompressed_bytes"],
        )

    body = {
        "outcome": "complete",
        "runtime_family": runtime_family,
        "profile_id": profile["profile_id"],
        "profile_digest": _profile_digest(profile),
        "corpus": {
            "file_count": file_count,
            "small_file_size_bytes": small_size,
            "large_file_size_bytes": large_size,
            "total_file_bytes": expected_bytes,
            "directory_depth": directory_depth,
            "deepest_path_components": deepest_path_components,
            "repeated_content": True,
            "projection_record_count": record_count,
            "tree_digest": manifest["tree_digest"],
            "source_record_set_digest": projection_receipt["source_record_set_digest"],
        },
        "measurements": {
            "scan_wall_microseconds": max(round(scan_seconds * 1_000_000), 1),
            "scan_peak_traced_memory_bytes": scan_peak,
            "hashing_bytes": scanned_bytes,
            "hashing_bytes_per_second": max(round(scanned_bytes / scan_seconds), 1),
            "projection_wall_microseconds": max(round(projection_seconds * 1_000_000), 1),
            "projection_peak_traced_memory_bytes": projection_peak,
            "sqlite_rebuild_wall_microseconds": max(round(sqlite_seconds * 1_000_000), 1),
            "sqlite_rebuild_peak_traced_memory_bytes": sqlite_peak,
            "sqlite_index_bytes": sqlite_size,
            "scanned_entry_count": scan_receipt["accounted_entry_count"],
            "projected_record_count": projection_receipt["record_count"],
        },
        "bounded_outcomes": {
            "byte_limit": _bounded_outcome(
                byte_limited,
                name="byte limit",
                expected_outcome="partial",
                expected_diagnostic="resource-limit",
            ),
            "entry_limit": _bounded_outcome(
                entry_limited,
                name="entry limit",
                expected_outcome="partial",
                expected_diagnostic="resource-limit",
            ),
            "cancellation": _bounded_outcome(
                cancelled,
                name="cancellation",
                expected_outcome="cancelled",
                expected_diagnostic="cancelled",
            ),
            "unavailable_root": _bounded_outcome(
                missing,
                name="unavailable root",
                expected_outcome="failed",
                expected_diagnostic=missing_diagnostic,
            ),
            "concurrent_change": concurrent,
            "nested_archive": nested,
        },
        "resource_policy": {
            "harness_max_bytes": MAX_BENCHMARK_BYTES,
            "harness_max_files": MAX_BENCHMARK_FILES,
            "harness_max_depth": MAX_BENCHMARK_DEPTH,
            "harness_max_records": MAX_BENCHMARK_RECORDS,
            "scan_byte_limit": profile["scan_byte_limit"],
            "scan_entry_limit": profile["scan_entry_limit"],
            "archive_max_entries": profile["archive_max_entries"],
            "archive_max_uncompressed_bytes": profile[
                "archive_max_uncompressed_bytes"
            ],
            "large_file_hash_exemption_bytes": 0,
        },
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": [
            "timings and traced Python allocations are descriptive for this runner and corpus",
            "traced Python allocation peaks exclude operating-system cache and native-library allocation",
            "synthetic unstable observation proves receipt behavior, not host filesystem race coverage",
            "nested archive bytes remain opaque because v0 inspection does not recurse",
            "no universal throughput, memory, scale, or capacity guarantee is made",
        ],
    }
    body["claims"] = _benchmark_claims(body)
    receipt = receipt_with_digest(
        "artifact-memory/benchmark-receipt/v2", "benchmark-receipt://", body
    )
    validate_benchmark_receipt(receipt, expected_profile=profile)
    return receipt


def _make_legacy_corpus(
    root: Path, file_count: int, file_size: int, depth: int
) -> None:
    payloads = [
        b"synthetic-repeat\n" * (file_size // 16),
        hashlib.sha256(b"synthetic-unique").digest() * (file_size // 32),
    ]
    for index in range(file_count):
        directory = root
        for level in range(depth if index == 0 else index % max(depth, 1)):
            directory /= f"level-{level:02d}"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"item-{index:04d}.bin").write_bytes(
            payloads[index % 2][:file_size]
        )


def run_baseline(
    file_count: int = 64, file_size: int = 4096, depth: int = 8
) -> dict[str, Any]:
    """Run the retained v1 callable and receipt contract.

    New bounded-profile callers should use :func:`run_baseline_v2`.
    """
    legacy_profile = {
        "file_count": file_count,
        "file_size": file_size,
        "depth": depth,
    }
    for name, maximum in (
        ("file_count", MAX_BENCHMARK_FILES),
        ("file_size", MAX_BENCHMARK_BYTES),
        ("depth", MAX_BENCHMARK_DEPTH),
    ):
        value = legacy_profile[name]
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
            or value > maximum
        ):
            raise ValidationFailure(
                "benchmark-profile-invalid",
                f"{name} must be a positive integer no greater than {maximum}",
                f"$.{name}",
            )
    if file_count * file_size > MAX_BENCHMARK_BYTES:
        raise ValidationFailure(
            "benchmark-profile-invalid",
            "legacy benchmark corpus exceeds the harness byte ceiling",
            "$.file_size",
        )
    runtime_family = _runtime_family()
    with tempfile.TemporaryDirectory(prefix="artifact-memory-benchmark-") as temporary:
        root = Path(temporary) / "tree"
        root.mkdir()
        _make_legacy_corpus(root, file_count, file_size, depth)

        (manifest, scan_receipt), scan_seconds, _ = _measure(lambda: scan_path(root))
        _, limited_receipt = scan_path(
            root, ScanLimits(max_bytes=max(file_size * 4, 1))
        )
        _, cancelled_receipt = scan_path(
            root, ScanLimits(cancellation_check=lambda: True)
        )

        records_dir = Path(temporary) / "records"
        records_dir.mkdir()
        record_paths = []
        for index in range(file_count):
            path = records_dir / f"record-{index:04d}.json"
            path.write_text(
                json.dumps(_record(index), sort_keys=True) + "\n", encoding="utf-8"
            )
            record_paths.append(path)
        projection_dir = Path(temporary) / "projection"
        projection_receipt, projection_seconds, _ = _measure(
            lambda: project_records(record_paths, projection_dir)
        )

    receipt = {
        "schema_id": "artifact-memory/benchmark-receipt/v1",
        "outcome": "complete",
        "runtime_family": runtime_family,
        "corpus": {
            "file_count": file_count,
            "file_size_bytes": file_size,
            "depth": depth,
            "repeated_content": True,
        },
        "measurements": {
            "scan_wall_seconds": round(scan_seconds, 6),
            "projection_wall_seconds": round(projection_seconds, 6),
            "scanned_entry_count": scan_receipt["accounted_entry_count"],
            "projected_record_count": projection_receipt["record_count"],
        },
        "bounded_outcomes": {
            "resource_limit": limited_receipt["outcome"],
            "resource_limit_diagnostic": limited_receipt["diagnostics"][0]["code"],
            "cancelled": cancelled_receipt["outcome"],
            "cancelled_diagnostic": cancelled_receipt["diagnostics"][0]["code"],
            "unbounded_scan": manifest["completeness"],
        },
        "resource_limits": {
            "benchmark_max_bytes": file_size * 4,
            "archive_max_uncompressed_bytes": 16 * 1024 * 1024,
        },
        "limitations": [
            "timings are descriptive for this runner and corpus",
            "no universal throughput or memory guarantee",
            "malicious archive nesting is covered by archive conformance tests",
        ],
    }
    validate_benchmark_receipt(receipt)
    return receipt


def invariant_projection(receipt: dict[str, Any]) -> dict[str, Any]:
    """Remove machine-specific measurements for cross-run conformance."""
    return {
        key: value
        for key, value in receipt.items()
        if key not in {"receipt_id", "runtime_family", "measurements"}
    }


def validate_benchmark_receipt(
    receipt: dict[str, Any],
    *,
    expected_profile: dict[str, Any] | None = None,
    expected_profile_digest: str | None = None,
) -> None:
    """Validate a v1 or v2 receipt and optionally bind v2 to a selected profile.

    Without an expected profile or digest, v2 validation proves structural and
    internal integrity only; it does not establish who selected the profile.
    """
    schema_id = receipt.get("schema_id") if isinstance(receipt, dict) else None
    if schema_id == "artifact-memory/benchmark-receipt/v1":
        if expected_profile is not None or expected_profile_digest is not None:
            raise ValidationFailure(
                "benchmark-profile-binding-unsupported",
                "v1 benchmark receipts do not carry profile identity",
                "$.schema_id",
            )
        validate(receipt, load_schema("core", "benchmark-receipt.v1.schema.json"))
        return
    if schema_id != "artifact-memory/benchmark-receipt/v2":
        raise ValidationFailure(
            "benchmark-receipt-schema-unsupported",
            "benchmark receipt schema is not supported",
            "$.schema_id",
        )
    if expected_profile is not None and expected_profile_digest is not None:
        raise ValueError("provide expected_profile or expected_profile_digest, not both")
    validate(receipt, load_schema("core", "benchmark-receipt.v2.schema.json"))
    body = {
        key: value
        for key, value in receipt.items()
        if key not in {"schema_id", "receipt_id"}
    }
    if receipt["receipt_id"] != expected_receipt_id(
        receipt, "benchmark-receipt://"
    ):
        raise ValidationFailure(
            "benchmark-receipt-id-mismatch",
            "benchmark receipt identity does not match its canonical body",
            "$.receipt_id",
        )
    if receipt["claims"] != _benchmark_claims(body):
        raise ValidationFailure(
            "benchmark-claim-binding-invalid",
            "benchmark claims do not match their profile and evidence references",
            "$.claims",
        )
    if expected_profile is not None:
        expected_profile_digest = _profile_digest(validate_profile(expected_profile))
    if (
        expected_profile_digest is not None
        and receipt["profile_digest"] != expected_profile_digest
    ):
        raise ValidationFailure(
            "benchmark-profile-mismatch",
            "benchmark receipt does not bind the expected profile",
            "$.profile_digest",
        )


def render_baseline(receipt: dict[str, Any]) -> str:
    measurements = receipt["measurements"]
    corpus = receipt["corpus"]
    return (
        "# Synthetic performance and resource-safety baseline\n\n"
        f"- Outcome: `{receipt['outcome']}`\n"
        f"- Runtime family: `{receipt['runtime_family']}`\n"
        f"- Profile: `{receipt['profile_id']}`\n"
        f"- Files: {corpus['file_count']} ({corpus['total_file_bytes']} bytes)\n"
        f"- Deepest synthetic path: {corpus['deepest_path_components']} components "
        f"({corpus['directory_depth']} directory levels)\n"
        f"- Projection records: {corpus['projection_record_count']}\n"
        f"- Scan: {measurements['scan_wall_microseconds']}µs, "
        f"{measurements['hashing_bytes_per_second']} bytes/s, "
        f"{measurements['scan_peak_traced_memory_bytes']} traced bytes peak\n"
        f"- SQLite rebuild: {measurements['sqlite_rebuild_wall_microseconds']}µs, "
        f"{measurements['sqlite_rebuild_peak_traced_memory_bytes']} traced bytes peak\n\n"
        "The checked profile also proves distinct partial, cancelled, failed, unstable-observation, and non-recursive nested-archive outcomes. Measurements are descriptive for this synthetic corpus and runner; they are not universal performance or capacity guarantees.\n"
    )
