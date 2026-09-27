"""Synthetic AM-6 repository-linked freshness acceptance proof."""

from __future__ import annotations

import os
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, receipt_with_digest
from .coordination import (
    FRESHNESS_EXTENSION_ID,
    revision_digest,
)
from .coordination_freshness import evaluate_coordination_freshness
from .coordination_kickoff import build_kickoff_pack, validate_kickoff_pack
from .coordination_onboarding import onboard_project
from .coordination_sync import (
    configure_local_hub,
    load_authorized_coordination_snapshot,
    pull,
    store_coordination_record,
)
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, validate


CONFORMANCE_SCHEMA_ID = (
    "artifact-memory/coordination-freshness-conformance-receipt/v0"
)
PROJECT_ID = "11111111-1111-4111-8111-111111111111"
HUB_ID = "coordination-hub://synthetic/freshness"
SESSION_ID = "coordination-session://synthetic/freshness"
PRINCIPAL_ID = "coordination-principal://synthetic/freshness"
AUTHORITY_BOUNDARY = (
    "freshness conformance evidence is informational only and grants no execution, "
    "mutation, routing, disclosure, credential, spending, deployment, approval, or merge authority"
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout.strip()


def _commit(repo: Path, message: str, timestamp: str) -> str:
    environment = os.environ.copy()
    environment["GIT_AUTHOR_DATE"] = timestamp
    environment["GIT_COMMITTER_DATE"] = timestamp
    subprocess.run(
        ["git", "commit", "-q", "-m", message],
        cwd=repo,
        env=environment,
        check=True,
    )
    return _git(repo, "rev-parse", "HEAD")


def _label(fixtures: Path) -> dict[str, Any]:
    label = deepcopy(load_json(fixtures / "coordination" / "access-label.json"))
    label["projectNames"] = [
        {"projectId": PROJECT_ID, "projectName": "synthetic-service"}
    ]
    for field in label["may"]:
        label["may"][field] = [PROJECT_ID]
    label["mayNot"]["readProjects"] = []
    return label


def _task(
    fixtures: Path,
    label: dict[str, Any],
    ordinal: int,
    commit: str,
) -> dict[str, Any]:
    task = deepcopy(load_json(fixtures / "coordination" / "task-open.json"))
    task_id = "task_01J0000000000000000000000" + str(ordinal)
    task["taskId"] = task_id
    task["record_id"] = (
        f"record://coordination/{task['originId']}/task/{task_id}"
    )
    task["projectId"] = PROJECT_ID
    task["projectName"] = "synthetic-service"
    task["assignedWriter"] = PRINCIPAL_ID
    task["accessLabelRef"] = {
        "record_id": label["record_id"],
        "revision_digest": revision_digest(label),
    }
    task["extensions"][FRESHNESS_EXTENSION_ID]["value"][
        "trueAsOfCommit"
    ] = commit
    task["extensions"]["https://synthetic.example/extensions/opaque"] = {
        "version": "v1",
        "required": False,
        "value": {"opaque": ["synthetic", 1, True]},
    }
    return task


def exercise(fixtures: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        repo, vault, hub = root / "repo", root / "vault", root / "hub"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.name", "Synthetic Fixture")
        _git(repo, "config", "user.email", "fixture@example.invalid")
        label = _label(fixtures)
        configure_local_hub(
            hub,
            hub_id=HUB_ID,
            scope_generation=11,
            bindings=[
                {
                    "session_id": SESSION_ID,
                    "principal_id": PRINCIPAL_ID,
                    "access_label": label,
                }
            ],
        )
        onboard_project(
            repo,
            vault,
            hub,
            session_id=SESSION_ID,
            completed_at="2026-09-27T15:00:00Z",
            human_name="synthetic-service",
        )
        _git(repo, "add", ".agent-memory/repo.json")
        ancestor_commit = _commit(
            repo, "Add synthetic identity", "2026-09-27T15:01:00Z"
        )

        _git(repo, "switch", "-q", "-c", "synthetic-stale")
        (repo / "stale.txt").write_text("synthetic stale branch\n", encoding="utf-8")
        _git(repo, "add", "stale.txt")
        stale_commit = _commit(
            repo, "Synthetic stale branch", "2026-09-27T15:02:00Z"
        )
        _git(repo, "switch", "-q", "main")
        (repo / "current.txt").write_text("synthetic current branch\n", encoding="utf-8")
        _git(repo, "add", "current.txt")
        current_head = _commit(
            repo, "Synthetic current head", "2026-09-27T15:03:00Z"
        )

        stale_task = _task(fixtures, label, 3, stale_commit)
        opaque_extension_id = "https://synthetic.example/extensions/opaque"
        opaque_before = canonical_bytes(
            stale_task["extensions"][opaque_extension_id]
        )
        store_coordination_record(hub, stale_task)
        pull(
            vault,
            hub,
            session_id=SESSION_ID,
            completed_at="2026-09-27T15:04:00Z",
        )
        stale_pack = build_kickoff_pack(vault, PROJECT_ID, repo_root=repo)
        validate_kickoff_pack(stale_pack)
        stale_digest = revision_digest(stale_task)
        transported_stale = next(
            record
            for record in load_authorized_coordination_snapshot(vault)["records"]
            if record["record_id"] == stale_task["record_id"]
            and revision_digest(record) == stale_digest
        )
        opaque_transport_preserved = canonical_bytes(
            transported_stale["extensions"][opaque_extension_id]
        ) == opaque_before

        current_task = _task(fixtures, label, 5, ancestor_commit)
        store_coordination_record(hub, current_task)
        pull(
            vault,
            hub,
            session_id=SESSION_ID,
            completed_at="2026-09-27T15:05:00Z",
        )
        current_pack = build_kickoff_pack(vault, PROJECT_ID, repo_root=repo)
        validate_kickoff_pack(current_pack)

        required = deepcopy(current_task)
        required["extensions"]["https://synthetic.example/extensions/required"] = {
            "version": "v1",
            "required": True,
            "value": {},
        }
        try:
            evaluate_coordination_freshness(
                required,
                repo,
                expected_project_id=PROJECT_ID,
            )
        except ValidationFailure as exc:
            required_code = exc.code
        else:
            raise RuntimeError("unknown required coordination extension was accepted")

        top_level = deepcopy(current_task)
        top_level["trueAsOfCommit"] = ancestor_commit
        try:
            evaluate_coordination_freshness(
                top_level,
                repo,
                expected_project_id=PROJECT_ID,
            )
        except ValidationFailure as exc:
            top_level_code = exc.code
        else:
            raise RuntimeError("top-level trueAsOfCommit was accepted")

        stale_observation = stale_pack["queue"]["selected_task"]["freshness"]
        current_observation = current_pack["queue"]["selected_task"]["freshness"]
        receipt = receipt_with_digest(
            CONFORMANCE_SCHEMA_ID,
            "coordination-freshness-conformance-receipt://sha-256/",
            {
                "outcome": "passed",
                "stale_observation": stale_observation,
                "current_observation": current_observation,
                "unknown_optional_preserved": opaque_transport_preserved,
                "negative_codes": {
                    "unknown_required": required_code,
                    "top_level_freshness": top_level_code,
                },
                "authority_boundary": AUTHORITY_BOUNDARY,
            },
        )
    validate(
        receipt,
        load_schema(
            "core",
            "coordination-freshness-conformance-receipt.v0.schema.json",
        ),
    )
    return stale_pack, current_pack, receipt


def run(fixtures: Path, fixture: Path) -> dict[str, Any]:
    del fixture
    return exercise(fixtures)[2]


def render_coordination_freshness_conformance_receipt(
    receipt: dict[str, Any],
) -> str:
    stale = receipt["stale_observation"]
    current = receipt["current_observation"]
    return (
        "# Coordination freshness conformance receipt\n\n"
        f"- Outcome: `{receipt['outcome']}`\n"
        f"- Divergent commit status: `{stale['status']}`\n"
        f"- Ancestor commit status: `{current['status']}`\n"
        "- Unknown optional extension preserved: "
        f"`{str(receipt['unknown_optional_preserved']).lower()}`\n"
        f"- Unknown required diagnostic: `{receipt['negative_codes']['unknown_required']}`\n"
        f"- Top-level freshness diagnostic: `{receipt['negative_codes']['top_level_freshness']}`\n"
        f"- Receipt: `{receipt['receipt_id']}`\n\n"
        f"Authority boundary: {receipt['authority_boundary']}.\n"
    )
