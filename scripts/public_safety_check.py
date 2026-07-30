#!/usr/bin/env python3
"""Fail-closed public-safety checks for tracked paths and Git history."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


FORBIDDEN_PATH = re.compile(
    r"(^|/)(?:vault|private|records/private|artifacts|objects|quarantine)(?:/|$)"
    r"|(?:^|/)(?:\.env(?:\..*)?|resolver\.local\..*|endpoints\.local\..*)$"
    r"|\.(?:sqlite|sqlite3|db|db3|log|key|pem|p12|pfx)$",
    re.IGNORECASE,
)

# These are deliberately high-confidence patterns. The scanner is a guardrail,
# not a claim that a clean result proves the repository contains no secret.
SECRET_LIKE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|(ghp_|github_pat_|sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16})"
    r"|Authorization\s*:\s*Bearer\s+\S+"
    r"|(password|passwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*['\"]?\S+",
    re.IGNORECASE,
)

SCANNER_PATH = "scripts/public_safety_check.py"


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT)


def history_entries() -> dict[str, set[str]]:
    entries: dict[str, set[str]] = {}
    for line in run("git", "rev-list", "--objects", "--all").splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2:
            entries.setdefault(parts[0], set()).add(parts[1])
    return entries


def commits() -> list[str]:
    return run("git", "rev-list", "--all").splitlines()


def current_paths() -> list[str]:
    return run("git", "ls-files", "--cached", "--others", "--exclude-standard").splitlines()


def check_paths(history: dict[str, set[str]], current: list[str]) -> list[str]:
    findings = []
    for path in [path for paths in history.values() for path in paths] + current:
        if FORBIDDEN_PATH.search(path):
            findings.append(f"forbidden repository path: {path}")
    return sorted(set(findings))


def read_blobs(object_ids: list[str]) -> dict[str, bytes]:
    if not object_ids:
        return {}
    process = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    output, error = process.communicate(("\n".join(object_ids) + "\n").encode("ascii"))
    if process.returncode:
        raise RuntimeError(error.decode("utf-8", errors="replace").strip())

    blobs = {}
    offset = 0
    for object_id in object_ids:
        header_end = output.find(b"\n", offset)
        if header_end < 0:
            raise RuntimeError("git cat-file returned an incomplete header")
        header = output[offset:header_end].decode("ascii", errors="replace").split()
        offset = header_end + 1
        if len(header) != 3:
            raise RuntimeError("git cat-file returned an invalid header")
        _, object_type, size_text = header
        size = int(size_text)
        content = output[offset : offset + size]
        offset += size + 1
        if object_type == "blob":
            blobs[object_id] = content
    return blobs


def check_historical_content(history: dict[str, set[str]]) -> list[str]:
    """Scan each reachable blob once and never print matching content."""

    blobs = read_blobs(list(history))
    findings = []
    for object_id, paths in history.items():
        if object_id not in blobs or all(path == SCANNER_PATH for path in paths):
            continue
        text = blobs[object_id].decode("utf-8", errors="replace")
        if SECRET_LIKE.search(text):
            path = sorted(path for path in paths if path != SCANNER_PATH)[0]
            findings.append(f"secret-like historical content: object {object_id}, path {path}")
    return findings


def staged_objects() -> dict[str, str]:
    entries = {}
    output = subprocess.check_output(["git", "ls-files", "--stage", "-z"])
    for record in output.split(b"\0"):
        if not record:
            continue
        header, path = record.split(b"\t", 1)
        parts = header.split()
        if len(parts) == 3:
            entries[path.decode("utf-8", errors="surrogateescape")] = parts[1].decode("ascii")
    return entries


def check_current_content(paths: list[str]) -> list[str]:
    """Scan staged and non-ignored worktree files without echoing content."""

    staged = staged_objects()
    staged_content = read_blobs(list(staged.values()))
    findings = []
    for path in paths:
        if path == SCANNER_PATH:
            continue
        try:
            content = staged_content[staged[path]] if path in staged else Path(path).read_bytes()
        except (OSError, subprocess.CalledProcessError) as error:
            findings.append(f"current content scan failed: {path} ({error})")
            continue
        if b"\x00" in content[:8192]:
            continue
        text = content.decode("utf-8", errors="replace")
        if SECRET_LIKE.search(text):
            findings.append(f"secret-like current content: path {path}")
    return findings


def main() -> int:
    history = history_entries()
    current = current_paths()
    findings = (
        check_paths(history, current)
        + check_historical_content(history)
        + check_current_content(current)
    )
    if findings:
        print("PUBLIC SAFETY CHECK FAILED", file=sys.stderr)
        for finding in sorted(set(findings)):
            print(f"- {finding}", file=sys.stderr)
        return 1
    print(
        "public safety check passed: "
        f"{len(commits())} commits, {len(history)} historical objects, "
        f"{len(current)} current paths"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
