"""Synthetic conformance evidence for portable storage locations."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, receipt_with_digest, sha256_bytes
from .location import AUTHORITY_BOUNDARY, validate_discovery_evidence, validate_endpoint, validate_location_observation
from .resolver import resolve
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, validate


VECTOR_SCHEMA_ID = "artifact-memory/location-conformance-vectors/v1"


def _digest_text(value: str) -> str:
    return "sha-256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def run_location_conformance(vector_path: Path) -> dict[str, Any]:
    vectors = load_json(vector_path)
    if not isinstance(vectors, dict) or set(vectors) != {"schema_id", "synthetic_only", "endpoint", "artifact_ref", "content_ref", "relative_path", "observed_at", "platforms"}:
        raise ValidationFailure("invalid-vector-set", "location vector envelope is invalid")
    if vectors["schema_id"] != VECTOR_SCHEMA_ID or vectors["synthetic_only"] is not True:
        raise ValidationFailure("invalid-vector-set", "location vector identity or synthetic marker is invalid")
    endpoint = vectors["endpoint"]
    validate_endpoint(endpoint)
    platforms = vectors["platforms"]
    if not isinstance(platforms, list) or [item.get("platform") for item in platforms if isinstance(item, dict)] != ["macos", "windows", "linux"]:
        raise ValidationFailure("invalid-vector-set", "macOS, Windows, and Linux cases are required in order")

    platform_results: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="artifact-memory-location-") as temporary:
        for item in platforms:
            if not isinstance(item, dict) or set(item) != {"platform", "layout_style", "root_token"}:
                raise ValidationFailure("invalid-vector", "platform vector fields are invalid")
            platform = item["platform"]
            local_root = Path(temporary) / item["root_token"]
            local_root.mkdir()
            resolution = resolve(
                [{"endpoint_ref": endpoint["endpoint_ref"], "platform": platform, "root": str(local_root), "authorized": True}],
                endpoint["endpoint_ref"],
                vectors["relative_path"],
            )
            if resolution["outcome"] != "resolved":
                raise ValidationFailure("vector-mismatch", f"logical resolution failed for {platform}")
            discovery = {
                "schema_id": "artifact-memory/endpoint-discovery-evidence/v1",
                "evidence_id": f"endpoint-discovery-evidence://synthetic/{platform}",
                "endpoint_ref": endpoint["endpoint_ref"],
                "observed_at": vectors["observed_at"],
                "evidence_kind": "test-double",
                "match_state": "matched",
                "evidence_digest": _digest_text(f"synthetic:{platform}:{item['root_token']}"),
                "limitations": ["synthetic discovery evidence; not endpoint identity"],
            }
            observation = {
                "schema_id": "artifact-memory/location-observation/v2",
                "observation_id": f"location-observation://synthetic/{platform}",
                "artifact_ref": vectors["artifact_ref"],
                "content_ref": vectors["content_ref"],
                "endpoint_ref": endpoint["endpoint_ref"],
                "relative_path": vectors["relative_path"],
                "presence_state": "present",
                "verification_state": "content-verified",
                "observed_at": vectors["observed_at"],
                "discovery_evidence_ref": discovery["evidence_id"],
                "authority_boundary": AUTHORITY_BOUNDARY,
            }
            validate_discovery_evidence(discovery)
            validate_location_observation(observation)
            platform_results.append({
                "platform": platform,
                "layout_style": item["layout_style"],
                "resolution_outcome": resolution["outcome"],
                "observation_id": observation["observation_id"],
                "discovery_evidence_id": discovery["evidence_id"],
            })

    body = {
        "outcome": "complete",
        "vector_set_digest": sha256_bytes(canonical_bytes(vectors)),
        "endpoint_ref": endpoint["endpoint_ref"],
        "relative_path": vectors["relative_path"],
        "platform_results": platform_results,
        "portable_fields": ["artifact_ref", "content_ref", "endpoint_ref", "relative_path"],
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": ["mount roots exist only in ephemeral local resolver configuration", "synthetic fixture does not claim physical-device interoperability"],
    }
    receipt = receipt_with_digest("artifact-memory/location-conformance-receipt/v1", "location-conformance-receipt://synthetic/", body)
    validate(receipt, load_schema("core", "location-conformance-receipt.v1.schema.json"))
    return receipt


def render_location_receipt(receipt: dict[str, Any]) -> str:
    lines = [
        "# Synthetic v0 location conformance receipt",
        "",
        f"- Outcome: `{receipt['outcome']}`",
        f"- Receipt: `{receipt['receipt_id']}`",
        f"- Vector set: `{receipt['vector_set_digest']}`",
        f"- Logical endpoint: `{receipt['endpoint_ref']}`",
        f"- Relative path: `{receipt['relative_path']}`",
        f"- Authority: `{receipt['authority_boundary']}`",
        "",
        "| Platform | Synthetic layout | Resolution | Observation |",
        "| --- | --- | --- | --- |",
    ]
    for result in receipt["platform_results"]:
        lines.append(f"| `{result['platform']}` | `{result['layout_style']}` | `{result['resolution_outcome']}` | `{result['observation_id']}` |")
    lines.extend(["", "No mount root, hostname, provider URL, bearer URL, or credential is present in this receipt.", ""])
    return "\n".join(lines)
