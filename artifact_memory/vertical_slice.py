"""Synthetic validate-to-restore proof for the first TraceMap evidence binding."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from .backup import create_backup, restore_isolated
from .canonical import canonical_bytes
from .context import build_selection_policy, export_context
from .projection import project_records, related_records
from .scan import scan_path, verify_path
from .schema_resources import load_schema
from .tracemap_adapter import FACT_SCHEMA_ID, bind_trace_map_evidence
from .validator import validate
from .vault import register_bytes


CLAIM_RECORD_ID = "record://synthetic/orders-status-static-read"
SOURCE_ARTIFACT_ID = "artifact://synthetic/orders-source"


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _register_tree(vault: Path, root: Path) -> list[dict[str, Any]]:
    receipts = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            receipt = register_bytes(vault, path.read_bytes())
            if receipt["outcome"] not in {"registered", "duplicate"}:
                raise RuntimeError("synthetic source content registration failed")
            receipts.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "receipt": receipt,
                }
            )
    return receipts


def _external_evidence(binding: dict[str, Any], provider_record_id: str) -> dict[str, Any]:
    selected = next(
        item
        for item in binding["selected_provider_records"]
        if item["provider_record_id"] == provider_record_id
    )
    return {
        "provider_id": "tracemap",
        "provider_schema_id": FACT_SCHEMA_ID,
        "provider_record_id": provider_record_id,
        "binding_ref": binding["binding_id"],
        "evidence_packet_ref": binding["evidence_packet_ref"],
        "adapter_receipt_digest": binding["receipt"]["deterministic_body_digest"],
        "integrity_state": binding["integrity_state"],
        "rule_id": selected["rule_id"],
        "evidence_tier": selected["evidence_tier"],
        "coverage": selected["coverage"],
        "limitations": selected["limitations"],
    }


def run_vertical_slice(
    source_dir: Path,
    packet_dir: Path,
    output_dir: Path,
    *,
    expected_repo: str,
    expected_commit: str,
    tool_source_commit: str,
    configuration_digest: str,
    rule_catalog_digest: str,
    selected_declaration_fact_id: str,
    selected_access_fact_id: str,
    passphrase: str,
) -> dict[str, Any]:
    """Exercise the synthetic slice without granting authority or invoking a provider."""
    source_dir = source_dir.resolve()
    output_dir = output_dir.resolve()
    if (
        output_dir.exists()
        or output_dir == source_dir
        or output_dir.is_relative_to(source_dir)
        or source_dir.is_relative_to(output_dir)
    ):
        raise ValueError("output must be a new location that does not overlap the source")
    output_dir.mkdir(parents=True, exist_ok=True)
    vault = output_dir / "vault"
    canonical = output_dir / "canonical"
    projection = output_dir / "projection"
    artifacts = output_dir / "artifacts"

    source_manifest, scan_receipt = scan_path(source_dir)
    if scan_receipt["outcome"] != "complete":
        raise RuntimeError("synthetic source scan was not complete")
    if verify_path(source_dir, source_manifest)["outcome"] != "verified":
        raise RuntimeError("synthetic source tree did not verify")
    source_registrations = _register_tree(vault, source_dir)
    manifest_registration = register_bytes(
        vault,
        canonical_bytes(source_manifest),
        "application/vnd.artifact-memory.manifest+json",
    )
    if manifest_registration["outcome"] not in {"registered", "duplicate"}:
        raise RuntimeError("synthetic source manifest registration failed")
    source_version_ref = manifest_registration["artifact_version_ref"]
    source_version = {
        "schema_id": "artifact-memory/artifact-version/v1",
        "artifact_id": SOURCE_ARTIFACT_ID,
        "version_id": source_version_ref,
        "content_refs": sorted(
            [manifest_registration["content_ref"]]
            + [item["receipt"]["content_ref"] for item in source_registrations]
        ),
        "lifecycle": "accepted",
        "extensions": {
            "artifact-memory/source-tree/v1": {
                "manifest_ref": source_manifest["manifest_id"],
                "tree_digest": source_manifest["tree_digest"],
                "git_commit": expected_commit,
            }
        },
    }
    validate(source_version, load_schema("core", "artifact-version.v1.schema.json"))
    _write_json(canonical / "source-version.json", source_version)
    _write_json(artifacts / "source-manifest.json", source_manifest)

    selected_ids = [selected_declaration_fact_id, selected_access_fact_id]
    binding = bind_trace_map_evidence(
        source_version_ref,
        packet_dir,
        expected_repo,
        expected_commit,
        selected_ids,
        tool_source_commit=tool_source_commit,
        configuration_digest=configuration_digest,
        rule_catalog_digest=rule_catalog_digest,
    )
    validate(binding, load_schema("adapters", "tracemap-evidence-binding.v1.schema.json"))
    packet_registrations = _register_tree(vault, packet_dir)
    registered_by_path = {
        item["path"]: item["receipt"]["digest"] for item in packet_registrations
    }
    bound_content = {
        item["name"]: item["digest"] for item in binding["content_objects"]
    }
    if {
        name: registered_by_path.get(name) for name in bound_content
    } != bound_content:
        raise RuntimeError("TraceMap packet registration did not preserve exact content")
    _write_json(artifacts / "tracemap-binding.json", binding)

    claim = {
        "schema_id": "artifact-memory/knowledge-record/v1",
        "record_id": CLAIM_RECORD_ID,
        "record_type": "claim",
        "lifecycle": "accepted",
        "meaning": {
            "summary": "Static evidence at the pinned SyntheticOrders source version identifies a read of Order.Status.",
            "labels": ["synthetic", "static-evidence", "tracemap"],
        },
        "artifact_refs": [SOURCE_ARTIFACT_ID],
        "provenance": [
            {"kind": "observation", "source_ref": selected_access_fact_id}
        ],
        "relationships": [
            {
                "type": "supported-by-external-evidence",
                "target_ref": binding["binding_id"],
            }
        ],
        "sensitivity": "public",
    }
    validate(claim, load_schema("core", "knowledge-record.v1.schema.json"))
    _write_json(canonical / "claim.json", claim)
    projection_receipt = project_records([canonical / "claim.json"], projection)
    relationships = related_records(projection / "records.sqlite", CLAIM_RECORD_ID)
    if relationships != [
        {
            "type": "supported-by-external-evidence",
            "target_ref": binding["binding_id"],
        }
    ]:
        raise RuntimeError("generated relationship index did not resolve the evidence binding")

    external_evidence = _external_evidence(binding, selected_access_fact_id)
    context = export_context(
        [claim],
        [external_evidence],
        allowed_sensitivity="public",
        **build_selection_policy(
            [CLAIM_RECORD_ID],
            selected_at="2026-07-30T00:00:00Z",
            freshness_basis="synthetic-fixture-source-version",
            authorized_evidence=[("tracemap", selected_access_fact_id)],
        ),
    )
    validate(context, load_schema("core", "context-pack.v2.schema.json"))
    serialized_context = json.dumps(context, sort_keys=True)
    for forbidden in ("Order.cs", "analyzer.log", "filePath", "sourceSymbol", "targetSymbol"):
        if forbidden in serialized_context:
            raise RuntimeError("context pack disclosed excluded provider or source detail")
    _write_json(artifacts / "context-pack.json", context)

    backup_dir = output_dir / "backup"
    backup_receipt = create_backup(
        {
            "source": source_dir,
            "vault": vault,
            "canonical": canonical,
            "artifacts": artifacts,
            "projection": projection,
            "tracemap-packet": packet_dir,
        },
        backup_dir,
        passphrase,
        endpoint_ref="endpoint://synthetic/isolated-proof",
        generation_ref="vertical-slice-0001",
    )
    if backup_receipt["outcome"] != "created":
        raise RuntimeError("synthetic backup failed")
    restore_dir = output_dir / "isolated-restore"
    restore_receipt = restore_isolated(
        backup_dir / "backup.enc",
        restore_dir,
        passphrase,
        backup_receipt["backup_ref"],
        backup_receipt["backup_digest"],
        backup_receipt["source_manifest_digest"],
    )
    if restore_receipt["outcome"] != "restored":
        raise RuntimeError("synthetic isolated restore failed")
    if verify_path(restore_dir / "source", source_manifest)["outcome"] != "verified":
        raise RuntimeError("restored source tree did not verify")

    restored_binding = bind_trace_map_evidence(
        source_version_ref,
        restore_dir / "tracemap-packet",
        expected_repo,
        expected_commit,
        selected_ids,
        tool_source_commit=tool_source_commit,
        configuration_digest=configuration_digest,
        rule_catalog_digest=rule_catalog_digest,
    )
    if restored_binding != binding:
        raise RuntimeError("restored TraceMap evidence binding changed")
    rebuilt = output_dir / "rebuilt-projection"
    rebuilt_receipt = project_records([restore_dir / "canonical" / "claim.json"], rebuilt)
    if rebuilt_receipt != projection_receipt:
        raise RuntimeError("restored projection did not rebuild equivalently")
    if (rebuilt / "records.ndjson").read_bytes() != (
        restore_dir / "projection" / "records.ndjson"
    ).read_bytes():
        raise RuntimeError("restored canonical records produced different NDJSON")
    restored_context = json.loads(
        (restore_dir / "artifacts" / "context-pack.json").read_text(encoding="utf-8")
    )
    validate(restored_context, load_schema("core", "context-pack.v2.schema.json"))
    regenerated_context = export_context(
        [claim],
        [_external_evidence(restored_binding, selected_access_fact_id)],
        allowed_sensitivity="public",
        **build_selection_policy(
            [CLAIM_RECORD_ID],
            selected_at="2026-07-30T00:00:00Z",
            freshness_basis="synthetic-fixture-source-version",
            authorized_evidence=[("tracemap", selected_access_fact_id)],
        ),
    )
    if regenerated_context != restored_context:
        raise RuntimeError("restored context pack did not revalidate deterministically")
    with sqlite3.connect(rebuilt / "records.sqlite") as connection:
        relationship_count = connection.execute(
            "select count(*) from relationships where source_record_id = ? and target_ref = ?",
            (CLAIM_RECORD_ID, binding["binding_id"]),
        ).fetchone()[0]
    if relationship_count != 1:
        raise RuntimeError("restored claim no longer resolves to external evidence")

    stages = [
        "validate-source",
        "register-source",
        "validate-and-register-tracemap-packet",
        "bind-selected-facts",
        "record-narrow-claim",
        "build-generated-index",
        "export-bounded-context",
        "create-encrypted-backup",
        "restore-isolated",
        "rebuild-and-revalidate",
    ]
    receipt_body = {
        "outcome": "complete",
        "synthetic": True,
        "stages": [{"name": name, "outcome": "complete"} for name in stages],
        "source_version_ref": source_version_ref,
        "source_manifest_ref": source_manifest["manifest_id"],
        "source_tree_digest": source_manifest["tree_digest"],
        "source_git_commit": expected_commit,
        "provider_contract_anchor": binding["provider"]["contract_anchor"],
        "provider_tool_source_commit": tool_source_commit,
        "selected_provider_record_ids": sorted(selected_ids),
        "binding_id": binding["binding_id"],
        "evidence_packet_ref": binding["evidence_packet_ref"],
        "integrity_state": binding["integrity_state"],
        "claim_record_id": CLAIM_RECORD_ID,
        "projection_source_digest": projection_receipt["source_record_set_digest"],
        "context_pack_id": context["pack_id"],
        "backup_outcome": backup_receipt["outcome"],
        "restore_outcome": restore_receipt["outcome"],
        "authority_boundary": "informational evidence only; no execution, routing, disclosure, approval, or mutation authority",
        "limitations": [
            "synthetic fixture evidence does not establish runtime behavior or correctness",
            "unsigned provider evidence does not establish issuer authenticity",
        ],
    }
    receipt = {
        "schema_id": "artifact-memory/tracemap-vertical-slice-receipt/v1",
        "receipt_id": "vertical-slice-receipt://"
        + hashlib.sha256(canonical_bytes(receipt_body)).hexdigest(),
        **receipt_body,
    }
    validate(
        receipt,
        load_schema("adapters", "tracemap-vertical-slice-receipt.v1.schema.json"),
    )
    _write_json(output_dir / "vertical-slice-receipt.json", receipt)
    return receipt
