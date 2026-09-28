"""Hub-authoritative pickup through the existing verified projection seam.

A verified claim is coordination evidence only. No tool or agent is launched.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import time
from typing import Any
from urllib.request import ProxyHandler, build_opener

from .coordination import (
    AUTHORITY_BOUNDARY, TASK_PACKET_SCHEMA_ID, current_coordination_task_leaves,
    revision_digest,
)
from .coordination_http import (
    _NoRedirect, _binding, _endpoint, _post_json, _require_bearer, sync_http,
)
from .coordination_sync import SyncFailure, _advisory_lock, authorized_coordination_snapshot
from .schema_resources import core_schemas
from .validator import ValidationFailure, validate

CLAIM_ENDPOINT = "/api/agent/coordination/claims"


def _validate_ref(reference: Any) -> None:
    schema = core_schemas()[TASK_PACKET_SCHEMA_ID]["properties"]["claims"]["items"]["properties"]["taskRef"]
    try:
        validate(reference, schema)
    except ValidationFailure:
        raise SyncFailure("claim-task-ref-invalid", "claim requires one exact TaskPacket reference") from None


def _task(snapshot: dict, requested: dict, project: str, binding: dict) -> dict:
    if any(snapshot["receipt"][name] != value for name, value in binding.items()):
        raise SyncFailure("claim-binding-mismatch", "authorized snapshot does not match configured bindings")
    candidates = [record for record in snapshot["records"]
                  if record["schema_id"] == TASK_PACKET_SCHEMA_ID]
    leaves = current_coordination_task_leaves(candidates)
    leaf = next((record for record in leaves if record["record_id"] == requested["record_id"]), None)
    original = next((record for record in candidates if record["record_id"] == requested["record_id"]
                     and revision_digest(record) == requested["revision_digest"]), None)
    if leaf is None or original is None or original["status"] != "open":
        raise SyncFailure("claim-task-not-current", "exact open task is not in authorized current history")
    if (leaf["projectId"] != project or original["projectId"] != project
            or leaf["assignedWriter"] != binding["principal_id"]
            or original["assignedWriter"] != binding["principal_id"]
            or leaf["accessLabelRef"] != binding["access_label_ref"]
            or original["accessLabelRef"] != binding["access_label_ref"]):
        raise SyncFailure("claim-binding-mismatch", "task does not match project, principal and label bindings")
    if leaf["status"] == "claimed":
        claim = leaf["claims"][0]
        if (leaf["predecessor"] != requested or claim["taskRef"] != requested
                or claim["principalId"] != binding["principal_id"]):
            raise SyncFailure("claim-conflict", "task is already claimed under another binding")
    elif revision_digest(leaf) != requested["revision_digest"]:
        raise SyncFailure("claim-task-not-current", "requested task revision is stale")
    return leaf


def claim_http(vault: Path, hub: str, *, task_ref: dict, project_id: str,
               bearer: str | None, expected_hub_id: str | None,
               expected_principal_id: str | None,
               expected_access_label_ref: dict | None) -> dict[str, Any]:
    """Claim one explicit reference, then verify its hub-minted successor.

    This function never retries a claim automatically. An interrupted call may
    have committed at the hub; a later explicit call must use the same open ref.
    """
    url = _endpoint(hub, CLAIM_ENDPOINT)
    bearer = _require_bearer(bearer)
    binding = _binding(expected_hub_id, expected_principal_id, expected_access_label_ref)
    _validate_ref(task_ref)
    try:
        validate(project_id, core_schemas()[TASK_PACKET_SCHEMA_ID]["properties"]["projectId"])
    except ValidationFailure:
        raise SyncFailure("claim-project-invalid", "claim requires a project UUID") from None
    requested = deepcopy(task_ref)
    sync_args = dict(bearer=bearer, expected_hub_id=binding["hub_id"],
                     expected_principal_id=binding["principal_id"],
                     expected_access_label_ref=binding["access_label_ref"], phase="pull")
    with _advisory_lock(vault, "http-task-claim", busy_code="claim-local-busy",
                       busy_message="one task pickup is already in flight for this vault"):
        sync_http(vault, hub, **sync_args)
        with authorized_coordination_snapshot(vault) as snapshot:
            _task(snapshot, requested, project_id, binding)
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        status, response = _post_json(opener, url, bearer, {"taskRef": requested},
                                     time.monotonic() + 20, statuses=(200, 201),
                                     response_limit=8192, operation="claim")
        if (not isinstance(response, dict) or set(response) != {"taskRef", "replay"}
                or type(response["replay"]) is not bool
                or response["replay"] != (status == 200)):
            raise SyncFailure("claim-response-invalid", "claim outcome is unverified; retry only the same exact open reference")
        try:
            _validate_ref(response["taskRef"])
            if response["taskRef"]["record_id"] != requested["record_id"]:
                raise SyncFailure("claim-response-invalid", "claim response names another task")
            sync_http(vault, hub, **sync_args)
            with authorized_coordination_snapshot(vault) as snapshot:
                leaf = _task(snapshot, requested, project_id, binding)
                successor = {"record_id": leaf["record_id"], "revision_digest": revision_digest(leaf)}
                if leaf["status"] != "claimed" or successor != response["taskRef"]:
                    raise SyncFailure("claim-result-unverified", "claimed successor is not the authorized current leaf")
                return {
                    "outcome": "verified", "phase": "claim", "requested_task_ref": requested,
                    "task_ref": successor, "claim_id": leaf["claims"][0]["claimId"],
                    "project_id": project_id, "replay": response["replay"], **binding,
                    "sync_receipt_id": snapshot["receipt"]["receipt_id"],
                    "authority_boundary": AUTHORITY_BOUNDARY,
                }
        except (ValidationFailure, OSError, RecursionError):
            raise SyncFailure("claim-result-unverified", "claim may be admitted; retry only the same exact open reference") from None
