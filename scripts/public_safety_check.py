#!/usr/bin/env python3
"""Fail-closed public-safety checks for tracked paths and Git history."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.canonical import receipt_with_digest
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import ValidationFailure, validate


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
RECEIPT_SCHEMA_ID = "artifact-memory/public-safety-receipt/v1"
RECEIPT_ID_PREFIX = "public-safety-receipt://"


def _revision_arguments(revisions: list[str] | None) -> list[str]:
    return ["--all"] if revisions is None else revisions


def history_entries(revisions: list[str] | None = None) -> dict[str, set[str]]:
    entries: dict[str, set[str]] = {}
    output = subprocess.check_output(
        ["git", "rev-list", "--objects", *_revision_arguments(revisions)],
        text=True,
        stderr=subprocess.STDOUT,
    )
    for line in output.splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2:
            entries.setdefault(parts[0], set()).add(parts[1])
    return entries


def commits(revisions: list[str] | None = None) -> list[str]:
    return subprocess.check_output(
        ["git", "rev-list", *_revision_arguments(revisions)],
        text=True,
        stderr=subprocess.STDOUT,
    ).splitlines()


def head_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.STDOUT
    ).strip()


def public_refs() -> list[dict[str, str]]:
    output = subprocess.check_output(
        [
            "git",
            "for-each-ref",
            "--format=%(refname)%09%(objectname)",
            "refs/remotes",
            "refs/tags",
        ],
        text=True,
        stderr=subprocess.STDOUT,
    )
    refs = []
    for line in output.splitlines():
        ref, object_id = line.split("\t", 1)
        if ref.endswith("/HEAD"):
            continue
        refs.append({"ref": ref, "object_id": object_id})
    return sorted(refs, key=lambda item: item["ref"])


def worktree_is_clean() -> bool:
    return not subprocess.check_output(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        stderr=subprocess.STDOUT,
    )


def repository_root() -> Path:
    return Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
    ).resolve()


def require_external_path(path: Path, purpose: str) -> None:
    if path.resolve().is_relative_to(repository_root()):
        raise ValueError(f"{purpose} must be outside the audited repository")


def current_paths() -> list[str]:
    return subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        text=True,
        stderr=subprocess.STDOUT,
    ).splitlines()


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
    """Scan both index and worktree forms without echoing content."""

    staged = staged_objects()
    staged_content = read_blobs(list(staged.values()))
    findings = []
    for path in paths:
        if path == SCANNER_PATH:
            continue
        candidates = []
        if path in staged and staged[path] in staged_content:
            candidates.append(staged_content[staged[path]])
        worktree_path = Path(path)
        if worktree_path.exists():
            try:
                worktree_content = worktree_path.read_bytes()
            except OSError as error:
                findings.append(f"current content scan failed: {path} ({error})")
            else:
                if worktree_content not in candidates:
                    candidates.append(worktree_content)
        if not candidates:
            findings.append(f"current content scan failed: {path} (content unavailable)")
            continue
        for content in candidates:
            if b"\x00" in content[:8192]:
                continue
            text = content.decode("utf-8", errors="replace")
            if SECRET_LIKE.search(text):
                findings.append(f"secret-like current content: path {path}")
                break
    return findings


def scan(revisions: list[str] | None = None) -> tuple[dict[str, set[str]], list[str], list[str]]:
    history = history_entries(revisions)
    current = current_paths()
    findings = (
        check_paths(history, current)
        + check_historical_content(history)
        + check_current_content(current)
    )
    return history, current, findings


def exact_candidate_receipt(candidate: str) -> tuple[dict[str, object], list[str]]:
    if re.fullmatch(r"[0-9a-f]{40}", candidate) is None:
        raise ValueError("candidate commit must be a full lowercase Git object ID")
    head = head_commit()
    if head != candidate:
        raise ValueError("checked-out HEAD does not equal the requested candidate commit")
    if not worktree_is_clean():
        raise ValueError("exact-candidate audit requires a clean index and worktree")
    refs = public_refs()
    revisions = [candidate, *(item["object_id"] for item in refs)]
    history, current, findings = scan(revisions)
    if findings:
        return {}, findings
    body = {
        "outcome": "pass",
        "candidate_commit": candidate,
        "head_commit": head,
        "ref_scope": "candidate-plus-remote-refs-and-tags-v1",
        "scanned_refs": refs,
        "commit_count": len(commits(revisions)),
        "historical_object_count": len(history),
        "current_path_count": len(current),
        "current_path_scope": "clean-index-and-worktree",
        "worktree_clean": True,
        "limitations": [
            "high-confidence pattern scanning does not prove absence of every protected value",
            "GitHub issues, reviews, logs, artifacts, releases, and repository settings require separate audit evidence",
        ],
    }
    receipt = receipt_with_digest(RECEIPT_SCHEMA_ID, RECEIPT_ID_PREFIX, body)
    validate(receipt, load_schema("core", "public-safety-receipt.v1.schema.json"))
    return receipt, []


def _load_expected_receipt(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("expected receipt is unavailable or invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("expected receipt must be a JSON object")
    try:
        validate(value, load_schema("core", "public-safety-receipt.v1.schema.json"))
    except ValidationFailure as exc:
        raise ValueError("expected receipt fails schema validation") from exc
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", help="full exact commit for a clean candidate receipt")
    parser.add_argument("--receipt-out", type=Path, help="external path for the generated receipt")
    parser.add_argument("--expect-receipt", type=Path, help="external receipt that the current run must equal")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    if (args.receipt_out or args.expect_receipt or args.as_json) and not args.candidate:
        parser.error("--candidate is required for receipt operations")

    if args.candidate:
        try:
            if args.receipt_out:
                require_external_path(args.receipt_out, "receipt output")
            if args.expect_receipt:
                require_external_path(args.expect_receipt, "expected receipt")
            receipt, findings = exact_candidate_receipt(args.candidate)
            if not findings and args.expect_receipt and receipt != _load_expected_receipt(args.expect_receipt):
                findings = ["exact-candidate receipt does not match the frozen receipt"]
        except ValueError as exc:
            findings = [str(exc)]
            receipt = {}
        if not findings and args.receipt_out:
            try:
                args.receipt_out.write_text(
                    json.dumps(receipt, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8",
                )
            except OSError:
                findings = ["exact-candidate receipt could not be written"]
        if findings:
            print("PUBLIC SAFETY CHECK FAILED", file=sys.stderr)
            for finding in sorted(set(findings)):
                print(f"- {finding}", file=sys.stderr)
            return 1
        if args.as_json:
            print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        else:
            print(
                "public safety candidate receipt passed: "
                f"{receipt['receipt_id']}, {receipt['commit_count']} commits, "
                f"{receipt['historical_object_count']} historical objects, "
                f"{receipt['current_path_count']} current paths"
            )
        return 0

    history, current, findings = scan()
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
