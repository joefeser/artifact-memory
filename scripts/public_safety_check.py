#!/usr/bin/env python3
"""Fail-closed public-safety checks for tracked paths and Git history."""

from __future__ import annotations

import re
import subprocess
import sys


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


def history_paths() -> list[str]:
    lines = run("git", "rev-list", "--objects", "--all").splitlines()
    return [line.split(" ", 1)[1] for line in lines if " " in line]


def commits() -> list[str]:
    return run("git", "rev-list", "--all").splitlines()


def current_paths() -> list[str]:
    return run("git", "ls-files", "--cached", "--others", "--exclude-standard").splitlines()


def check_paths() -> list[str]:
    findings = []
    for path in history_paths() + current_paths():
        if FORBIDDEN_PATH.search(path):
            findings.append(f"forbidden repository path: {path}")
    return findings


def check_content() -> list[str]:
    findings = []
    for commit in commits():
        try:
            output = subprocess.check_output(
                [
                    "git",
                    "grep",
                    "-I",
                    "-n",
                    "-E",
                    "-e",
                    SECRET_LIKE.pattern,
                    commit,
                    "--",
                    ":(exclude)" + SCANNER_PATH,
                ],
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError as error:
            if error.returncode == 1:
                continue
            findings.append(f"history scan failed at {commit}: exit {error.returncode}")
            continue
        for line in output.splitlines():
            findings.append(f"secret-like historical content: {line}")
    return findings


def main() -> int:
    findings = check_paths() + check_content()
    if findings:
        print("PUBLIC SAFETY CHECK FAILED", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print(
        "public safety check passed: "
        f"{len(commits())} commits, {len(history_paths())} historical paths, "
        f"{len(current_paths())} current paths"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
