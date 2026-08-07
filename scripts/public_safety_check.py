#!/usr/bin/env python3
"""Fail-closed public-safety checks for tracked paths and Git history."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.canonical import receipt_with_digest
from artifact_memory.sanitized_custody_attestation import (
    render_sanitized_custody_attestation,
    validate_historical_sanitized_custody_attestation,
    validate_sanitized_custody_attestation,
)
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import (
    ValidationFailure,
    load_json,
    load_json_bytes,
    validate,
)


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
SANITIZED_CUSTODY_RECEIPT_PATH = "evidence/sanitized/custody/v1/receipt.md"
SANITIZED_CUSTODY_ATTESTATION_PATH = "evidence/sanitized/custody/v1/receipt.json"
RECEIPT_SCHEMA_ID = "artifact-memory/public-safety-receipt/v1"
RECEIPT_ID_PREFIX = "public-safety-receipt://"
PUBLIC_REF_PATTERN = re.compile(r"^refs/(?:remotes/[^/]+/[^/].*|tags/[^/].*)$")
GIT_OBJECT_ID_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SUPPORTED_LEGACY_CUSTODY_MARKDOWN_REWRITES = {
    "pre-contract-v0": (
        "published `endpoint://` value is a portable logical identity",
        "published logical endpoint value is a portable identity",
    )
}
MACHINE_BINDING_PATTERNS = (
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    re.compile(r"\[[0-9A-Fa-f:%.]+\]"),
    re.compile(r"\b(?:[0-9A-Fa-f]{1,4}:){2,}[0-9A-Fa-f:]{1,39}\b"),
    re.compile(r"\b(?:https?|sftp|ssh|ftp|ftps|nfs|smb)://", re.IGNORECASE),
    re.compile(
        r"\b(?:backup|codex-task|task|content|artifact|artifact-version|"
        r"restore-receipt|backup-receipt|custody-receipt|endpoint)://",
        re.IGNORECASE,
    ),
    re.compile(r"(?<![A-Za-z0-9])/(?:Users|home|srv|mnt|var|etc|opt|private|Volumes)/\S+"),
    re.compile(r"\b[A-Za-z]:[\\/]\S+"),
    re.compile(r"\\\\[^\s\\]+\\[^\s\\]+"),
    re.compile(r"\b[A-Za-z0-9._~-]+@[A-Za-z0-9._~-]+(?::[\\/]\S+)?"),
    re.compile(r"\b[0-9A-Fa-f]{40,64}\b"),
    re.compile(
        r"\b(?:private repository|snapshot reference|repository identifier|"
        r"task identifier)\s*:",
        re.IGNORECASE,
    ),
)


class PublicSafetyInvalidGitOutput(RuntimeError):
    """Raised when Git emits data outside the exact public-audit contract."""


def _machine_binding_findings(text: str) -> list[str]:
    findings = []
    binding_scope = text
    if SECRET_LIKE.search(binding_scope):
        findings.append("secret-like-binding")
    for pattern in MACHINE_BINDING_PATTERNS:
        if pattern.search(binding_scope):
            findings.append("machine-binding-detected")
            break
    return sorted(set(findings))


def _markdown_without_exact_endpoint(text: str, endpoint: str) -> tuple[str, list[str]]:
    endpoint_line = f"- Endpoint: `{endpoint}`"
    lines = text.splitlines(keepends=True)
    indexes = [
        index
        for index, line in enumerate(lines)
        if line.rstrip("\r\n") == endpoint_line
    ]
    if len(indexes) != 1:
        return text, ["logical-endpoint-line-invalid"]
    return "".join(line for index, line in enumerate(lines) if index != indexes[0]), []


def _historical_custody_receipt_findings(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for old, new in SUPPORTED_LEGACY_CUSTODY_MARKDOWN_REWRITES.values():
        normalized = normalized.replace(old, new)
    matches = re.findall(
        r"^- Endpoint: `([^`]+)`$",
        normalized,
        flags=re.MULTILINE,
    )
    try:
        approved_endpoint = str(_load_sanitized_custody_attestation()["endpoint"])
    except ValidationFailure:
        return ["contract-invalid"]
    if len(matches) != 1 or matches[0] != approved_endpoint:
        return sorted(
            set(["logical-endpoint-invalid", *_machine_binding_findings(normalized)])
        )
    scope, findings = _markdown_without_exact_endpoint(normalized, approved_endpoint)
    return sorted(set([*findings, *_machine_binding_findings(scope)]))


def _load_sanitized_custody_attestation() -> dict[str, object]:
    attestation = load_json(ROOT / SANITIZED_CUSTODY_ATTESTATION_PATH)
    if not isinstance(attestation, dict):
        raise ValidationFailure(
            "type-mismatch",
            "sanitized custody attestation must be an object",
        )
    validate_sanitized_custody_attestation(attestation)
    return attestation


def sanitized_custody_attestation_findings(text: str) -> list[str]:
    """Validate the authoritative machine receipt and its privacy boundary."""

    try:
        attestation = load_json_bytes(text.encode("utf-8"))
        if not isinstance(attestation, dict):
            raise ValidationFailure("type-mismatch", "attestation must be an object")
        validate_sanitized_custody_attestation(attestation)
    except (UnicodeError, ValidationFailure):
        return ["contract-invalid"]
    endpoint = attestation["endpoint"]
    other_values = "\n".join(
        str(value) for key, value in attestation.items() if key != "endpoint"
    )
    return _machine_binding_findings(other_values)


def _historical_custody_attestation_findings(text: str) -> list[str]:
    try:
        attestation = load_json_bytes(text.encode("utf-8"))
        if not isinstance(attestation, dict):
            raise ValidationFailure("type-mismatch", "attestation must be an object")
        validate_historical_sanitized_custody_attestation(attestation)
        approved_endpoint = _load_sanitized_custody_attestation()["endpoint"]
        if attestation["endpoint"] != approved_endpoint:
            return ["logical-endpoint-invalid"]
    except (TypeError, UnicodeError, ValidationFailure):
        return ["contract-invalid"]
    other_values = "\n".join(
        str(value) for key, value in attestation.items() if key != "endpoint"
    )
    return _machine_binding_findings(other_values)


def sanitized_custody_receipt_findings(text: str) -> list[str]:
    """Validate the public projection without claiming private replay."""

    try:
        attestation = _load_sanitized_custody_attestation()
    except ValidationFailure:
        return ["contract-invalid"]
    findings = []
    if text != render_sanitized_custody_attestation(attestation):
        findings.append("contract-render-mismatch")
    endpoint = str(attestation["endpoint"])
    scope, endpoint_findings = _markdown_without_exact_endpoint(text, endpoint)
    findings.extend(endpoint_findings)
    findings.extend(_machine_binding_findings(scope))
    return sorted(set(findings))


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
        entries.setdefault(parts[0], set())
        if len(parts) == 2:
            entries[parts[0]].add(parts[1])
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
        if line.count("\t") != 1:
            raise PublicSafetyInvalidGitOutput("Git public ref output is invalid")
        ref, object_id = line.split("\t", 1)
        if (
            PUBLIC_REF_PATTERN.fullmatch(ref) is None
            or GIT_OBJECT_ID_PATTERN.fullmatch(object_id) is None
        ):
            raise PublicSafetyInvalidGitOutput("Git public ref output is invalid")
        if FORBIDDEN_PATH.search(ref) or SECRET_LIKE.search(ref):
            raise PublicSafetyInvalidGitOutput(
                "Git public ref name violates public-safety policy"
            )
        if ref.startswith("refs/remotes/") and ref.endswith("/HEAD"):
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


def _repository_file_inodes(root: Path) -> set[tuple[int, int]]:
    inodes: set[tuple[int, int]] = set()
    for candidate in root.rglob("*"):
        try:
            metadata = candidate.stat(follow_symlinks=False)
        except OSError:
            continue
        if candidate.is_file() and not candidate.is_symlink():
            inodes.add((metadata.st_dev, metadata.st_ino))
    return inodes


def write_external_receipt(path: Path, content: str) -> None:
    """Atomically replace an external receipt without following its final entry."""

    root = repository_root()
    parent = path.parent.resolve(strict=True)
    if parent.is_relative_to(root):
        raise ValueError("receipt output must be outside the audited repository")
    destination = parent / path.name
    if destination.is_symlink():
        raise ValueError("receipt output must not be a symbolic link")
    if destination.exists():
        metadata = destination.stat(follow_symlinks=False)
        if (metadata.st_dev, metadata.st_ino) in _repository_file_inodes(root):
            raise ValueError("receipt output must not share a repository file inode")

    temporary_name: str | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except OSError:
                pass


def current_paths() -> list[str]:
    return subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        text=True,
        stderr=subprocess.STDOUT,
    ).splitlines()


def historical_paths(revisions: list[str] | None = None) -> list[str]:
    """Enumerate every changed path without rename collapsing."""

    output = subprocess.check_output(
        [
            "git",
            "log",
            "--format=",
            "--name-only",
            "--no-renames",
            "-z",
            *_revision_arguments(revisions),
        ],
        stderr=subprocess.STDOUT,
    )
    return sorted(
        {
            record.decode("utf-8", errors="surrogateescape")
            for record in output.split(b"\0")
            if record
        }
    )


def check_paths(
    history: dict[str, set[str]],
    current: list[str],
    exact_historical_paths: list[str] | None = None,
) -> list[str]:
    findings = []
    paths = [path for names in history.values() for path in names]
    paths.extend(exact_historical_paths or [])
    paths.extend(current)
    for path in paths:
        if FORBIDDEN_PATH.search(path):
            findings.append(f"forbidden repository path: {path}")
    return sorted(set(findings))


def read_objects(object_ids: list[str]) -> dict[str, tuple[str, bytes]]:
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

    objects = {}
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
        objects[object_id] = (object_type, content)
    return objects


def read_blobs(object_ids: list[str]) -> dict[str, bytes]:
    return {
        object_id: content
        for object_id, (object_type, content) in read_objects(object_ids).items()
        if object_type == "blob"
    }


def check_historical_content(history: dict[str, set[str]]) -> list[str]:
    """Scan each reachable blob once and never print matching content."""

    blobs = read_blobs(list(history))
    findings = []
    for object_id, paths in history.items():
        non_scanner_paths = sorted(path for path in paths if path != SCANNER_PATH)
        if object_id not in blobs or (paths and not non_scanner_paths):
            continue
        text = blobs[object_id].decode("utf-8", errors="replace")
        if SECRET_LIKE.search(text):
            path_evidence = f", path {non_scanner_paths[0]}" if non_scanner_paths else ""
            findings.append(f"secret-like historical content: object {object_id}{path_evidence}")
        if SANITIZED_CUSTODY_RECEIPT_PATH in non_scanner_paths:
            for code in _historical_custody_receipt_findings(text):
                findings.append(
                    "sanitized custody receipt historical content invalid: "
                    f"object {object_id}, {code}"
                )
        if SANITIZED_CUSTODY_ATTESTATION_PATH in non_scanner_paths:
            for code in _historical_custody_attestation_findings(text):
                findings.append(
                    "sanitized custody attestation historical content invalid: "
                    f"object {object_id}, {code}"
                )
    return findings


def check_revision_metadata(
    revisions: list[str] | None,
    refs: list[dict[str, str]],
) -> list[str]:
    commit_ids = commits(revisions)
    tag_refs = [item for item in refs if item["ref"].startswith("refs/tags/")]
    object_ids = sorted(set(commit_ids) | {item["object_id"] for item in tag_refs})
    objects = read_objects(object_ids)
    findings = []
    for object_id in object_ids:
        object_record = objects.get(object_id)
        if object_record is None:
            continue
        object_type, content = object_record
        matching_refs = sorted(item["ref"] for item in tag_refs if item["object_id"] == object_id)
        if object_type not in {"commit", "tag"} and not matching_refs:
            continue
        if SECRET_LIKE.search(content.decode("utf-8", errors="replace")):
            ref_evidence = f", ref {matching_refs[0]}" if matching_refs else ""
            findings.append(
                f"secret-like revision metadata: {object_type} object {object_id}{ref_evidence}"
            )
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
            if path == SANITIZED_CUSTODY_RECEIPT_PATH:
                for code in sanitized_custody_receipt_findings(text):
                    findings.append(f"sanitized custody receipt invalid: {code}")
            if path == SANITIZED_CUSTODY_ATTESTATION_PATH:
                for code in sanitized_custody_attestation_findings(text):
                    findings.append(f"sanitized custody attestation invalid: {code}")
    return findings


def scan(
    revisions: list[str] | None = None,
    refs: list[dict[str, str]] | None = None,
) -> tuple[dict[str, set[str]], list[str], list[str]]:
    history = history_entries(revisions)
    current = current_paths()
    metadata_refs = public_refs() if refs is None else refs
    findings = (
        check_paths(history, current, historical_paths(revisions))
        + check_historical_content(history)
        + check_revision_metadata(revisions, metadata_refs)
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
    history, current, findings = scan(revisions, refs)
    commit_ids = commits(revisions)
    final_head = head_commit()
    final_refs = public_refs()
    final_clean = worktree_is_clean()
    if final_head != head:
        raise ValueError("checked-out HEAD changed during the exact-candidate audit")
    if final_refs != refs:
        raise ValueError("public refs changed during the exact-candidate audit")
    if not final_clean:
        raise ValueError("index or worktree changed during the exact-candidate audit")
    if findings:
        return {}, findings
    body = {
        "outcome": "pass",
        "candidate_commit": candidate,
        "head_commit": head,
        "ref_scope": "candidate-plus-remote-refs-and-tags-v1",
        "scanned_refs": refs,
        "commit_count": len(commit_ids),
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
        value = load_json(path)
    except ValidationFailure as exc:
        raise ValueError("expected receipt is unavailable or invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("expected receipt must be a JSON object")
    try:
        validate(value, load_schema("core", "public-safety-receipt.v1.schema.json"))
    except ValidationFailure as exc:
        raise ValueError("expected receipt fails schema validation") from exc
    body = {key: item for key, item in value.items() if key not in {"schema_id", "receipt_id"}}
    if value != receipt_with_digest(RECEIPT_SCHEMA_ID, RECEIPT_ID_PREFIX, body):
        raise ValueError("expected receipt canonical identity does not match its content")
    return value


def render_candidate_receipt(receipt: dict[str, object]) -> str:
    refs = receipt["scanned_refs"]
    assert isinstance(refs, list)
    ref_label = "ref" if len(refs) == 1 else "refs"
    return (
        "# Public safety candidate receipt\n\n"
        f"- Outcome: `{receipt['outcome']}`\n"
        f"- Receipt: `{receipt['receipt_id']}`\n"
        f"- Candidate/HEAD: `{receipt['candidate_commit']}`\n"
        f"- Ref scope: `{receipt['ref_scope']}` ({len(refs)} {ref_label})\n"
        f"- Reachable commits: {receipt['commit_count']}\n"
        f"- Historical objects: {receipt['historical_object_count']}\n"
        f"- Current paths: {receipt['current_path_count']}\n"
        f"- Worktree clean: `{str(receipt['worktree_clean']).lower()}`\n"
    )


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
        except subprocess.CalledProcessError:
            findings = ["Git audit command failed"]
            receipt = {}
        except OSError:
            findings = ["audit input or Git executable is unavailable"]
            receipt = {}
        except RuntimeError:
            findings = ["Git object audit failed"]
            receipt = {}
        except ValidationFailure as exc:
            findings = [f"audit receipt validation failed: {exc.code}"]
            receipt = {}
        if not findings and args.receipt_out:
            try:
                write_external_receipt(
                    args.receipt_out,
                    json.dumps(receipt, sort_keys=True, indent=2) + "\n",
                )
            except ValueError as exc:
                findings = [str(exc)]
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
            print(render_candidate_receipt(receipt), end="")
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
