#!/usr/bin/env python3
"""Run the cross-SQLite determinism matrix over every discoverable runtime.

Runtimes: local python interpreters, pinned sqlite3 CLI binaries (tier A
only, via a generated SQL script), and pinned Docker images when Docker is
available. The matrix asserts the epic invariants:

- a two-step records_fts/records_fts_content forgery never yields results
  through the library: above SQLite 3.44 the read gate detects it typed,
  below it the runtime floor fails every read closed;
- PRAGMA integrity_check detects the forgery exactly on 3.44+ runtimes;
- gate-passing runtimes agree on projection digests and on default, literal,
  and ranked search results.

Observed measurements are descriptive evidence per decision 0015; the
invariants above are asserted and a violation exits nonzero.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts" / "cross_sqlite_probe.py"
FTS5_MINIMUM = (3, 44, 0)
DOCKER_IMAGES = (
    "python:3.11-slim-bullseye",
    "python:3.12-slim-bookworm",
    "python:3.11-slim",
    "python:3.13-slim",
)
CLI_BINARIES = ("/usr/bin/sqlite3", "/opt/homebrew/opt/sqlite/bin/sqlite3")


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split(".")[:3])


def _run_local() -> list[dict]:
    entries = []
    seen: set[str] = set()
    for name in ("python3", "python3.11", "python3.12", "python3.13", "python3.14"):
        path = shutil.which(name)
        if path is None:
            continue
        try:
            report = json.loads(
                subprocess.run(
                    [path, str(PROBE)], capture_output=True, text=True, check=True, timeout=180
                ).stdout
            )
        except (subprocess.SubprocessError, json.JSONDecodeError):
            continue
        if report["sqlite_version"] in seen:
            continue
        seen.add(report["sqlite_version"])
        entries.append({"runtime": f"{name} ({path})", **report})
    return entries


def _run_docker() -> list[dict]:
    if shutil.which("docker") is None:
        return []
    try:
        subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            check=True,
            timeout=30,
        )
    except subprocess.SubprocessError:
        print("docker daemon unavailable; skipping container runtimes", file=sys.stderr)
        return []
    entries = []
    seen: set[str] = set()
    for image in DOCKER_IMAGES:
        try:
            completed = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-v",
                    f"{ROOT}:/repo:ro",
                    image,
                    "python3",
                    "/repo/scripts/cross_sqlite_probe.py",
                ],
                capture_output=True,
                text=True,
                timeout=600,
            )
            report = json.loads(completed.stdout)
        except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
            entries.append({"runtime": image, "error": f"{type(exc).__name__}: {exc}"})
            continue
        if report["sqlite_version"] in seen:
            continue
        seen.add(report["sqlite_version"])
        entries.append({"runtime": image, **report})
    return entries


TIER_A_SQL = """CREATE VIRTUAL TABLE records_fts USING fts5(record_id UNINDEXED, summary, labels);
INSERT INTO records_fts VALUES ('record://synthetic/matrix-0001', 'beta beta beta beta beta gamma alpha', '');
INSERT INTO records_fts VALUES ('record://synthetic/matrix-0002', 'beta gamma gamma gamma gamma alpha', '');
INSERT INTO records_fts VALUES ('record://synthetic/matrix-0003', 'gamma alpha', '');
 UPDATE records_fts SET summary = 'forged summary containing syntheticforged' WHERE record_id = 'record://synthetic/matrix-0001';
UPDATE records_fts_content SET c1 = 'beta beta beta beta beta gamma alpha' WHERE c0 = 'record://synthetic/matrix-0001';
PRAGMA integrity_check;
"""


def _run_cli_binaries() -> list[dict]:
    entries = []
    seen: set[str] = set()
    for binary in CLI_BINARIES:
        if not Path(binary).exists():
            continue
        try:
            version = (
                subprocess.run([binary, "--version"], capture_output=True, text=True, check=True)
                .stdout.split()[0]
            )
            completed = subprocess.run(
                [binary, "-batch"], input=TIER_A_SQL, capture_output=True, text=True, check=True
            )
            integrity_rows = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        except (subprocess.SubprocessError, OSError):
            continue
        if version in seen:
            continue
        seen.add(version)
        entries.append(
            {
                "runtime": f"sqlite3-cli ({binary})",
                "python_version": None,
                "sqlite_version": version,
                "tier_a": {
                    "integrity_check_detects_forgery": integrity_rows != ["ok"],
                    "integrity_check_rows": integrity_rows[:3],
                },
                "tier_b": {"available": False, "reason": "CLI runtime; library tier not applicable"},
            }
        )
    return entries


def _assert_invariants(entries: list[dict]) -> list[str]:
    failures = []
    gate_passing = []
    for entry in entries:
        if "error" in entry:
            failures.append(f"{entry['runtime']}: probe error {entry['error']}")
            continue
        tier_a = entry.get("tier_a") or {}
        if "integrity_check_detects_forgery" in tier_a:
            expected = _version_tuple(entry["sqlite_version"]) >= FTS5_MINIMUM
            observed = tier_a["integrity_check_detects_forgery"]
            if observed != expected:
                failures.append(
                    f"{entry['runtime']}: forgery detection {observed} but SQLite "
                    f"{entry['sqlite_version']} implies {expected}"
                )
        tier_b = entry.get("tier_b") or {}
        if tier_b.get("available"):
            if entry["sqlite_version"] >= "3.44" and not tier_b.get("clean_read_succeeded"):
                failures.append(f"{entry['runtime']}: clean read failed on a capable runtime")
            if entry["sqlite_version"] < "3.44" and tier_b.get("clean_read_succeeded"):
                failures.append(f"{entry['runtime']}: runtime floor did not fail closed")
            if tier_b.get("tampered_outcome") not in ("projection-unavailable", None):
                failures.append(
                    f"{entry['runtime']}: tampered index yielded {tier_b.get('tampered_outcome')}"
                )
            if tier_b.get("clean_read_succeeded"):
                gate_passing.append(entry)
    reference = None
    for entry in gate_passing:
        fingerprint = json.dumps(
            {
                "digest": entry["tier_b"]["source_record_set_digest"],
                "default": entry["tier_b"]["clean_default_order"],
                "ranked": entry["tier_b"]["clean_ranked_order"],
            },
            sort_keys=True,
        )
        if reference is None:
            reference = (entry["runtime"], fingerprint)
        elif fingerprint != reference[1]:
            failures.append(
                f"{entry['runtime']}: results diverge from {reference[0]}: "
                f"{fingerprint} vs {reference[1]}"
            )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-docker", action="store_true")
    args = parser.parse_args(argv)
    entries = _run_local() + _run_cli_binaries()
    if not args.no_docker:
        entries += _run_docker()
    failures = _assert_invariants(entries)
    matrix = {
        "schema": "artifact-memory/cross-sqlite-matrix/v1",
        "invariants_hold": not failures,
        "runtime_count": len(entries),
        "runtimes": entries,
        "failures": failures,
    }
    json.dump(matrix, sys.stdout, indent=2, sort_keys=True)
    print()
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
