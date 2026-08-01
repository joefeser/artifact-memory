"""Replay synthetic issue #7 scan-policy and completeness vectors."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from .canonical import receipt_with_digest
from .scan import ScanLimits, _ObservationFailure, make_scan_policy, scan_path
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, validate


def _require_case(case: Any) -> dict[str, Any]:
    if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not isinstance(case.get("observation"), str):
        raise ValidationFailure("invalid-vector", "scan conformance case is malformed")
    if case.get("expected_outcome") not in {"complete", "partial", "failed", "cancelled"}:
        raise ValidationFailure("invalid-vector", "scan conformance expected outcome is malformed")
    return case


def _case_observations(root: Path, case: dict[str, Any]) -> tuple[list[tuple[Path, str]], tuple[int, str] | _ObservationFailure | None]:
    observation = case["observation"]
    if observation in {"file", "file-failure", "excluded"}:
        relative_path = case.get("relative_path")
        if not isinstance(relative_path, str):
            raise ValidationFailure("invalid-vector", "scan conformance relative path is malformed")
        kind = "file" if observation in {"file", "file-failure"} else "excluded"
        walked = [(root / relative_path, kind)]
    elif observation == "root-failure":
        walked = [(root, case.get("failure_code", "unreadable"))]
    elif observation == "cancelled":
        walked = [(root, "cancelled")]
    else:
        raise ValidationFailure("invalid-vector", "scan conformance observation is unsupported")

    if observation == "file":
        byte_size = case.get("byte_size")
        content_digest = case.get("content_digest")
        if isinstance(byte_size, bool) or not isinstance(byte_size, int) or byte_size < 0 or not isinstance(content_digest, str):
            raise ValidationFailure("invalid-vector", "scan conformance file observation is malformed")
        hashed: tuple[int, str] | _ObservationFailure | None = (byte_size, content_digest)
    elif observation == "file-failure":
        code = case.get("failure_code")
        if code not in {"unreadable", "unstable"}:
            raise ValidationFailure("invalid-vector", "scan conformance failure code is unsupported")
        hashed = _ObservationFailure(code, "synthetic entry could not be admitted")
    else:
        hashed = None
    return walked, hashed


def render_scan_conformance_receipt(receipt: dict[str, Any]) -> str:
    outcomes = receipt["outcomes"]
    return (
        "# Scan policy and completeness conformance receipt\n\n"
        f"- Outcome: `{receipt['outcome']}`\n"
        f"- Synthetic cases: {receipt['case_count']}\n"
        f"- Outcomes: complete={outcomes['complete']}, partial={outcomes['partial']}, failed={outcomes['failed']}, cancelled={outcomes['cancelled']}\n"
        "- Policy identity: canonical SHA-256 digest\n"
        "- Manifest binding: manifest identity and normalized tree digest\n\n"
        "The vectors are newly authored synthetic observer events. They prove typed contract behavior for declared exclusions, inaccessible entries, changing files, unavailable roots, and cancellation; they are not claims about a production filesystem.\n"
    )


def run_scan_conformance(fixture_path: Path) -> dict[str, Any]:
    vectors = load_json(fixture_path)
    if not isinstance(vectors, dict) or vectors.get("synthetic") is not True:
        raise ValidationFailure("invalid-vector", "scan conformance input must declare synthetic provenance")
    started_at = vectors.get("started_at")
    ended_at = vectors.get("ended_at")
    cases = vectors.get("cases")
    if not isinstance(started_at, str) or not isinstance(ended_at, str) or not isinstance(cases, list) or not cases:
        raise ValidationFailure("invalid-vector", "scan conformance vector set is malformed")

    summaries: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="artifact-memory-scan-conformance-") as temporary:
        root = Path(temporary)
        for raw_case in cases:
            case = _require_case(raw_case)
            walked, hashed = _case_observations(root, case)
            prefixes = case.get("exclusion_prefixes", [])
            if not isinstance(prefixes, list) or not all(isinstance(item, str) for item in prefixes):
                raise ValidationFailure("invalid-vector", "scan conformance exclusion prefixes are malformed")
            policy = make_scan_policy(endpoint_ref="endpoint://synthetic/scan-vectors", root_relative_path=case["id"], exclusion_prefixes=tuple(prefixes))
            limits = ScanLimits(cancellation_check=(lambda: True)) if case["observation"] == "cancelled" else None
            hash_patch = patch("artifact_memory.scan._hash_regular_file", side_effect=hashed) if isinstance(hashed, _ObservationFailure) else patch("artifact_memory.scan._hash_regular_file", return_value=hashed)
            with (
                patch("artifact_memory.scan._walk", return_value=iter(walked)),
                patch("artifact_memory.scan._utc_now", side_effect=[started_at, ended_at]),
                hash_patch,
            ):
                manifest, receipt = scan_path(root, limits=limits, policy=policy)
            if receipt["outcome"] != case["expected_outcome"]:
                raise ValidationFailure("vector-mismatch", f"scan conformance outcome does not match: {case['id']}")
            validate(receipt, load_schema("core", "scan-receipt.v2.schema.json"))
            summaries.append({
                "id": case["id"],
                "outcome": receipt["outcome"],
                "manifest_ref": manifest["manifest_id"],
                "manifest_tree_digest": manifest["tree_digest"],
                "receipt_ref": receipt["receipt_id"],
                "warning_codes": [item["code"] for item in receipt["warnings"]],
                "failure_codes": [item["code"] for item in receipt["failures"]],
                "excluded_entry_count": receipt["excluded_entry_count"],
            })

    outcomes = {name: sum(item["outcome"] == name for item in summaries) for name in ("complete", "partial", "failed", "cancelled")}
    body = {
        "outcome": "complete",
        "synthetic": True,
        "case_count": len(summaries),
        "outcomes": outcomes,
        "cases": summaries,
        "claims": [
            "declared exclusions remain separately accounted without weakening a complete outcome",
            "scan receipts bind canonical policy identity, logical scope, attempt times, implementation identity, and manifest digests",
            "inaccessible and changing entries cannot produce a complete outcome",
            "complete, partial, failed, and cancelled remain distinct outcomes",
        ],
        "limitations": [
            "synthetic observer events do not prove host filesystem behavior",
            "v0 does not follow links and reports unsupported entry semantics explicitly",
        ],
    }
    receipt = receipt_with_digest("artifact-memory/scan-conformance-receipt/v1", "scan-conformance-receipt://", body)
    validate(receipt, load_schema("core", "scan-conformance-receipt.v1.schema.json"))
    return receipt
