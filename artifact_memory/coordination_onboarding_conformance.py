"""Synthetic AM-9 project-onboarding acceptance proof."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from .canonical import receipt_with_digest
from .coordination import revision_digest
from .coordination_onboarding import (
    BOOTSTRAP_PACK_SCHEMA_ID,
    validate_bootstrap_pack,
    validate_bootstrap_receipt,
)
from .coordination_sync import (
    configure_local_hub,
    directory_digest,
    store_coordination_record,
)
from .schema_resources import load_schema
from .validator import load_json, validate


CONFORMANCE_SCHEMA_ID = (
    "artifact-memory/coordination-onboarding-conformance-receipt/v0"
)
PROJECT_ID = "11111111-1111-4111-8111-111111111111"
HUB_ID = "coordination-hub://synthetic/onboarding"
SESSION_ID = "coordination-session://synthetic/onboarding"
PRINCIPAL_ID = "coordination-principal://synthetic/onboarding"
AUTHORITY_BOUNDARY = (
    "onboarding proof grants no execution, mutation, routing, disclosure, "
    "credential, spending, deployment, approval, or merge authority"
)


def _init_repo(
    root: Path,
    identity: dict[str, str] | None = None,
    *,
    commit_baseline: bool = True,
) -> None:
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Synthetic Fixture"], cwd=root, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=root,
        check=True,
    )
    (root / "README.md").write_text("# Synthetic onboarding repo\n", encoding="utf-8")
    if identity is not None:
        directory = root / ".agent-memory"
        directory.mkdir()
        (directory / "repo.json").write_text(
            json.dumps(identity, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    if commit_baseline:
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "Synthetic baseline"],
            cwd=root,
            check=True,
        )


def _label(fixtures: Path) -> dict[str, Any]:
    label = deepcopy(load_json(fixtures / "coordination" / "access-label.json"))
    label["projectNames"] = [
        {"projectId": PROJECT_ID, "projectName": "synthetic-service"}
    ]
    for field in label["may"]:
        label["may"][field] = [PROJECT_ID]
    label["mayNot"]["readProjects"] = []
    return label


def _configure(hub: Path, label: dict[str, Any]) -> None:
    configure_local_hub(
        hub,
        hub_id=HUB_ID,
        scope_generation=1,
        bindings=[
            {
                "session_id": SESSION_ID,
                "principal_id": PRINCIPAL_ID,
                "access_label": label,
            }
        ],
    )


def _task(fixtures: Path, label: dict[str, Any]) -> dict[str, Any]:
    task = deepcopy(load_json(fixtures / "coordination" / "task-open.json"))
    task["projectId"] = PROJECT_ID
    task["projectName"] = "synthetic-service"
    task["assignedWriter"] = PRINCIPAL_ID
    task["accessLabelRef"] = {
        "record_id": label["record_id"],
        "revision_digest": revision_digest(label),
    }
    return task


def _run_artifact_memory(
    source_root: Path,
    arguments: list[str],
) -> subprocess.CompletedProcess[str]:
    # This proof intentionally exercises the installed CLI boundary. The
    # interpreter and module are fixed locally, every variable is one argv
    # value, and shell=False prevents command-text interpretation.
    return subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
        [sys.executable, "-m", "artifact_memory", *arguments],
        cwd=source_root,
        text=True,
        capture_output=True,
        shell=False,
    )


def _command(
    source_root: Path,
    repo: Path,
    vault: Path,
    hub: Path,
    *,
    completed_at: str,
) -> dict[str, Any]:
    completed = _run_artifact_memory(
        source_root,
        [
            "onboard",
            str(repo),
            "--vault",
            str(vault),
            "--hub",
            str(hub),
            "--session-id",
            SESSION_ID,
            "--human-name",
            "synthetic-service",
            "--completed-at",
            completed_at,
            "--json",
        ],
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)
    return json.loads(completed.stdout)


def run(fixtures: Path, fixture: Path) -> dict[str, Any]:
    del fixture  # the proof is generated wholly in a disposable directory
    source_root = fixtures.parent
    label = _label(fixtures)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()

        fresh_repo = root / "fresh-repo"
        fresh_vault = root / "fresh-vault"
        fresh_hub = root / "fresh-hub"
        _init_repo(fresh_repo, commit_baseline=False)
        _configure(fresh_hub, label)
        first = _command(
            source_root,
            fresh_repo,
            fresh_vault,
            fresh_hub,
            completed_at="2026-09-26T20:00:00Z",
        )
        validate_bootstrap_receipt(first)
        pack_path = (
            fresh_vault
            / "generated"
            / "coordination-onboarding"
            / PROJECT_ID
            / "bootstrap-kickoff.json"
        )
        pack = load_json(pack_path)
        validate_bootstrap_pack(pack)
        if pack["schema_id"] != BOOTSTRAP_PACK_SCHEMA_ID:
            raise RuntimeError("bootstrap kickoff pack used an unexpected schema")

        subprocess.run(
            ["git", "add", ".agent-memory/repo.json"], cwd=fresh_repo, check=True
        )
        subprocess.run(
            ["git", "commit", "-q", "-m", "Add synthetic project identity"],
            cwd=fresh_repo,
            check=True,
        )
        before_retry = directory_digest(fresh_vault)
        replay = _command(
            source_root,
            fresh_repo,
            fresh_vault,
            fresh_hub,
            completed_at="2026-09-26T21:00:00Z",
        )
        after_retry = directory_digest(fresh_vault)

        existing_repo = root / "existing-repo"
        existing_vault = root / "existing-vault"
        existing_hub = root / "existing-hub"
        _init_repo(existing_repo)
        _configure(existing_hub, label)
        store_coordination_record(existing_vault, _task(fixtures, label))
        existing = _command(
            source_root,
            existing_repo,
            existing_vault,
            existing_hub,
            completed_at="2026-09-26T22:00:00Z",
        )
        validate_bootstrap_receipt(existing)

        unonboarded_repo = root / "unonboarded-repo"
        unonboarded_vault = root / "unonboarded-vault"
        _init_repo(
            unonboarded_repo,
            {"uuid": PROJECT_ID, "humanName": "synthetic-service"},
        )
        rejected = _run_artifact_memory(
            source_root,
            [
                "sync",
                "--repo",
                str(unonboarded_repo),
                "--vault",
                str(unonboarded_vault),
                "--hub",
                str(fresh_hub),
                "--session-id",
                SESSION_ID,
                "--completed-at",
                "2026-09-26T23:00:00Z",
                "--json",
            ],
        )
        if rejected.returncode != 2:
            raise RuntimeError("unonboarded repo-bound sync did not fail typed")
        rejected_payload = json.loads(rejected.stdout)
        sync_diagnostic = rejected_payload["diagnostics"][0]
        rejected_append = _run_artifact_memory(
            source_root,
            [
                "record",
                "append",
                str(fixtures / "coordination" / "task-open.json"),
                "--repo",
                str(unonboarded_repo),
                "--vault",
                str(unonboarded_vault),
                "--json",
            ],
        )
        if rejected_append.returncode != 2:
            raise RuntimeError("unonboarded repo-bound append did not fail typed")
        append_payload = json.loads(rejected_append.stdout)
        append_diagnostic = append_payload["diagnostics"][0]

        stored = b"".join(
            path.read_bytes() for path in fresh_vault.rglob("*") if path.is_file()
        )
        receipt = receipt_with_digest(
            CONFORMANCE_SCHEMA_ID,
            "coordination-onboarding-conformance-receipt://sha-256/",
            {
                "outcome": "passed",
                "fresh_repo": {
                    "project_id": load_json(
                        fresh_repo / ".agent-memory" / "repo.json"
                    )["uuid"],
                    "identity_state": first["repo_identity_state"],
                    "bootstrap_receipt_valid": True,
                    "kickoff_pack_valid": True,
                },
                "existing_repo": {
                    "pair_count_before": existing["record_state"]["pair_count_before"],
                    "pair_count_after": existing["record_state"]["pair_count_after"],
                    "duplicate_pair_count": existing["record_state"]["duplicate_pair_count"],
                    "history_import_state": existing["history_import"]["state"],
                },
                "idempotency": {
                    "receipt_replayed": replay == first,
                    "vault_byte_identical": before_retry == after_retry,
                },
                "unonboarded_precondition": {
                    "sync_code": sync_diagnostic["code"],
                    "append_code": append_diagnostic["code"],
                    "names_onboard_fix": all(
                        "artifact-memory onboard" in diagnostic["message"]
                        for diagnostic in (sync_diagnostic, append_diagnostic)
                    ),
                },
                "privacy": {
                    "full_access_label_body_count": stored.count(
                        b"artifact-memory/coordination-access-label/v0"
                    ),
                    "machine_path_match_count": stored.count(str(root).encode("utf-8")),
                },
                "authority_boundary": AUTHORITY_BOUNDARY,
            },
        )
    validate(
        receipt,
        load_schema(
            "core", "coordination-onboarding-conformance-receipt.v0.schema.json"
        ),
    )
    return receipt


def render_coordination_onboarding_conformance_receipt(
    receipt: dict[str, Any],
) -> str:
    return (
        "# Coordination onboarding conformance receipt\n\n"
        f"- Outcome: `{receipt['outcome']}`\n"
        f"- Fresh project UUID: `{receipt['fresh_repo']['project_id']}`\n"
        f"- Fresh identity state: `{receipt['fresh_repo']['identity_state']}`\n"
        f"- Existing pair counts: `{receipt['existing_repo']['pair_count_before']}` "
        f"before / `{receipt['existing_repo']['pair_count_after']}` after\n"
        f"- Duplicate pairs: `{receipt['existing_repo']['duplicate_pair_count']}`\n"
        f"- Byte-identical rerun: `{str(receipt['idempotency']['vault_byte_identical']).lower()}`\n"
        f"- Unonboarded sync diagnostic: `{receipt['unonboarded_precondition']['sync_code']}`\n"
        f"- Unonboarded append diagnostic: `{receipt['unonboarded_precondition']['append_code']}`\n"
        f"- Full AccessLabel bodies retained by client: `{receipt['privacy']['full_access_label_body_count']}`\n"
        f"- Machine-path matches: `{receipt['privacy']['machine_path_match_count']}`\n"
        f"- Receipt: `{receipt['receipt_id']}`\n\n"
        f"Authority boundary: {receipt['authority_boundary']}.\n"
    )
