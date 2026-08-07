#!/usr/bin/env python3
"""Run issue #39 against TraceMap's exact provider-contract anchor."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.canonical import canonical_bytes, sha256_path
from artifact_memory.tracemap_adapter import TRACE_MAP_CONTRACT_ANCHOR
from artifact_memory.vertical_slice import run_vertical_slice


SOURCE = ROOT / "fixtures" / "synthetic" / "vertical-slice" / "v1" / "source"
EXPECTED_SOURCE_COMMIT = "78b4e1fe6b31195de8898a25e4ad7e2895987d83"


def _run(args: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout.strip()


def _export_trace_map(trace_map_repo: Path, destination: Path) -> None:
    archive = subprocess.run(
        ["git", "archive", "--format=tar", TRACE_MAP_CONTRACT_ANCHOR],
        cwd=trace_map_repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if archive.returncode != 0:
        raise RuntimeError(archive.stderr.decode("utf-8", errors="replace").strip())
    with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as bundle:
        destination_root = destination.resolve()
        for member in bundle.getmembers():
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError("TraceMap archive contains an unsafe path")
            target = destination / relative
            if not target.resolve().is_relative_to(destination_root):
                raise RuntimeError("TraceMap archive escapes the export root")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isreg():
                raise RuntimeError("TraceMap archive contains an unsupported member")
            source = bundle.extractfile(member)
            if source is None:
                raise RuntimeError("TraceMap archive member is unreadable")
            target.parent.mkdir(parents=True, exist_ok=True)
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output)


def _create_synthetic_repo(parent: Path) -> Path:
    repo = parent / "SyntheticOrders"
    shutil.copytree(SOURCE, repo)
    _run(["git", "init", "--initial-branch=main"], cwd=repo)
    _run(["git", "config", "user.name", "Artifact Memory Synthetic Fixture"], cwd=repo)
    _run(["git", "config", "user.email", "synthetic-fixture@artifact-memory.invalid"], cwd=repo)
    _run(["git", "add", "."], cwd=repo)
    environment = {
        **dict(os.environ),
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
    }
    _run(["git", "commit", "-m", "Add SyntheticOrders fixture"], cwd=repo, env=environment)
    commit = _run(["git", "rev-parse", "HEAD"], cwd=repo)
    if commit != EXPECTED_SOURCE_COMMIT:
        raise RuntimeError(f"synthetic source commit changed: {commit}")
    return repo


def _select_status_facts(packet: Path) -> tuple[str, str]:
    facts = [
        json.loads(line)
        for line in (packet / "facts.ndjson").read_text(encoding="utf-8").splitlines()
    ]
    declarations = [
        fact
        for fact in facts
        if fact.get("contractElement") == "Status"
        and fact.get("factType") in {"PropertyDeclared", "PropertyDeclaration"}
        and isinstance(fact.get("factId"), str)
        and fact["factId"]
    ]
    accesses = [
        fact
        for fact in facts
        if fact.get("contractElement") == "Status"
        and fact.get("factType") in {"PropertyAccessed", "PropertyAccess"}
        and fact.get("evidenceTier") == "Tier1Semantic"
        and isinstance(fact.get("factId"), str)
        and fact["factId"]
    ]
    if len(declarations) != 1 or len(accesses) != 1:
        raise RuntimeError("TraceMap did not emit exactly one expected declaration and semantic access")
    return declarations[0]["factId"], accesses[0]["factId"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracemap-repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    trace_map_repo = args.tracemap_repo.resolve()
    output = args.output.resolve()
    if output.exists():
        raise RuntimeError("output must not already exist")
    if _run(["git", "cat-file", "-t", TRACE_MAP_CONTRACT_ANCHOR], cwd=trace_map_repo) != "commit":
        raise RuntimeError("TraceMap contract anchor is unavailable")

    scratch_parent = ROOT / ".agent-control"
    scratch_parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="artifact-memory-tracemap-slice-",
        dir=scratch_parent,
    ) as temporary:
        root = Path(temporary)
        provider = root / "TraceMap"
        provider.mkdir()
        _export_trace_map(trace_map_repo, provider)
        synthetic_repo = _create_synthetic_repo(root)
        packet = root / "packet"
        _run(
            ["dotnet", "build", str(provider / "src/dotnet/TraceMap.sln")],
            cwd=provider,
        )
        _run(
            [
                "dotnet",
                "run",
                "--project",
                str(provider / "src/dotnet/TraceMap.Cli"),
                "--",
                "scan",
                "--repo",
                synthetic_repo.name,
                "--out",
                str(packet),
            ],
            cwd=root,
        )
        _run(
            [
                sys.executable,
                str(provider / "scripts/validate-adapter-artifacts.py"),
                str(packet),
            ],
            cwd=provider,
        )
        manifest = json.loads((packet / "scan-manifest.json").read_text(encoding="utf-8"))
        if manifest["repoName"] != "SyntheticOrders":
            raise RuntimeError("TraceMap repository identity was not portable")
        declaration_id, access_id = _select_status_facts(packet)
        configuration_digest = "sha-256:" + hashlib.sha256(
            canonical_bytes(
                {
                    "command": "scan",
                    "repo": "SyntheticOrders",
                    "provider_contract_anchor": TRACE_MAP_CONTRACT_ANCHOR,
                }
            )
        ).hexdigest()
        receipt = run_vertical_slice(
            SOURCE,
            packet,
            output,
            expected_repo="SyntheticOrders",
            expected_commit=EXPECTED_SOURCE_COMMIT,
            tool_source_commit=TRACE_MAP_CONTRACT_ANCHOR,
            configuration_digest=configuration_digest,
            rule_catalog_digest=sha256_path(provider / "rules/rule-catalog.yml"),
            selected_declaration_fact_id=declaration_id,
            selected_access_fact_id=access_id,
            passphrase=secrets.token_urlsafe(32),
        )
    sys.stdout.write(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
