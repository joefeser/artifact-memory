"""Build and replay checked synthetic safe and malicious ZIP vectors."""

from __future__ import annotations

import re
import stat
import tempfile
import warnings
import zipfile
from pathlib import Path
from typing import Any

from .archive import inspect_zip
from .canonical import canonical_bytes, receipt_with_digest, sha256_bytes
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, validate


def _zip_info(name: str, kind: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    if kind == "directory":
        info.filename = name.rstrip("/") + "/"
        info.create_system = 3
        info.external_attr = (stat.S_IFDIR | 0o755) << 16
    elif kind == "link":
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
    else:
        info.create_system = 3
        info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info


def _set_encryption_flags(data: bytes) -> bytes:
    patched = bytearray(data)
    offsets = ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8))
    for signature, flag_offset in offsets:
        start = 0
        while (position := data.find(signature, start)) >= 0:
            field = position + flag_offset
            flags = int.from_bytes(patched[field : field + 2], "little") | 0x1
            patched[field : field + 2] = flags.to_bytes(2, "little")
            start = position + 4
    return bytes(patched)


def _build_case(case: dict[str, Any], path: Path) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w") as archive:
            for entry in case["entries"]:
                kind = entry["kind"]
                payload = entry.get("content_utf8", "").encode("utf-8")
                archive.writestr(_zip_info(entry["path"], kind), payload)
    data = path.read_bytes()
    if case.get("patch") == "encrypted-flags":
        path.write_bytes(_set_encryption_flags(data))
    elif case.get("patch") == "corrupt-payload":
        marker = case["corruption_marker"].encode("utf-8")
        position = data.find(marker)
        if position < 0:
            raise ValidationFailure("invalid-vector", "corruption marker is absent from generated ZIP")
        patched = bytearray(data)
        patched[position] ^= 0x01
        path.write_bytes(patched)


