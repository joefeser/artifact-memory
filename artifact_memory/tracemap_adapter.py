"""Narrow, provider-preserving TraceMap evidence binding adapter."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .canonical import CHUNK_SIZE, canonical_bytes

TRACE_MAP_CONTRACT_ANCHOR = "9a252f12f781ae2a0aab52b5faa53601440a2a3b"
REQUIRED_ARTIFACTS = ("scan-manifest.json", "facts.ndjson", "index.sqlite", "report.md", "logs/analyzer.log")
FACT_SCHEMA_ID = "https://tracemap.tools/contracts/code-fact.v1.schema.json"
MANIFEST_SCHEMA_ID = "https://tracemap.tools/contracts/scan-manifest.v1.schema.json"
INTEGRITY_STATE = "integrity-verified / issuer-unverified"


class AdapterFailure(Exception):
    def __init__(self, outcome: str, message: str) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.message = message


_canonical = canonical_bytes


def _digest(value: bytes) -> str:
    return "sha-256:" + hashlib.sha256(value).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AdapterFailure("trace-output-invalid", "provider JSON is unavailable or invalid") from exc
    if not isinstance(value, dict):
        raise AdapterFailure("trace-output-invalid", "provider JSON object is required")
    return value


def _read_facts(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise AdapterFailure("trace-output-invalid", "provider facts are unavailable") from exc
    facts: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            raise AdapterFailure("trace-output-invalid", "provider facts contain a blank line")
        try:
            fact = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AdapterFailure("trace-output-invalid", "provider facts contain invalid JSON") from exc
        if not isinstance(fact, dict):
            raise AdapterFailure("trace-output-invalid", "provider fact must be an object")
        facts.append(fact)
    return facts


def _safe_relative(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    return bool(normalized) and not re.match(r"^[A-Za-z]:/", normalized) and not path.is_absolute() and ".." not in path.parts


def _require_digest(value: str, label: str) -> None:
    if not re.fullmatch(r"sha-256:[0-9a-f]{64}", value):
        raise AdapterFailure("trace-output-invalid", f"{label} is not a SHA-256 content identity")


def _is_link_or_reparse_point(path: Path) -> bool:
    try:
        metadata = os.lstat(path)
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & reparse_flag
    )


def _snapshot_required_artifacts(packet_dir: Path, snapshot_dir: Path) -> list[dict[str, str]]:
    if _is_link_or_reparse_point(packet_dir):
        raise AdapterFailure("unsafe-provenance-rejected", "provider packet root must not be a link or reparse point")
    for name in REQUIRED_ARTIFACTS:
        packet_path = packet_dir / name
        current = packet_dir
        for part in PurePosixPath(name).parts:
            current /= part
            if _is_link_or_reparse_point(current):
                raise AdapterFailure("unsafe-provenance-rejected", "required provider artifact path must not contain a link or reparse point")
        if not packet_path.is_file():
            raise AdapterFailure("required-artifact-missing", "required provider artifact is missing")
    inspected = []
    for name in REQUIRED_ARTIFACTS:
        digest = hashlib.sha256()
        target = snapshot_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with (packet_dir / name).open("rb") as stream, target.open("xb") as output:
                while chunk := stream.read(CHUNK_SIZE):
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
        except OSError as exc:
            raise AdapterFailure("trace-output-invalid", "provider artifact is unavailable or invalid") from exc
        inspected.append({"name": name, "digest": "sha-256:" + digest.hexdigest()})
    return inspected


def _validate_provider_packet(packet_dir: Path, expected_repo: str, expected_commit: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = _load_object(packet_dir / "scan-manifest.json")
    required_manifest = ("scanId", "repoName", "commitSha", "scannerVersion", "scannedAt", "analysisLevel", "buildStatus", "knownGaps")
    scalar_manifest = required_manifest[:-1]
    if any(not isinstance(manifest.get(key), str) or not manifest[key] for key in scalar_manifest):
        raise AdapterFailure("trace-output-invalid", "provider manifest is incomplete")
    if not isinstance(manifest.get("knownGaps"), list) or any(not isinstance(gap, str) for gap in manifest["knownGaps"]):
        raise AdapterFailure("trace-output-invalid", "provider known gaps must be an array of strings")
    try:
        datetime.fromisoformat(manifest["scannedAt"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdapterFailure("trace-output-invalid", "provider scan time is invalid") from exc
    if manifest["repoName"] != expected_repo:
        raise AdapterFailure("repository-binding-mismatch", "provider repository does not match expected repository")
    if manifest["commitSha"] != expected_commit:
        raise AdapterFailure("commit-binding-mismatch", "provider commit does not match expected commit")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", expected_commit):
        raise AdapterFailure("trace-output-invalid", "expected commit is not a Git commit identity")
    facts = _read_facts(packet_dir / "facts.ndjson")
    for fact in facts:
        scalar_fact = ("factId", "scanId", "repo", "commitSha", "factType", "ruleId", "evidenceTier")
        if (
            any(not isinstance(fact.get(key), str) or not fact[key] for key in scalar_fact)
            or fact["scanId"] != manifest["scanId"]
            or fact["commitSha"] != expected_commit
            or fact["repo"] != expected_repo
            or not isinstance(fact.get("properties"), dict)
        ):
            raise AdapterFailure("trace-output-invalid", "provider fact provenance is incomplete")
        evidence = fact.get("evidence")
        if (
            not isinstance(evidence, dict)
            or not _safe_relative(evidence.get("filePath"))
            or any(not isinstance(evidence.get(key), str) or not evidence[key] for key in ("extractorId", "extractorVersion"))
            or any(not isinstance(evidence.get(key), int) or isinstance(evidence[key], bool) for key in ("startLine", "endLine"))
        ):
            raise AdapterFailure("unsafe-provenance-rejected", "provider evidence path is not portable")
        optional_strings = (
            fact.get("projectPath"),
            fact.get("sourceSymbol"),
            fact.get("targetSymbol"),
            fact.get("contractElement"),
            evidence.get("snippetHash"),
        )
        if any(value is not None and not isinstance(value, str) for value in optional_strings):
            raise AdapterFailure("trace-output-invalid", "provider fact contains an invalid optional scalar")
        if fact["evidenceTier"] not in {"Tier1Semantic", "Tier2Structural", "Tier3SyntaxOrTextual", "Tier4Unknown"}:
            raise AdapterFailure("schema-unsupported", "provider evidence tier is unsupported")
    return manifest, facts


def _verify_index(packet_dir: Path, manifest: dict[str, Any], facts: list[dict[str, Any]]) -> None:
    try:
        uri = (packet_dir / "index.sqlite").resolve().as_uri()
        connection = sqlite3.connect(f"{uri}?mode=ro", uri=True)
        try:
            tables = {row[0] for row in connection.execute("select name from sqlite_master where type='table'")}
            if not {"scan_manifest", "facts"}.issubset(tables):
                raise AdapterFailure("trace-output-invalid", "provider index lacks required tables")
            rows = connection.execute(
                "select scan_id, repo, commit_sha, scanner_version, scanned_at, analysis_level, build_status, manifest_json from scan_manifest"
            ).fetchall()
            expected_manifest = (
                manifest["scanId"],
                manifest["repoName"],
                manifest["commitSha"],
                manifest["scannerVersion"],
                datetime.fromisoformat(manifest["scannedAt"].replace("Z", "+00:00")),
                manifest["analysisLevel"],
                manifest["buildStatus"],
                canonical_bytes(manifest),
            )
            normalized_manifests = [
                (
                    *row[:4],
                    datetime.fromisoformat(row[4].replace("Z", "+00:00")),
                    *row[5:-1],
                    canonical_bytes(json.loads(row[-1])),
                )
                for row in rows
            ]
            if normalized_manifests != [expected_manifest]:
                raise AdapterFailure("digest-mismatch", "provider index manifest parity failed")
            indexed_facts = []
            for row in connection.execute(
                "select fact_id, scan_id, repo, commit_sha, project_path, fact_type, rule_id, evidence_tier, source_symbol, target_symbol, contract_element, file_path, start_line, end_line, snippet_hash, extractor_id, extractor_version, properties_json from facts"
            ):
                indexed_facts.append((*row[:-1], canonical_bytes(json.loads(row[-1]))))
            expected_facts = []
            for fact in facts:
                evidence = fact["evidence"]
                expected_facts.append(
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
                        canonical_bytes(fact["properties"]),
                    )
                )
            if sorted(indexed_facts, key=lambda item: item[0]) != sorted(expected_facts, key=lambda item: item[0]):
                raise AdapterFailure("digest-mismatch", "provider index fact parity failed")
        finally:
            connection.close()
    except (sqlite3.Error, json.JSONDecodeError, ValueError, TypeError, AttributeError, KeyError, UnicodeError) as exc:
        raise AdapterFailure("trace-output-invalid", "provider index cannot be opened read-only") from exc


def bind_trace_map_evidence(
    source_version_ref: str,
    packet_dir: Path,
    expected_repo: str,
    expected_commit: str,
    selected_fact_ids: list[str] | None = None,
    *,
    tool_source_commit: str,
    configuration_digest: str,
    rule_catalog_digest: str | None = None,
) -> dict[str, Any]:
    """Validate and bind one existing TraceMap packet without interpreting it."""
    if not re.fullmatch(r"artifact-version://[A-Za-z0-9._~-]+/[A-Za-z0-9._~-]+/[0-9]+", source_version_ref):
        raise AdapterFailure("source-version-unavailable", "source artifact-version reference is invalid")
    if not re.fullmatch(r"[0-9a-f]{40}", tool_source_commit):
        raise AdapterFailure("trace-output-invalid", "provider tool source commit is invalid")
    _require_digest(configuration_digest, "provider configuration digest")
    if rule_catalog_digest is not None:
        _require_digest(rule_catalog_digest, "provider rule catalog digest")
    with tempfile.TemporaryDirectory(prefix="artifact-memory-tracemap-packet-") as temporary:
        snapshot_dir = Path(temporary)
        file_digests = _snapshot_required_artifacts(packet_dir, snapshot_dir)
        manifest, facts = _validate_provider_packet(snapshot_dir, expected_repo, expected_commit)
        _verify_index(snapshot_dir, manifest, facts)
    fact_by_id = {fact["factId"]: fact for fact in facts}
    selected = selected_fact_ids or sorted(fact_by_id)[:1]
    if not selected or any(fact_id not in fact_by_id for fact_id in selected):
        raise AdapterFailure("provider-record-not-found", "selected provider record is unavailable")

    provider_identity = {
        "tool_source_commit": tool_source_commit,
        "configuration_digest": configuration_digest,
        **({"rule_catalog_digest": rule_catalog_digest} if rule_catalog_digest is not None else {}),
    }
    packet_body = {
        "provider": "tracemap",
        "contract_anchor": TRACE_MAP_CONTRACT_ANCHOR,
        "provider_identity": provider_identity,
        "files": file_digests,
    }
    packet_digest = _digest(_canonical(packet_body))
    selected_records = []
    for fact_id in sorted(selected):
        fact = fact_by_id[fact_id]
        limitations = []
        limitation = fact["properties"].get("limitation") if isinstance(fact["properties"], dict) else None
        if isinstance(limitation, str) and limitation:
            limitations.append(limitation)
        selected_records.append(
            {
                "provider_record_id": fact_id,
                "fact_type": fact["factType"],
                "rule_id": fact["ruleId"],
                "evidence_tier": fact["evidenceTier"],
                "coverage": {
                    "analysis_level": manifest["analysisLevel"],
                    "build_status": manifest["buildStatus"],
                    "known_gaps": sorted(manifest["knownGaps"]),
                },
                "limitations": sorted(limitations),
            }
        )
    binding_body = {
        "source_version_ref": source_version_ref,
        "packet_digest": packet_digest,
        "selected_provider_records": selected_records,
        "provider_contract_anchor": TRACE_MAP_CONTRACT_ANCHOR,
    }
    binding_digest = hashlib.sha256(_canonical(binding_body)).hexdigest()
    outcome = "partial-evidence-admitted" if manifest["knownGaps"] else "complete"
    receipt_body = {
        "outcome": outcome,
        "provider": "tracemap",
        "packet_digest": packet_digest,
        "selected_provider_record_ids": sorted(selected),
        "provider_identity": provider_identity,
        "integrity_state": INTEGRITY_STATE,
    }
    return {
        "schema_id": "artifact-memory/tracemap-evidence-binding/v1",
        "binding_id": f"binding://tracemap/{binding_digest}",
        "source_version_ref": source_version_ref,
        "provider": {
            "id": "tracemap",
            "contract_anchor": TRACE_MAP_CONTRACT_ANCHOR,
            "record_schema_ids": [MANIFEST_SCHEMA_ID, FACT_SCHEMA_ID],
            **provider_identity,
        },
        "evidence_packet_ref": f"artifact-version://tracemap/evidence/{packet_digest.removeprefix('sha-256:')}/1",
        "integrity_state": INTEGRITY_STATE,
        "selected_provider_record_ids": sorted(selected),
        "selected_provider_records": selected_records,
        "receipt": {"outcome": outcome, "deterministic_body_digest": _digest(_canonical(receipt_body)), "diagnostics": []},
        "content_objects": file_digests,
        "relations": [{"type": "produced-from", "source": f"artifact-version://tracemap/evidence/{packet_digest.removeprefix('sha-256:')}/1", "target": source_version_ref, "supports_claim": False}],
    }
