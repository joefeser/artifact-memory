"""Synthetic proof for private project-vault onboarding through the public CLI model."""

from __future__ import annotations

import ipaddress
import json
import re
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, receipt_with_digest
from .context import AUTHORITY_BOUNDARY, build_selection_policy, export_context
from .independent_context_reader import recall_context
from .knowledge import knowledge_schema
from .projection import project_records, search_receipt
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, validate


SELECTED_AT = "2026-09-15T00:00:00Z"
MAX_CONTEXT_BYTES = 4096
SYNTHETIC_RECORD_PREFIX = "record://synthetic-onboarding/"
SEARCH_CASES = (
    ("overlay connectivity", ["record://synthetic-onboarding/relay-connectivity"]),
    ("JSONC mode", ["record://synthetic-onboarding/jsonc-mode"]),
)
SAFETY_CATEGORIES = [
    "credential-fields",
    "email-addresses",
    "machine-local-paths",
    "network-addresses",
    "non-json-raw-sources",
    "non-synthetic-records",
]
_EMAIL = re.compile(r"\b[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6_CANDIDATE = re.compile(r"\[?[0-9A-Fa-f:.]+(?:%[A-Za-z0-9_.-]+)?\]?")
_NETWORK_URL = re.compile(r"\b(?:https?|ssh|sftp|ftp|ftps|nfs|smb)://", re.IGNORECASE)
_HOSTNAME = re.compile(
    r"\b(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}\b"
)
_MACHINE_PATH = re.compile(
    r"(?:^|\s)(?:/(?:Users|home|srv|mnt|var|etc|opt|private|Volumes)/\S+|[A-Za-z]:[\\/]\S+|\\\\\S+)"
)
_CREDENTIAL_KEYS = {
    "access_key",
    "access_token",
    "api_key",
    "authorization",
    "bearer",
    "client_secret",
    "cookie",
    "credential",
    "credentials",
    "passphrase",
    "passwd",
    "password",
    "private_key",
    "secret",
    "session_token",
    "signing_key",
    "ssh_key",
    "token",
}
_CREDENTIAL_KEY_PARTS = {
    "authorization",
    "bearer",
    "cookie",
    "credential",
    "credentials",
    "passphrase",
    "passwd",
    "password",
    "secret",
    "token",
}
_KEY_QUALIFIERS = {"access", "api", "client", "private", "signing", "ssh"}


def _record_paths(fixture_root: Path) -> list[Path]:
    return sorted((fixture_root / "records").rglob("*.json"))


def _load_records(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        value = load_json(path)
        if not isinstance(value, dict):
            raise ValidationFailure("invalid-input", "synthetic onboarding record must be an object")
        validate(value, knowledge_schema(value))
        records.append(value)
    return records


def _walk(value: Any) -> tuple[list[str], list[str]]:
    keys: list[str] = []
    strings: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(key))
            keys.append(normalized_key.casefold().replace("-", "_"))
            child_keys, child_strings = _walk(item)
            keys.extend(child_keys)
            strings.extend(child_strings)
    elif isinstance(value, list):
        for item in value:
            child_keys, child_strings = _walk(item)
            keys.extend(child_keys)
            strings.extend(child_strings)
    elif isinstance(value, str):
        strings.append(value)
    return keys, strings


def _has_network_binding(value: str) -> bool:
    if _IPV4.search(value) or _NETWORK_URL.search(value) or _HOSTNAME.search(value):
        return True
    for candidate in _IPV6_CANDIDATE.findall(value):
        address = candidate.strip("[]().,;").split("%", 1)[0]
        if ":" not in address:
            continue
        try:
            if isinstance(ipaddress.ip_address(address), ipaddress.IPv6Address):
                return True
        except ValueError:
            continue
    return False


def _is_credential_key(key: str) -> bool:
    parts = set(key.split("_"))
    return (
        key in _CREDENTIAL_KEYS
        or bool(parts & _CREDENTIAL_KEY_PARTS)
        or ("key" in parts and bool(parts & _KEY_QUALIFIERS))
    )


def _fixture_safety(fixture_root: Path, records: list[dict[str, Any]]) -> dict[str, Any]:
    canonical_record_paths = set(_record_paths(fixture_root))
    allowed_evidence_paths = {
        fixture_root / "README.md",
        fixture_root / "expected-receipt.json",
        fixture_root / "receipt.md",
    }
    raw_sources = [
        path
        for path in fixture_root.rglob("*")
        if path.is_file()
        and path not in canonical_record_paths
        and path not in allowed_evidence_paths
    ]
    findings = len(raw_sources)
    for record in records:
        keys, strings = _walk(record)
        if not str(record.get("record_id", "")).startswith(SYNTHETIC_RECORD_PREFIX):
            findings += 1
        if not str(record.get("meaning", {}).get("summary", "")).startswith("Synthetic "):
            findings += 1
        if record.get("artifact_refs"):
            findings += 1
        if any(_is_credential_key(key) for key in keys):
            findings += 1
        if any(
            _EMAIL.search(value)
            or _has_network_binding(value)
            or _MACHINE_PATH.search(value)
            for value in strings
        ):
            findings += 1
        provenance = record.get("provenance", [])
        if any(
            not str(item.get("source_ref", "")).startswith(("actor://synthetic/", "fixture://synthetic/"))
            for item in provenance
            if isinstance(item, dict)
        ):
            findings += 1
    if findings:
        raise ValidationFailure(
            "fixture-boundary-invalid",
            "synthetic onboarding fixture contains a forbidden category",
        )
    return {
        "scanned_record_count": len(records),
        "raw_source_file_count": 0,
        "forbidden_category_match_count": 0,
        "categories_checked": SAFETY_CATEGORIES,
    }


def run_private_vault_onboarding_slice(fixture_root: Path, workspace: Path) -> dict[str, Any]:
    """Validate, project, search, and context-export a synthetic project vault."""
    paths = _record_paths(fixture_root)
    records = _load_records(paths)
    fixture_safety = _fixture_safety(fixture_root, records)

    generated = workspace / "generated"
    projection_root = generated / "search-projection"
    projection = project_records(paths, projection_root)
    index = projection_root / "records.sqlite"

    searches = []
    selected_ids: set[str] = set()
    search_outcome = "verified"
    for query, expected_ids in SEARCH_CASES:
        result = search_receipt(
            index,
            query,
            literal=True,
            exclude_superseded=True,
        )
        searches.append(result)
        selected_ids.update(result["record_ids"])
        if result["record_ids"] != expected_ids:
            search_outcome = "failed"

    selected = sorted(selected_ids)
    pack = export_context(
        records,
        allowed_sensitivity="private",
        max_bytes=MAX_CONTEXT_BYTES,
        supported_context_schema_ids=["artifact-memory/context-pack/v4"],
        **build_selection_policy(
            selected,
            selected_at=SELECTED_AT,
            freshness_basis="synthetic-operator-asserted-current",
        ),
    )
    serialized_pack = canonical_bytes(pack)
    recall = recall_context(serialized_pack)
    validate(pack, load_schema("core", "context-pack.v4.schema.json"))
    validate(recall, load_schema("core", "context-recall-receipt.v1.schema.json"))

    context_root = generated / "context-pack-operator-startup"
    context_root.mkdir(parents=True, exist_ok=True)
    (context_root / "context-pack.json").write_text(
        json.dumps(pack, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (context_root / "context-recall-receipt.json").write_text(
        json.dumps(recall, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    recalled_ids = [item["record_id"] for item in recall["records"]]
    context_outcome = "verified" if recalled_ids == selected and len(serialized_pack) <= MAX_CONTEXT_BYTES else "failed"
    operations = [
        {"name": "validate-synthetic-canonical-records", "outcome": "complete"},
        {"name": "check-public-fixture-boundary", "outcome": "verified"},
        {"name": "build-replaceable-search-projection", "outcome": "complete"},
        {"name": "find-operational-topics", "outcome": search_outcome},
        {"name": "export-bounded-context-pack-v4", "outcome": context_outcome},
        {"name": "independent-informational-recall", "outcome": context_outcome},
    ]
    outcome = "complete" if all(item["outcome"] in {"complete", "verified"} for item in operations) else "failed"
    body = {
        "outcome": outcome,
        "operations": operations,
        "record_validation": {
            "record_count": len(records),
            "schema_ids": sorted({record["schema_id"] for record in records}),
            "synthetic_namespace": SYNTHETIC_RECORD_PREFIX,
        },
        "projection": {
            "record_count": projection["record_count"],
            "source_record_set_digest": projection["source_record_set_digest"],
            "generated_views": sorted(projection["generated_views"]),
        },
        "searches": searches,
        "context": {
            "schema_id": pack["schema_id"],
            "pack_id": pack["pack_id"],
            "serialized_bytes": len(serialized_pack),
            "max_bytes": MAX_CONTEXT_BYTES,
            "selected_record_count": len(pack["records"]),
            "not_caller_selected_count": pack["selection_receipt"]["exclusion_counts"]["not-caller-selected"],
            "recall_receipt_id": recall["receipt_id"],
            "artifact_retrieval": recall["artifact_retrieval"],
            "mutation_authority": recall["mutation_authority"],
            "disclosure_authority": recall["disclosure_authority"],
            "execution_authority": recall["execution_authority"],
        },
        "public_fixture_safety": fixture_safety,
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": [
            "fixture-specific pattern checks do not prove that every protected value is absent from arbitrary future records",
            "freshness is an explicit operator assertion, not inferred truth",
            "generated projections and context packs can disclose private summaries and require the same local access controls as their source vault",
            "search and memory remain informational and do not grant operational authority",
        ],
    }
    receipt = receipt_with_digest(
        "artifact-memory/private-vault-onboarding-slice-receipt/v1",
        "private-vault-onboarding-slice-receipt://synthetic/",
        body,
    )
    validate(receipt, load_schema("core", "private-vault-onboarding-slice-receipt.v1.schema.json"))
    return receipt


def render_private_vault_onboarding_receipt(receipt: dict[str, Any]) -> str:
    validate(receipt, load_schema("core", "private-vault-onboarding-slice-receipt.v1.schema.json"))
    search_outcome = next(
        operation["outcome"]
        for operation in receipt["operations"]
        if operation["name"] == "find-operational-topics"
    )
    lines = [
        "# Synthetic private-vault onboarding receipt",
        "",
        f'- Outcome: `{receipt["outcome"]}`',
        f'- Canonical records validated: `{receipt["record_validation"]["record_count"]}`',
        f'- Projection source digest: `{receipt["projection"]["source_record_set_digest"]}`',
        f'- Operational searches executed: `{len(receipt["searches"])}`; outcome: `{search_outcome}`',
        f'- Context contract: `{receipt["context"]["schema_id"]}`',
        f'- Context bytes: `{receipt["context"]["serialized_bytes"]}` / `{receipt["context"]["max_bytes"]}`',
        f'- Public fixture forbidden-category matches: `{receipt["public_fixture_safety"]["forbidden_category_match_count"]}`',
        "",
        f'Authority boundary: {receipt["authority_boundary"]}.',
        "",
        "Generated SQLite and context files were written only to the caller-provided disposable workspace.",
        "They are rebuildable views and are not canonical knowledge.",
        "",
    ]
    return "\n".join(lines)
