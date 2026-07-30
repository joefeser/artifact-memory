"""Small synthetic baseline for scan and projection resource behavior."""

from __future__ import annotations

import hashlib
import json
import platform
import tempfile
import time
from pathlib import Path
from typing import Any

from .projection import project_records
from .scan import ScanLimits, scan_path


def _record(index: int) -> dict[str, Any]:
    return {
        "schema_id": "artifact-memory/knowledge-record/v1",
        "record_id": f"record://synthetic/benchmark-{index:04d}",
        "record_type": "note",
        "lifecycle": "accepted",
        "meaning": {"summary": "Synthetic benchmark record.", "labels": ["synthetic", "benchmark"]},
        "artifact_refs": [f"artifact://synthetic/benchmark-{index:04d}"],
        "provenance": [{"kind": "observation", "source_ref": "fixture://synthetic/benchmark/v0"}],
        "sensitivity": "public",
    }


def _make_corpus(root: Path, file_count: int, file_size: int, depth: int) -> None:
    payloads = [b"synthetic-repeat\n" * (file_size // 16), hashlib.sha256(b"synthetic-unique").digest() * (file_size // 32)]
    for index in range(file_count):
        directory = root
        for level in range(depth if index == 0 else index % max(depth, 1)):
            directory /= f"level-{level:02d}"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"item-{index:04d}.bin").write_bytes(payloads[index % 2][:file_size])


def run_baseline(file_count: int = 64, file_size: int = 4096, depth: int = 8) -> dict[str, Any]:
    """Run a bounded, synthetic baseline without exposing temporary paths."""
    with tempfile.TemporaryDirectory(prefix="artifact-memory-benchmark-") as temporary:
        root = Path(temporary) / "tree"
        root.mkdir()
        _make_corpus(root, file_count, file_size, depth)

        started = time.perf_counter()
        manifest, scan_receipt = scan_path(root)
        scan_seconds = time.perf_counter() - started

        limited_manifest, limited_receipt = scan_path(root, ScanLimits(max_bytes=file_size * 4))
        _, cancelled_receipt = scan_path(root, ScanLimits(cancellation_check=lambda: True))

        records_dir = Path(temporary) / "records"
        records_dir.mkdir()
        record_paths = []
        for index in range(file_count):
            path = records_dir / f"record-{index:04d}.json"
            path.write_text(json.dumps(_record(index), sort_keys=True) + "\n", encoding="utf-8")
            record_paths.append(path)
        projection_dir = Path(temporary) / "projection"
        started = time.perf_counter()
        projection_receipt = project_records(record_paths, projection_dir)
        projection_seconds = time.perf_counter() - started

    return {
        "schema_id": "artifact-memory/benchmark-receipt/v1",
        "outcome": "complete",
        "runtime_family": platform.system().lower(),
        "corpus": {"file_count": file_count, "file_size_bytes": file_size, "depth": depth, "repeated_content": True},
        "measurements": {"scan_wall_seconds": round(scan_seconds, 6), "projection_wall_seconds": round(projection_seconds, 6), "scanned_entry_count": scan_receipt["accounted_entry_count"], "projected_record_count": projection_receipt["record_count"]},
        "bounded_outcomes": {"resource_limit": limited_receipt["outcome"], "resource_limit_diagnostic": limited_receipt["diagnostics"][0]["code"], "cancelled": cancelled_receipt["outcome"], "cancelled_diagnostic": cancelled_receipt["diagnostics"][0]["code"], "unbounded_scan": manifest["completeness"]},
        "resource_limits": {"benchmark_max_bytes": file_size * 4, "archive_max_uncompressed_bytes": 16 * 1024 * 1024},
        "limitations": ["timings are descriptive for this runner and corpus", "no universal throughput or memory guarantee", "malicious archive nesting is covered by archive conformance tests"],
    }
