"""Synthetic AM-8 repository identity and project-binding proof."""

from __future__ import annotations

import json
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from .canonical import receipt_with_digest
from .coordination import revision_digest
from .repo_identity import (
    load_repo_identity_registry,
    validate_repo_bound_coordination_records,
)
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, validate


CONFORMANCE_SCHEMA_ID = (
    "artifact-memory/coordination-repo-identity-conformance-receipt/v0"
)
PROJECT_A = "11111111-1111-4111-8111-111111111111"
PROJECT_B = "22222222-2222-4222-8222-222222222222"
UNKNOWN_PROJECT = "99999999-9999-4999-8999-999999999999"


def _records(fixtures: Path) -> list[dict[str, Any]]:
    label = deepcopy(load_json(fixtures / "coordination" / "access-label.json"))
    label["projectNames"] = [
        {"projectId": PROJECT_A, "projectName": "synthetic-service"},
        {"projectId": PROJECT_B, "projectName": "synthetic-service"},
    ]
    for field in label["may"]:
        label["may"][field] = [PROJECT_A, PROJECT_B]
    label["mayNot"]["readProjects"] = []

    tasks = []
    for ordinal, project_id in enumerate((PROJECT_A, PROJECT_B)):
        task = deepcopy(load_json(fixtures / "coordination" / "task-open.json"))
        task_id = f"task_01J0000000000000000000000{ordinal}"
        task["taskId"] = task_id
        task["record_id"] = (
            f"record://coordination/{task['originId']}/task/{task_id}"
        )
        task["projectId"] = project_id
        task["projectName"] = "synthetic-service"
        task["title"] = "Prove same-name repository identity"
        task["accessLabelRef"] = {
            "record_id": label["record_id"],
            "revision_digest": revision_digest(label),
        }
        tasks.append(task)
    return [label, *tasks]


def _unknown_project_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    changed = deepcopy(records)
    label = changed[0]
    label["projectNames"][0]["projectId"] = UNKNOWN_PROJECT
    for field in label["may"]:
        label["may"][field][0] = UNKNOWN_PROJECT
    changed[1]["projectId"] = UNKNOWN_PROJECT
    label_digest = revision_digest(label)
    for task in changed[1:]:
        task["accessLabelRef"]["revision_digest"] = label_digest
    return changed


def run(fixtures: Path, fixture: Path) -> dict[str, Any]:
    records = _records(fixtures)
    record_digests_before = sorted(revision_digest(record) for record in records)
    with tempfile.TemporaryDirectory() as temporary:
        repo_root = Path(temporary) / "repositories"
        shutil.copytree(fixture / "repositories", repo_root)
        repo_roots = [repo_root / "alpha", repo_root / "beta"]

        registry = load_repo_identity_registry(repo_roots)
        result = validate_repo_bound_coordination_records(records, repo_roots)
        if result["known_project_count"] != 2:
            raise RuntimeError("same-name repository identities did not remain distinct")
        same_name_coexists = len(set(registry["human_names"])) == 1

        try:
            validate_repo_bound_coordination_records(
                _unknown_project_records(records), repo_roots
            )
        except ValidationFailure as exc:
            unknown_project_code = exc.code
        else:
            raise RuntimeError("unknown project UUID unexpectedly validated")
        if unknown_project_code != "coordination-project-unknown":
            raise RuntimeError("unknown project UUID returned the wrong diagnostic")

        alpha_manifest = repo_roots[0] / ".agent-memory" / "repo.json"
        renamed = load_json(alpha_manifest)
        renamed["humanName"] = "renamed-synthetic-service"
        alpha_manifest.write_text(
            json.dumps(renamed, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        validate_repo_bound_coordination_records(records, repo_roots)
        record_digests_after = sorted(revision_digest(record) for record in records)

    receipt = receipt_with_digest(
        CONFORMANCE_SCHEMA_ID,
        "coordination-repo-identity-conformance-receipt://sha-256/",
        {
            "outcome": "passed",
            "manifest_count": result["repo_manifest_count"],
            "unique_project_count": result["known_project_count"],
            "same_human_name_coexists": same_name_coexists,
            "unknown_project_code": unknown_project_code,
            "record_digest_count": len(record_digests_before),
            "record_digests_unchanged_after_human_name_rename": (
                record_digests_before == record_digests_after
            ),
            "authority_boundary": (
                "repository identity is informational provenance and grants no "
                "execution, disclosure, authorization, or trust"
            ),
        },
    )
    validate(
        receipt,
        load_schema(
            "core",
            "coordination-repo-identity-conformance-receipt.v0.schema.json",
        ),
    )
    return receipt


def render_coordination_repo_identity_conformance_receipt(
    receipt: dict[str, Any],
) -> str:
    return (
        "# Coordination repository identity conformance receipt\n\n"
        f"- Outcome: `{receipt['outcome']}`\n"
        f"- Repository manifests: `{receipt['manifest_count']}`\n"
        f"- Unique project UUIDs: `{receipt['unique_project_count']}`\n"
        f"- Same human name coexists: `{str(receipt['same_human_name_coexists']).lower()}`\n"
        f"- Unknown-project diagnostic: `{receipt['unknown_project_code']}`\n"
        f"- Record digests checked: `{receipt['record_digest_count']}`\n"
        "- Record digests unchanged after human-name rename: "
        f"`{str(receipt['record_digests_unchanged_after_human_name_rename']).lower()}`\n"
        f"- Receipt: `{receipt['receipt_id']}`\n\n"
        f"Authority boundary: {receipt['authority_boundary']}.\n"
    )
