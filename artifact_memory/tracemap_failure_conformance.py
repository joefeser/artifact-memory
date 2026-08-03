"""Synthetic conformance proof for every issue #39 adapter outcome."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Callable

from .canonical import receipt_with_digest
from .schema_resources import load_schema
from .tracemap_adapter import (
    AUTHORITY_BOUNDARY,
    DECLARED_OUTCOMES,
    TRACE_MAP_CONTRACT_ANCHOR,
    bind_trace_map_evidence_receipted,
)
from .validator import ValidationFailure, validate


SOURCE_REF = "artifact-version://synthetic/orders/1"
REPOSITORY = "SyntheticOrders"
SOURCE_COMMIT = "1111111111111111111111111111111111111111"
TOOL_COMMIT = "2222222222222222222222222222222222222222"
CONFIGURATION_DIGEST = "sha-256:" + "3" * 64
RULE_CATALOG_DIGEST = "sha-256:" + "4" * 64


class _ExplodingPacketPath:
    """Synthetic non-Path used only to prove unexpected faults are receipted."""

    def __fspath__(self) -> str:
        raise RuntimeError("synthetic unexpected packet fault")


def _materialize_packet(fixture: Path, destination: Path) -> Path:
    packet = destination / "packet"
    shutil.copytree(fixture, packet)
    (packet / "logs").mkdir(exist_ok=True)
    (packet / "logs" / "analyzer.log").write_text(
        "synthetic TraceMap analyzer log\n",
        encoding="utf-8",
    )
    connection = sqlite3.connect(packet / "index.sqlite")
    try:
        connection.executescript((packet / "index.sqlite.sql").read_text(encoding="utf-8"))
        manifest = json.loads((packet / "scan-manifest.json").read_text(encoding="utf-8"))
        facts = [
            json.loads(line)
            for line in (packet / "facts.ndjson").read_text(encoding="utf-8").splitlines()
        ]
        connection.execute(
            "insert into scan_manifest values (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                manifest["scanId"],
                manifest["repoName"],
                manifest["commitSha"],
                manifest["scannerVersion"],
                manifest["scannedAt"],
                manifest["analysisLevel"],
                manifest["buildStatus"],
                json.dumps(manifest, sort_keys=True),
            ),
        )
        for fact in facts:
            evidence = fact["evidence"]
            connection.execute(
                "insert into facts values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fact["factId"],
                    fact["scanId"],
                    fact["repo"],
                    fact["commitSha"],
                    fact.get("projectPath"),
                    fact["factType"],
                    fact["ruleId"],
                    fact["evidenceTier"],
                    fact.get("sourceSymbol"),
                    fact.get("targetSymbol"),
                    fact.get("contractElement"),
                    evidence["filePath"],
                    evidence["startLine"],
                    evidence["endLine"],
                    evidence.get("snippetHash"),
                    evidence["extractorId"],
                    evidence["extractorVersion"],
                    json.dumps(fact["properties"], sort_keys=True),
                ),
            )
        connection.commit()
    finally:
        connection.close()
    return packet


def _rewrite_facts(packet: Path, change: Callable[[list[dict[str, Any]]], None]) -> None:
    path = packet / "facts.ndjson"
    facts = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    change(facts)
    path.write_text(
        "\n".join(json.dumps(fact, sort_keys=True) for fact in facts) + "\n",
        encoding="utf-8",
    )


def _complete_packet(packet: Path) -> None:
    manifest_path = packet / "scan-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["knownGaps"] = []
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    connection = sqlite3.connect(packet / "index.sqlite")
    try:
        connection.execute(
            "update scan_manifest set manifest_json = ?",
            (json.dumps(manifest, sort_keys=True),),
        )
        connection.commit()
    finally:
        connection.close()


def _run_case(fixture: Path, case_id: str, expected_outcome: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="artifact-memory-tracemap-outcome-") as temporary:
        packet: Any = _materialize_packet(fixture, Path(temporary))
        arguments: dict[str, Any] = {
            "source_version_ref": SOURCE_REF,
            "packet_dir": packet,
            "expected_repo": REPOSITORY,
            "expected_commit": SOURCE_COMMIT,
            "selected_fact_ids": ["fact-synthetic-status-declaration"],
            "tool_source_commit": TOOL_COMMIT,
            "configuration_digest": CONFIGURATION_DIGEST,
            "rule_catalog_digest": RULE_CATALOG_DIGEST,
        }
        if case_id == "complete":
            _complete_packet(packet)
        elif case_id == "required-artifact-missing":
            (packet / "report.md").unlink()
        elif case_id == "schema-unsupported":
            _rewrite_facts(packet, lambda facts: facts[0].__setitem__("evidenceTier", "Tier5Synthetic"))
        elif case_id == "trace-output-invalid":
            manifest_path = packet / "scan-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["knownGaps"] = "synthetic-invalid"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        elif case_id == "digest-mismatch":
            connection = sqlite3.connect(packet / "index.sqlite")
            try:
                connection.execute(
                    "update facts set evidence_tier = 'Tier4Unknown' where fact_id = ?",
                    ("fact-synthetic-status-declaration",),
                )
                connection.commit()
            finally:
                connection.close()
        elif case_id == "repository-binding-mismatch":
            arguments["expected_repo"] = "SyntheticOther"
        elif case_id == "commit-binding-mismatch":
            arguments["expected_commit"] = "9" * 40
        elif case_id == "source-version-unavailable":
            arguments["source_version_ref"] = "synthetic-invalid-source-version"
        elif case_id == "rule-catalog-unavailable":
            arguments["rule_catalog_digest"] = "synthetic-invalid-rule-catalog"
        elif case_id == "configuration-identity-unavailable":
            arguments["configuration_digest"] = "synthetic-invalid-configuration"
        elif case_id == "unsafe-provenance-rejected":
            _rewrite_facts(
                packet,
                lambda facts: facts[0]["evidence"].__setitem__("filePath", "../synthetic-escape"),
            )
        elif case_id == "provider-record-not-found":
            arguments["selected_fact_ids"] = ["synthetic-missing-fact"]
        elif case_id == "partial-evidence-admitted":
            pass
        elif case_id == "adapter-failed":
            arguments["packet_dir"] = _ExplodingPacketPath()
        else:
            raise ValidationFailure("vector-unsupported", "unknown TraceMap outcome case")

        binding, receipt = bind_trace_map_evidence_receipted(**arguments)
        validate(receipt, load_schema("adapters", "tracemap-adapter-receipt.v1.schema.json"))
        if receipt["outcome"] != expected_outcome:
            raise ValidationFailure("vector-mismatch", "TraceMap outcome did not match the declared case")
        if receipt["admitted"] != (binding is not None):
            raise ValidationFailure("vector-mismatch", "TraceMap admission state disagrees with binding output")
        if receipt["protected_input_echoed"] or receipt["local_path_echoed"]:
            raise ValidationFailure("unsafe-receipt", "TraceMap receipt exposed protected input")
        return {
            "case_id": case_id,
            "expected_outcome": expected_outcome,
            "observed_outcome": receipt["outcome"],
            "receipt_id": receipt["receipt_id"],
            "passed": True,
        }


def run_tracemap_failure_conformance(fixture: Path) -> dict[str, Any]:
    declared = sorted(DECLARED_OUTCOMES)
    cases = [_run_case(fixture, outcome, outcome) for outcome in declared]
    if sorted(case["observed_outcome"] for case in cases) != declared:
        raise ValidationFailure("outcome-surface-incomplete", "TraceMap declared outcome surface is incomplete")
    body = {
        "synthetic": True,
        "outcome": "complete",
        "provider_contract_anchor": TRACE_MAP_CONTRACT_ANCHOR,
        "declared_outcomes": declared,
        "cases": cases,
        "protected_input_echoed": False,
        "local_path_echoed": False,
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": [
            "synthetic failure vectors do not establish provider issuer authenticity",
            "adapter-failed proves exception containment through an injected synthetic path fault",
        ],
    }
    receipt = receipt_with_digest(
        "artifact-memory/tracemap-failure-conformance-receipt/v1",
        "tracemap-failure-conformance-receipt://",
        body,
    )
    validate(
        receipt,
        load_schema("adapters", "tracemap-failure-conformance-receipt.v1.schema.json"),
    )
    return receipt


def render_tracemap_failure_conformance(receipt: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| `{case['case_id']}` | `{case['observed_outcome']}` | pass |"
        for case in receipt["cases"]
    )
    return (
        "# TraceMap adapter failure-surface receipt\n\n"
        f"- Provider contract anchor: `{receipt['provider_contract_anchor']}`\n"
        f"- Aggregate outcome: `{receipt['outcome']}`\n"
        f"- Conformance receipt: `{receipt['receipt_id']}`\n"
        "- Protected input echoed: `false`\n"
        "- Local path echoed: `false`\n\n"
        "| Case | Observed outcome | Result |\n"
        "| --- | --- | --- |\n"
        f"{rows}\n\n"
        f"Authority boundary: {receipt['authority_boundary']}.\n"
    )
