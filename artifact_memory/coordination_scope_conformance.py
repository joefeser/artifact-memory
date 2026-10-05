"""Synthetic AM-7 proof for count-only scoped sync and context export."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .canonical import canonical_bytes, receipt_with_digest
from .coordination import ACCESS_LABEL_SCHEMA_ID, revision_digest
from .coordination_context import (
    build_coordination_context_pack,
    validate_coordination_context_pack,
)
from .coordination_sync import (
    append_local_coordination_record,
    apply_pull_response,
    build_pull_response,
    configure_local_hub,
    coordination_pair_count,
    pull,
    store_coordination_record,
)
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, validate


CONFORMANCE_SCHEMA_ID = (
    "artifact-memory/coordination-access-scope-conformance-receipt/v0"
)
PROJECT_A = "11111111-1111-4111-8111-111111111111"
PROJECT_B = "22222222-2222-4222-8222-222222222222"
PROJECT_B_NAME = "sample-analytics"
PRINCIPAL_ID = "coordination-principal://synthetic/scoped-client"
SESSION_ID = "coordination-session://synthetic/scoped-client"
HUB_ID = "coordination-hub://synthetic/access-scope"
AUTHORITY_BOUNDARY = (
    "access-scope conformance evidence is informational only and grants no execution, "
    "mutation, routing, disclosure, credential, spending, deployment, approval, or merge authority"
)


def _label(fixtures: Path, *, broad: bool) -> dict[str, Any]:
    label = deepcopy(load_json(fixtures / "coordination" / "access-label.json"))
    label["may"]["readProjects"] = [PROJECT_A, PROJECT_B] if broad else [PROJECT_A]
    label["mayNot"]["readProjects"] = [] if broad else [PROJECT_B]
    return label


def _task(
    fixtures: Path,
    label: dict[str, Any],
    *,
    project_id: str,
    project_name: str,
    origin_id: str,
    task_id: str,
    title: str,
) -> dict[str, Any]:
    task = deepcopy(load_json(fixtures / "coordination" / "task-open.json"))
    task["originId"] = origin_id
    task["taskId"] = task_id
    task["record_id"] = f"record://coordination/{origin_id}/task/{task_id}"
    task["projectId"] = project_id
    task["projectName"] = project_name
    task["title"] = title
    task["accessLabelRef"] = {
        "record_id": label["record_id"],
        "revision_digest": revision_digest(label),
    }
    return task


def _binding(label: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "session_id": SESSION_ID,
            "principal_id": PRINCIPAL_ID,
            "access_label": label,
        }
    ]


def _failure_code(operation: Any) -> str:
    try:
        operation()
    except ValidationFailure as exc:
        return exc.code
    raise RuntimeError("negative access-scope vector was accepted")


def exercise(fixtures: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    with TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        hub, vault = root / "hub", root / "vault"
        broad = _label(fixtures, broad=True)
        narrow = _label(fixtures, broad=False)
        task_a = _task(
            fixtures,
            broad,
            project_id=PROJECT_A,
            project_name="sample-service",
            origin_id="33333333-3333-4333-8333-333333333333",
            task_id="task_01J00000000000000000000000",
            title="Synthetic allowed coordination task",
        )
        task_b = _task(
            fixtures,
            broad,
            project_id=PROJECT_B,
            project_name=PROJECT_B_NAME,
            origin_id="44444444-4444-4444-8444-444444444444",
            task_id="task_01J00000000000000000000001",
            title="Synthetic denied coordination task",
        )

        configure_local_hub(
            hub,
            hub_id=HUB_ID,
            scope_generation=1,
            bindings=_binding(broad),
        )
        store_coordination_record(hub, task_a)
        store_coordination_record(hub, task_b)
        first = pull(
            vault,
            hub,
            session_id=SESSION_ID,
            completed_at="2026-09-27T18:00:00Z",
        )
        prior_count = len(first["authorized_pairs"])

        configure_local_hub(
            hub,
            hub_id=HUB_ID,
            scope_generation=2,
            bindings=_binding(narrow),
        )
        response = build_pull_response(
            hub,
            session_id=SESSION_ID,
            completed_at="2026-09-27T18:01:00Z",
        )
        response_bytes = canonical_bytes(response)
        forbidden = (
            PROJECT_B.encode("utf-8"),
            PROJECT_B_NAME.encode("utf-8"),
            task_b["record_id"].encode("utf-8"),
            task_b["title"].encode("utf-8"),
        )
        denied_in_response = any(value in response_bytes for value in forbidden)
        response_records = [
            record for page in response["record_pages"] for record in page
        ]
        response_label_count = sum(
            record.get("schema_id") == ACCESS_LABEL_SCHEMA_ID
            for record in response_records
        )
        apply_pull_response(vault, response)

        context_pack = build_coordination_context_pack(vault)
        validate_coordination_context_pack(context_pack)
        context_bytes = canonical_bytes(context_pack)
        denied_in_context = any(value in context_bytes for value in forbidden)
        context_label_count = sum(
            record.get("schema_id") == ACCESS_LABEL_SCHEMA_ID
            for record in context_pack["records"]
        )
        current_count = context_pack["record_count"]
        canonical_count = coordination_pair_count(vault)

        untrusted_vault = root / "untrusted-vault"
        append_local_coordination_record(untrusted_vault, task_a)
        missing_policy_code = _failure_code(
            lambda: build_coordination_context_pack(untrusted_vault)
        )

        duplicate = load_json(
            fixtures / "coordination" / "invalid" / "access-label-duplicate-read.json"
        )
        overlap = load_json(
            fixtures / "coordination" / "invalid" / "access-label-overlap.json"
        )
        duplicate_code = _failure_code(
            lambda: configure_local_hub(
                root / "duplicate-hub",
                hub_id="coordination-hub://synthetic/duplicate",
                scope_generation=1,
                bindings=_binding(duplicate),
            )
        )
        overlap_code = _failure_code(
            lambda: configure_local_hub(
                root / "overlap-hub",
                hub_id="coordination-hub://synthetic/overlap",
                scope_generation=1,
                bindings=_binding(overlap),
            )
        )

        invalid_hub = root / "invalid-bound-hub"
        configure_local_hub(
            invalid_hub,
            hub_id="coordination-hub://synthetic/invalid-bound",
            scope_generation=1,
            bindings=_binding(broad),
        )
        invalid_config = load_json(invalid_hub / "hub-config.json")
        invalid_config["bindings"][0]["access_label"] = overlap
        (invalid_hub / "hub-config.json").write_bytes(canonical_bytes(invalid_config))
        invalid_bound_code = _failure_code(
            lambda: pull(
                root / "invalid-bound-vault",
                invalid_hub,
                session_id=SESSION_ID,
                completed_at="2026-09-27T18:02:00Z",
            )
        )

        invalid_context = deepcopy(context_pack)
        invalid_context["records"].append(overlap)
        invalid_label_context_code = _failure_code(
            lambda: validate_coordination_context_pack(invalid_context)
        )
        label_context = deepcopy(context_pack)
        label_context["records"].append(broad)
        label_body_context_code = _failure_code(
            lambda: validate_coordination_context_pack(label_context)
        )

        receipt = receipt_with_digest(
            CONFORMANCE_SCHEMA_ID,
            "coordination-access-scope-conformance-receipt://sha-256/",
            {
                "outcome": "passed",
                "restricted_sync": {
                    "authorized_record_count": len(response_records),
                    "excluded_count": response["receipt"]["excluded_count"],
                    "denied_identity_present": denied_in_response,
                    "full_access_label_body_count": response_label_count,
                },
                "context_pack": {
                    "schema_id": context_pack["schema_id"],
                    "record_count": current_count,
                    "excluded_count": context_pack["sync_observation"][
                        "excluded_count"
                    ],
                    "denied_identity_present": denied_in_context,
                    "full_access_label_body_count": context_label_count,
                    "trusted_policy_receipt_bound": (
                        context_pack["sync_observation"]["receipt_id"]
                        == response["receipt"]["receipt_id"]
                    ),
                },
                "scope_narrowing": {
                    "prior_generation": first["receipt"]["scope_generation"],
                    "current_generation": response["receipt"]["scope_generation"],
                    "prior_authorized_count": prior_count,
                    "current_authorized_count": current_count,
                    "canonical_record_count": canonical_count,
                    "suppressed_record_count": prior_count - current_count,
                    "canonical_history_retained": canonical_count == prior_count,
                    "erasure_claimed": False,
                },
                "negative_codes": {
                    "duplicate_label": duplicate_code,
                    "overlapping_label": overlap_code,
                    "invalid_bound_label_sync": invalid_bound_code,
                    "missing_policy_context": missing_policy_code,
                    "invalid_label_context": invalid_label_context_code,
                    "label_body_context": label_body_context_code,
                },
                "authority_boundary": AUTHORITY_BOUNDARY,
            },
        )
    validate(
        receipt,
        load_schema(
            "core",
            "coordination-access-scope-conformance-receipt.v0.schema.json",
        ),
    )
    return context_pack, receipt


def run(fixtures: Path, fixture: Path) -> dict[str, Any]:
    del fixture
    return exercise(fixtures)[1]


def render_coordination_access_scope_conformance_receipt(
    receipt: dict[str, Any],
) -> str:
    sync = receipt["restricted_sync"]
    context = receipt["context_pack"]
    narrowing = receipt["scope_narrowing"]
    return (
        "# Coordination access-scope conformance receipt\n\n"
        f"- Outcome: `{receipt['outcome']}`\n"
        f"- Restricted sync records: `{sync['authorized_record_count']}`\n"
        f"- Count-only exclusions: `{sync['excluded_count']}`\n"
        f"- Denied identity disclosed: `{str(sync['denied_identity_present']).lower()}`\n"
        f"- Context records: `{context['record_count']}`\n"
        f"- Scope generation: `{narrowing['prior_generation']} -> {narrowing['current_generation']}`\n"
        f"- Canonical history retained: `{str(narrowing['canonical_history_retained']).lower()}`\n"
        f"- Receipt: `{receipt['receipt_id']}`\n\n"
        f"Authority boundary: {receipt['authority_boundary']}.\n"
    )
