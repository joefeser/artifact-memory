"""Sanitized probes for the v0 filesystem conformance matrix."""

from __future__ import annotations

import os
import platform
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

from .repo_identity import load_repo_identity
from .validator import ValidationFailure


def _case_sensitivity(root: Path) -> bool:
    probe = root / "caseprobe"
    probe.write_text("synthetic", encoding="utf-8")
    return not (root / "CASEPROBE").exists()


def _unicode_behavior(root: Path) -> str:
    nfc = "caf\u00e9"
    nfd = unicodedata.normalize("NFD", nfc)
    (root / nfc).write_text("nfc", encoding="utf-8")
    try:
        (root / nfd).write_text("nfd", encoding="utf-8")
    except OSError:
        return "collision-or-normalized"
    names = {entry.name for entry in root.iterdir()}
    if nfc in names and nfd in names and nfc != nfd:
        return "distinct-names"
    return "normalized-or-reported-differently"


def _symlink_behavior(root: Path) -> str:
    target = root / "link-target"
    link = root / "link"
    target.write_text("synthetic", encoding="utf-8")
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        return "creation-unsupported"
    return "created-but-v0-scan-unsupported"


def _repo_identity_redirect_behavior(root: Path) -> str:
    if os.name != "nt":
        return "not-applicable"
    target = root / "repository-target"
    manifest_directory = target / ".agent-memory"
    manifest_directory.mkdir(parents=True)
    (manifest_directory / "repo.json").write_text(
        '{"uuid":"11111111-1111-4111-8111-111111111111",'
        '"humanName":"synthetic-platform-repository"}\n',
        encoding="utf-8",
    )
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("GIT_")
    }
    commands = (
        ["git", "init", "-q"],
        ["git", "config", "user.name", "Synthetic Fixture"],
        ["git", "config", "user.email", "fixture@example.invalid"],
        ["git", "add", ".agent-memory/repo.json"],
        [
            "git",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "-m",
            "Synthetic repository identity",
        ],
    )
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=target,
            env=environment,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if completed.returncode != 0:
            return "fixture-creation-failed"

    junction = root / "repository-junction"
    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        return "junction-creation-failed"
    try:
        load_repo_identity(junction)
    except ValidationFailure as exc:
        if exc.code == "repo-identity-unsafe":
            return "junction-rejected"
        return "unexpected-diagnostic"
    return "junction-followed"


def probe_platform() -> dict[str, Any]:
    """Return only portable observations; never return the temporary path."""
    diagnostics: list[str] = []
    with tempfile.TemporaryDirectory(prefix="artifact-memory-matrix-") as temporary:
        root = Path(temporary)
        try:
            case_sensitive = _case_sensitivity(root)
        except OSError as error:
            case_sensitive = None
            diagnostics.append(f"case-probe:{type(error).__name__}")
        try:
            unicode_behavior = _unicode_behavior(root)
        except OSError as error:
            unicode_behavior = "probe-failed"
            diagnostics.append(f"unicode-probe:{type(error).__name__}")
        try:
            symlink_behavior = _symlink_behavior(root)
        except OSError as error:
            symlink_behavior = "probe-failed"
            diagnostics.append(f"symlink-probe:{type(error).__name__}")
        try:
            repo_identity_redirect_behavior = _repo_identity_redirect_behavior(
                root
            )
        except OSError as error:
            repo_identity_redirect_behavior = "probe-failed"
            diagnostics.append(
                f"repo-identity-redirect-probe:{type(error).__name__}"
            )

    return {
        "schema_id": "artifact-memory/platform-matrix-receipt/v2",
        "profile": "v0-case-sensitive-unicode-codepoint",
        "runtime": {"family": platform.system().lower(), "python": platform.python_version()},
        "observations": {
            "case_sensitivity": case_sensitive,
            "unicode_name_behavior": unicode_behavior,
            "symlink_behavior": symlink_behavior,
            "repo_identity_redirect_behavior": repo_identity_redirect_behavior,
            "timestamps": "ignored-by-v0-profile",
            "mount_layout": "logical-relative-paths-only",
        },
        "diagnostics": diagnostics,
        "limitations": [
            "probe observations describe this runner only",
            "v0 does not infer Unicode normalization equivalence",
            "v0 scan treats symlinks as explicitly unsupported",
            "repository identity redirect behavior is exercised with a "
            "junction only on Windows",
        ],
    }