def run_archive_conformance(vector_path: Path) -> dict[str, Any]:
    vectors = load_json(vector_path)
    if not isinstance(vectors, dict):
        raise ValidationFailure("invalid-vector", "archive conformance vectors must be an object")
    if vectors.get("schema_id") != "artifact-memory/archive-conformance-vectors/v1" or vectors.get("synthetic") is not True:
        raise ValidationFailure("invalid-vector", "archive conformance vectors require synthetic provenance")
    cases = vectors.get("cases")
    if not isinstance(cases, list) or not cases or not all(isinstance(case, dict) for case in cases):
        raise ValidationFailure("invalid-vector", "archive conformance vectors require cases")
    for case in cases:
        case_id = case.get("case_id")
        entries = case.get("entries")
        if not isinstance(case_id, str) or re.fullmatch(r"[A-Za-z0-9._-]+", case_id) is None:
            raise ValidationFailure("invalid-vector", "archive case identifiers must be safe strings")
        if not isinstance(entries, list) or not all(
            isinstance(entry, dict)
            and isinstance(entry.get("path"), str)
            and entry.get("kind") in {"file", "directory", "link"}
            and isinstance(entry.get("content_utf8", ""), str)
            for entry in entries
        ):
            raise ValidationFailure("invalid-vector", "archive cases require valid entry recipes")
        if case.get("expected_outcome") not in {"supported", "partial", "unsupported", "failed"} or not isinstance(case.get("expected_diagnostic_codes"), list) or not all(isinstance(code, str) for code in case["expected_diagnostic_codes"]):
            raise ValidationFailure("invalid-vector", "archive cases require expected outcomes and diagnostics")
        if case.get("patch") not in {None, "encrypted-flags", "corrupt-payload"}:
            raise ValidationFailure("invalid-vector", "archive case patch is unsupported")
        if case.get("patch") == "corrupt-payload" and not isinstance(case.get("corruption_marker"), str):
            raise ValidationFailure("invalid-vector", "corrupt archive cases require a marker")
        for field in ("max_entries", "max_uncompressed_bytes"):
            limit = case.get(field)
            if limit is not None and (
                not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0
            ):
                raise ValidationFailure(
                    "invalid-vector",
                    f"archive case {field} must be a positive integer",
                )

    summaries: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for case in cases:
            archive_path = root / f"{case['case_id']}.zip"
            _build_case(case, archive_path)
            receipt = inspect_zip(
                archive_path,
                max_uncompressed_bytes=case.get("max_uncompressed_bytes", 16 * 1024 * 1024),
                max_entries=case.get("max_entries", 10_000),
            )
            codes = [item["code"] for item in receipt["diagnostics"]]
            if receipt["outcome"] != case["expected_outcome"] or codes != case["expected_diagnostic_codes"]:
                raise ValidationFailure("vector-mismatch", f"archive case {case['case_id']} did not reproduce")
            if case["expected_outcome"] == "supported":
                if receipt["relationship"] is None or receipt["container"]["content_digest"] == receipt["extracted_tree_manifest_digest"]:
                    raise ValidationFailure("vector-mismatch", "safe container/tree relationship did not reproduce")
            elif receipt["relationship"] is not None or receipt["extracted_tree_manifest"] is not None:
                raise ValidationFailure("vector-mismatch", "incomplete archive emitted a complete tree relationship")
            summaries.append(
                {
                    "case_id": case["case_id"],
                    "outcome": receipt["outcome"],
                    "inspection_completeness": receipt["inspection_completeness"],
                    "diagnostic_codes": codes,
                    "accepted_entry_count": len(receipt["entries"]),
                    "container_digest": receipt["container"]["content_digest"],
                    "extracted_tree_manifest_digest": receipt["extracted_tree_manifest_digest"],
                    "relationship_emitted": receipt["relationship"] is not None,
                    "inspection_receipt_id": receipt["receipt_id"],
                }
            )

    body = {
        "outcome": "pass",
        "synthetic": True,
        "vector_set_digest": sha256_bytes(canonical_bytes(vectors)),
        "case_count": len(summaries),
        "cases": summaries,
        "claims": [
            "safe ZIP bytes retain an independent container digest and complete extracted-tree manifest relationship",
            "path traversal, duplicate entry, case collision, link, encryption, corruption, and decompression limits produce explicit bounded outcomes",
            "partial and unsupported receipts emit no complete extracted-tree relationship",
        ],
        "authority_boundary": "archive inspection grants no extraction, execution, mutation, disclosure, or trust authority",
        "limitations": [
            "fixtures are newly authored synthetic ZIP recipes replayed in a temporary directory",
            "v0 supports bounded ZIP inspection only and does not claim arbitrary archive-format interoperability",
        ],
    }
    receipt = receipt_with_digest(
        "artifact-memory/archive-conformance-receipt/v1",
        "archive-conformance-receipt://",
        body,
    )
    validate(receipt, load_schema("core", "archive-conformance-receipt.v1.schema.json"))
    return receipt


def render_archive_conformance(receipt: dict[str, Any]) -> str:
    lines = [
        "# Archive conformance receipt",
        "",
        f"- Outcome: `{receipt['outcome']}`",
        f"- Receipt: `{receipt['receipt_id']}`",
        f"- Synthetic cases: {receipt['case_count']}",
        "",
        "| Case | Outcome | Completeness | Diagnostics | Tree relationship |",
        "| --- | --- | --- | --- | --- |",
    ]
    for case in receipt["cases"]:
        diagnostics = ", ".join(case["diagnostic_codes"]) or "none"
        relationship = "yes" if case["relationship_emitted"] else "no"
        lines.append(f"| `{case['case_id']}` | `{case['outcome']}` | `{case['inspection_completeness']}` | `{diagnostics}` | `{relationship}` |")
    lines.extend(
        [
            "",
            "Only the safe complete case emits a container-to-extracted-tree relationship. The fixture performs bounded in-memory inspection and grants no extraction, execution, mutation, disclosure, or trust authority.",
            "",
        ]
    )
    return "\n".join(lines)
