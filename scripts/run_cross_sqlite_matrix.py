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
            completed = subprocess.run(
                [path, str(PROBE)], capture_output=True, text=True, check=True, timeout=180
            )
            report = json.loads(completed.stdout)
        except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
            entries.append(
                {
                    "runtime": f"{name} ({path})",
                    "error": f"probe failed: {type(exc).__name__}: {exc}",
                }
            )
            continue
        if report["sqlite_version"] in seen:
            continue
        seen.add(report["sqlite_version"])
        entries.append({"runtime": f"{name} ({path})", **report})
    return entries


def _docker_reference(image: str) -> tuple[str, str]:
    """Resolve the immutable digest reference for a mutable tag.

    The tag stays human-readable, but execution and the receipt bind to the
    digest so a later rerun cannot silently execute a different build.
    """
    completed = subprocess.run(
        ["docker", "image", "inspect", image, "--format", "{{index .RepoDigests 0}}"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    digest = completed.stdout.strip() if completed.returncode == 0 else ""
    if not digest or "@sha256:" not in digest:
        subprocess.run(["docker", "pull", image], capture_output=True, timeout=600)
        completed = subprocess.run(
            ["docker", "image", "inspect", image, "--format", "{{index .RepoDigests 0}}"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        digest = completed.stdout.strip() if completed.returncode == 0 else ""
    if "@sha256:" in digest:
        return digest, digest.split("@sha256:")[1]
    return image, ""


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
        reference, digest = _docker_reference(image)
        try:
            completed = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-v",
                    f"{ROOT}:/repo:ro",
                    reference,
                    "python3",
                    "/repo/scripts/cross_sqlite_probe.py",
                ],
                capture_output=True,
                text=True,
                timeout=600,
            )
            report = json.loads(completed.stdout)
        except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
            entries.append(
                {
                    "runtime": image,
                    "image_digest": digest,
                    "error": f"probe failed: {type(exc).__name__}: {exc}",
                }
            )
            continue
        if report["sqlite_version"] in seen:
            continue
        seen.add(report["sqlite_version"])
        entries.append({"runtime": image, "image_digest": digest, **report})
    return entries


TIER_A_SQL = """-- The sqlite3 CLI may enable defensive mode by default, which rejects the
-- direct shadow-table write this probe depends on. Defensive mode is a CLI
-- configuration, not an engine capability, so the probe disables it to
-- measure the engine's actual tamper-detection behavior uniformly.
.dbconfig defensive off
CREATE VIRTUAL TABLE records_fts USING fts5(record_id UNINDEXED, summary, labels);
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
        except (subprocess.SubprocessError, OSError) as exc:
            entries.append(
                {
                    "runtime": f"sqlite3-cli ({binary})",
                    "library_tier_expected": False,
                    "error": f"probe failed: {type(exc).__name__}: {exc}",
                }
            )
            continue
        if version in seen:
            continue
        seen.add(version)
        entries.append(
            {
                "runtime": f"sqlite3-cli ({binary})",
                "library_tier_expected": False,
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


def _assert_invariants(entries: list[dict]) -> tuple[list[str], dict]:
    failures = []
    gate_passing = []
    for entry in entries:
        if "error" in entry:
            failures.append(f"{entry['runtime']}: {entry['error']}")
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
        if entry.get("library_tier_expected", True) and tier_b.get("available") is False:
            failures.append(
                f"{entry['runtime']}: library tier unavailable ({tier_b.get('reason')})"
            )
            continue
        if tier_b.get("available"):
            capable = _version_tuple(entry["sqlite_version"]) >= FTS5_MINIMUM
            if capable and not tier_b.get("clean_read_succeeded"):
                failures.append(f"{entry['runtime']}: clean read failed on a capable runtime")
            if not capable and tier_b.get("clean_read_succeeded"):
                failures.append(f"{entry['runtime']}: runtime floor did not fail closed")
            if tier_b.get("tampered_outcome") not in ("projection-unavailable", None):
                failures.append(
                    f"{entry['runtime']}: tampered index yielded {tier_b.get('tampered_outcome')}"
                )
            if tier_b.get("clean_read_succeeded"):
                gate_passing.append(entry)
    versions = {entry["sqlite_version"] for entry in gate_passing}
    if len(versions) < 2:
        failures.append(
            f"insufficient gate-passing runtime coverage: determinism compared across "
            f"{sorted(versions)}; at least two distinct SQLite versions are required"
        )
    reference = None
    for entry in gate_passing:
        fingerprint = json.dumps(
            {
                "source_digest": entry["tier_b"]["source_record_set_digest"],
                "snapshot_digest": entry["tier_b"].get("logical_snapshot_digest"),
                "default": entry["tier_b"]["clean_default_order"],
                "literal": entry["tier_b"].get("clean_literal_order"),
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
    summary = {
        "gate_passing_versions": sorted(versions),
        "fail_closed_versions": sorted(
            {
                entry["sqlite_version"]
                for entry in entries
                if "error" not in entry
                and (entry.get("tier_b") or {}).get("available")
                and not (entry.get("tier_b") or {}).get("clean_read_succeeded")
            }
        ),
    }
    return failures, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-docker", action="store_true")
    args = parser.parse_args(argv)
    entries = _run_local() + _run_cli_binaries()
    if not args.no_docker:
        entries += _run_docker()
    failures, summary = _assert_invariants(entries)
    matrix = {
        "schema": "artifact-memory/cross-sqlite-matrix/v1",
        "invariants_hold": not failures,
        "runtime_count": len(entries),
        "runtimes": entries,
        "coverage": summary,
        "failures": failures,
    }
    json.dump(matrix, sys.stdout, indent=2, sort_keys=True)
    print()
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
