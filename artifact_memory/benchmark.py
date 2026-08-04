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
from .canonical import canonical_bytes, receipt_with_digest, sha256_bytes
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
    _positive_integer(profile, "projection_record_count", MAX_BENCHMARK_RECORDS)
    scan_byte_limit = _positive_integer(profile, "scan_byte_limit", MAX_BENCHMARK_BYTES)
    _positive_integer(profile, "scan_entry_limit", MAX_BENCHMARK_FILES)
    _positive_integer(profile, "archive_max_entries", MAX_BENCHMARK_FILES)
    _positive_integer(profile, "archive_max_uncompressed_bytes", MAX_BENCHMARK_BYTES)
    _positive_integer(profile, "nested_archive_depth", MAX_BENCHMARK_DEPTH)
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
    repeated = _repeat_to_size(b"synthetic-repeat\n", small_file_size)
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


def _nested_archive(
    path: Path,
    depth: int,
    *,
    max_entries: int,
    max_uncompressed_bytes: int,
) -> dict[str, Any]:
    payload = b"synthetic nested archive leaf\n"
    entry_name = "leaf.txt"
    for level in range(depth):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(entry_name, payload)
        payload = buffer.getvalue()
        entry_name = f"level-{level:02d}.zip"
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
        case for case in receipt["cases"] if case["id"] == "concurrent-change"
    )
    return {
        "evidence_kind": "synthetic-observer-event",
        "outcome": observed["outcome"],
        "diagnostic": observed["failure_codes"][0],
    }


def _profile_digest(profile: dict[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(profile))


def run_baseline(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the bounded profile without exposing temporary machine paths."""
    profile = validate_profile(DEFAULT_PROFILE if profile is None else profile)
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

        _, byte_limited = scan_path(root, ScanLimits(max_bytes=profile["scan_byte_limit"]))
        _, entry_limited = scan_path(root, ScanLimits(max_entries=profile["scan_entry_limit"]))
        _, cancelled = scan_path(root, ScanLimits(cancellation_check=lambda: True))
        _, missing = scan_path(temporary_root / "missing-root")
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
        "runtime_family": platform.system().lower(),
        "profile_id": profile["profile_id"],
        "profile_digest": _profile_digest(profile),
        "corpus": {
            "file_count": file_count,
            "small_file_size_bytes": small_size,
            "large_file_size_bytes": large_size,
            "total_file_bytes": expected_bytes,
            "depth": profile["depth"],
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
            "byte_limit": {
                "outcome": byte_limited["outcome"],
                "diagnostic": byte_limited["diagnostics"][0]["code"],
            },
            "entry_limit": {
                "outcome": entry_limited["outcome"],
                "diagnostic": entry_limited["diagnostics"][0]["code"],
            },
            "cancellation": {
                "outcome": cancelled["outcome"],
                "diagnostic": cancelled["diagnostics"][0]["code"],
            },
            "unavailable_root": {
                "outcome": missing["outcome"],
                "diagnostic": missing["diagnostics"][0]["code"],
            },
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
        "claims": [
            "the synthetic corpus covers large counts, one multi-chunk file, deep paths, and repeated content",
            "scan and SQLite projection rebuild measurements include traced Python allocation peaks",
            "byte limits, entry limits, cancellation, unavailable roots, unstable observations, and nested archives retain distinct bounded outcomes",
            "every admitted regular-file byte is hashed without a large-file exemption",
        ],
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": [
            "timings and traced Python allocations are descriptive for this runner and corpus",
            "traced Python allocation peaks exclude operating-system cache and native-library allocation",
            "synthetic unstable observation proves receipt behavior, not host filesystem race coverage",
            "nested archive bytes remain opaque because v0 inspection does not recurse",
            "no universal throughput, memory, scale, or capacity guarantee is made",
        ],
    }
    receipt = receipt_with_digest(
        "artifact-memory/benchmark-receipt/v2", "benchmark-receipt://", body
    )
    validate_benchmark_receipt(receipt)
    return receipt


def invariant_projection(receipt: dict[str, Any]) -> dict[str, Any]:
    """Remove machine-specific measurements for cross-run conformance."""
    return {
        key: value
        for key, value in receipt.items()
        if key not in {"receipt_id", "runtime_family", "measurements"}
    }


def validate_benchmark_receipt(receipt: dict[str, Any]) -> None:
    """Validate the schema and digest-bound receipt identity."""
    validate(receipt, load_schema("core", "benchmark-receipt.v2.schema.json"))
    body = {
        key: value
        for key, value in receipt.items()
        if key not in {"schema_id", "receipt_id"}
    }
    expected = receipt_with_digest(
        receipt["schema_id"], "benchmark-receipt://", body
    )
    if receipt["receipt_id"] != expected["receipt_id"]:
        raise ValidationFailure(
            "benchmark-receipt-id-mismatch",
            "benchmark receipt identity does not match its canonical body",
            "$.receipt_id",
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
        f"- Deepest synthetic path: {corpus['depth']} components\n"
        f"- Projection records: {corpus['projection_record_count']}\n"
        f"- Scan: {measurements['scan_wall_microseconds']}µs, "
        f"{measurements['hashing_bytes_per_second']} bytes/s, "
        f"{measurements['scan_peak_traced_memory_bytes']} traced bytes peak\n"
        f"- SQLite rebuild: {measurements['sqlite_rebuild_wall_microseconds']}µs, "
        f"{measurements['sqlite_rebuild_peak_traced_memory_bytes']} traced bytes peak\n\n"
        "The checked profile also proves distinct partial, cancelled, failed, unstable-observation, and non-recursive nested-archive outcomes. Measurements are descriptive for this synthetic corpus and runner; they are not universal performance or capacity guarantees.\n"
    )
