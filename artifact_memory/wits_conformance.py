"""Synthetic #41 WITS boundary proof ending before HACP work creation."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Callable

from .backup import create_backup, restore_isolated
from .canonical import canonical_bytes
from .context import build_selection_policy, export_context
from .independent_context_reader import recall_context
from .projection import logical_projection_snapshot, project_records
from .schema_resources import load_schema
from .validator import validate
from .vault import register_bytes
from .wits_adapter import AUTHORITY_BOUNDARY, bind_projection_v2, build_projection_request


WITS_RECORD_ID = "record://synthetic/wits-projection-reference"
WITS_ARTIFACT_ID = "artifact://synthetic/wits-projection"
WITS_ARTIFACT_VERSION_ID = "artifact-version://synthetic/wits-projection/1"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _trace_evidence(binding: dict[str, Any], provider_record_id: str) -> dict[str, Any]:
    try:
        selected = next(
            item for item in binding["selected_provider_records"]
            if item["provider_record_id"] == provider_record_id
        )
    except StopIteration as error:
        raise RuntimeError("claim-supporting TraceMap evidence is unavailable") from error
    return {
        "provider_id": "tracemap",
        "provider_schema_id": binding["provider"]["record_schema_ids"][-1],
        "provider_record_id": selected["provider_record_id"],
        "binding_ref": binding["binding_id"],
        "evidence_packet_ref": binding["evidence_packet_ref"],
        "adapter_receipt_digest": binding["receipt"]["deterministic_body_digest"],
        "integrity_state": binding["integrity_state"],
        "rule_id": selected["rule_id"],
        "evidence_tier": selected["evidence_tier"],
        "coverage": selected["coverage"],
        "limitations": selected["limitations"],
    }


def run_wits_conformance(
    base_proof: Path,
    output_dir: Path,
    passphrase: str,
    provider: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Extend the accepted TraceMap proof with an opaque WITS projection reference."""
    if output_dir.exists():
        raise ValueError("output must be new")
    canonical = output_dir / "canonical"
    artifacts = output_dir / "artifacts"
    vault = output_dir / "vault"
    shutil.copytree(base_proof / "canonical", canonical)
    shutil.copytree(base_proof / "artifacts", artifacts)
    shutil.copytree(base_proof / "vault", vault)
    claim = _load(canonical / "claim.json")
    trace_binding = _load(artifacts / "tracemap-binding.json")

    request = build_projection_request(
        [claim], "owner-meaning", external_evidence_refs=[trace_binding["binding_id"]],
    )
    provider_response = provider(request)
    projection, admission = bind_projection_v2(
        [claim], "owner-meaning", provider_response, True,
        external_evidence_refs=[trace_binding["binding_id"]],
    )
    if projection is None or admission["outcome"] != "admitted":
        raise RuntimeError("synthetic WITS projection was not admitted")
    validate(projection, load_schema("adapters", "wits-projection.v2.schema.json"))
    validate(admission, load_schema("adapters", "wits-admission-receipt.v2.schema.json"))
    projection_bytes = canonical_bytes(projection)
    registration = register_bytes(vault, projection_bytes, "application/vnd.artifact-memory.wits-projection+json")
    if registration["outcome"] not in {"registered", "duplicate"}:
        raise RuntimeError("WITS projection content registration failed")
    _write(artifacts / "wits-projection.json", projection)
    _write(artifacts / "wits-admission-receipt.json", admission)

    projection_version = {
        "schema_id": "artifact-memory/artifact-version/v1",
        "artifact_id": WITS_ARTIFACT_ID,
        "version_id": WITS_ARTIFACT_VERSION_ID,
        "content_refs": [registration["content_ref"]],
        "lifecycle": "accepted",
    }
    validate(projection_version, load_schema("core", "artifact-version.v1.schema.json"))
    _write(canonical / "wits-projection-version.json", projection_version)

    projection_record = {
        "schema_id": "artifact-memory/knowledge-record/v1",
        "record_id": WITS_RECORD_ID,
        "record_type": "note",
        "lifecycle": "accepted",
        "meaning": {
            "summary": "WITS supplied an opaque owner-meaning projection for the exact synthetic claim revision.",
            "labels": ["informational", "synthetic", "wits-projection"],
        },
        "artifact_refs": [WITS_ARTIFACT_ID],
        "provenance": [{"kind": "derivation", "source_ref": projection["projection_id"]}],
        "relationships": [{"type": "related-to", "target_ref": claim["record_id"]}],
        "sensitivity": "public",
    }
    validate(projection_record, load_schema("core", "knowledge-record.v1.schema.json"))
    _write(canonical / "wits-projection-reference.json", projection_record)

    generated = output_dir / "projection"
    paths = [canonical / "claim.json", canonical / "wits-projection-reference.json"]
    projection_receipt = project_records(paths, generated)
    snapshot = logical_projection_snapshot(generated / "records.sqlite")
    evidence = _trace_evidence(trace_binding, claim["provenance"][0]["source_ref"])
    context = export_context(
        [claim, projection_record], [evidence], allowed_sensitivity="public",
        **build_selection_policy(
            [claim["record_id"], projection_record["record_id"]],
            selected_at="2026-08-01T00:00:00Z",
            freshness_basis="synthetic-wits-exact-revision",
            authorized_evidence=[("tracemap", evidence["provider_record_id"])],
        ),
    )
    validate(context, load_schema("core", "context-pack.v2.schema.json"))
    recall = recall_context(canonical_bytes(context))
    if WITS_ARTIFACT_ID not in recall["artifact_refs"] or recall["execution_authority"] != "absent":
        raise RuntimeError("fresh reader lost the WITS reference or gained authority")
    _write(artifacts / "context-pack.json", context)
    _write(artifacts / "context-recall-receipt.json", recall)

    backup = create_backup(
        {
            "canonical": canonical,
            "artifacts": artifacts,
            "projection": generated,
            "source": base_proof / "isolated-restore" / "source",
            "tracemap-packet": base_proof / "isolated-restore" / "tracemap-packet",
            "vault": vault,
        },
        output_dir / "backup", passphrase,
        endpoint_ref="endpoint://synthetic/wits-isolated-proof",
        generation_ref="wits-slice-0001",
    )
    restored = output_dir / "isolated-restore"
    restore = restore_isolated(
        output_dir / "backup" / "backup.enc", restored, passphrase,
        backup["backup_ref"], backup["backup_digest"],
        backup["source_manifest_digest"],
    )
    if backup["outcome"] != "created" or restore["outcome"] != "restored":
        raise RuntimeError("WITS fixture backup or isolated restore failed")
    restored_projection = _load(restored / "artifacts" / "wits-projection.json")
    validate(restored_projection, load_schema("adapters", "wits-projection.v2.schema.json"))
    restored_version = _load(restored / "canonical" / "wits-projection-version.json")
    validate(restored_version, load_schema("core", "artifact-version.v1.schema.json"))
    if registration["content_ref"] not in restored_version["content_refs"]:
        raise RuntimeError("restored artifact version lost its registered content binding")
    shutil.rmtree(restored / "projection")
    rebuilt = output_dir / "rebuilt-projection"
    rebuilt_receipt = project_records(
        [restored / "canonical" / "claim.json", restored / "canonical" / "wits-projection-reference.json"],
        rebuilt,
    )
    if rebuilt_receipt != projection_receipt or logical_projection_snapshot(rebuilt / "records.sqlite") != snapshot:
        raise RuntimeError("canonical records did not rebuild the generated index equivalently")
    restored_context = _load(restored / "artifacts" / "context-pack.json")
    if recall_context(canonical_bytes(restored_context)) != recall:
        raise RuntimeError("restored context did not recall equivalently")

    stages = [
        "register-source-and-tracemap-evidence", "bind-exact-wits-projection",
        "export-informational-context", "fresh-reader-recall", "create-encrypted-backup",
        "restore-isolated", "rebuild-generated-index", "stop-before-hacp-task-creation",
    ]
    body = {
        "outcome": "complete",
        "synthetic": True,
        "stages": [{"name": stage, "outcome": "complete"} for stage in stages],
        "source_record_refs": projection["source_record_refs"],
        "tracemap_binding_ref": trace_binding["binding_id"],
        "wits_binding_ref": projection["projection_id"],
        "wits_projection_ref": projection["wits_projection_ref"],
        "wits_artifact_version_ref": WITS_ARTIFACT_VERSION_ID,
        "wits_contract_commit": projection["provider_contract"]["commit"],
        "wits_license": projection["provider_contract"]["license"],
        "context_pack_id": context["pack_id"],
        "projection_source_digest": projection_receipt["source_record_set_digest"],
        "registered_projection_content_ref": registration["content_ref"],
        "backup_outcome": backup["outcome"],
        "restore_outcome": restore["outcome"],
        "fixture_end": "before_hacp_task_creation_or_execution",
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": [
            "synthetic WITS response is an independently supplied opaque fixture, not a live WITS interoperability claim",
            "Artifact Memory does not interpret WITS owner meaning or readiness",
        ],
    }
    receipt = {
        "schema_id": "artifact-memory/wits-conformance-receipt/v1",
        "receipt_id": "wits-conformance-receipt://" + hashlib.sha256(canonical_bytes(body)).hexdigest(),
        **body,
    }
    validate(receipt, load_schema("adapters", "wits-conformance-receipt.v1.schema.json"))
    _write(output_dir / "wits-conformance-receipt.json", receipt)
    return receipt
