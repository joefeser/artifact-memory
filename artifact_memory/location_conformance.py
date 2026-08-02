"""Synthetic conformance evidence for portable storage locations."""

from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .canonical import canonical_bytes, receipt_with_digest, sha256_bytes
from .content import verify_content
from .location import AUTHORITY_BOUNDARY, validate_discovery_evidence, validate_endpoint, validate_location_observation, validate_logical_references
from .resolver import resolve
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, validate


VECTOR_SCHEMA_ID = "artifact-memory/location-conformance-vectors/v1"
ROOT_TOKEN = re.compile(r"^[A-Za-z0-9._~-]+$")


def _digest_text(value: str) -> str:
    return "sha-256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _native_root(platform: str, root_token: str) -> str:
    """Exercise each fixture's native mount spelling without exposing it."""
    if platform == "macos":
        return str(PurePosixPath("/Volumes") / root_token)
    if platform == "windows":
        return str(PureWindowsPath("R:/") / root_token)
    if platform == "linux":
        return str(PurePosixPath("/mnt") / root_token)
    raise ValidationFailure("invalid-vector", "unsupported platform")


def run_location_conformance(vector_path: Path) -> dict[str, Any]:
    vectors = load_json(vector_path)
    if not isinstance(vectors, dict) or set(vectors) != {"schema_id", "synthetic_only", "endpoint", "artifact_ref", "content_ref", "relative_path", "payload_utf8", "observed_at", "platforms"}:
        raise ValidationFailure("invalid-vector-set", "location vector envelope is invalid")
    if vectors["schema_id"] != VECTOR_SCHEMA_ID or vectors["synthetic_only"] is not True:
        raise ValidationFailure("invalid-vector-set", "location vector identity or synthetic marker is invalid")
    endpoint = vectors["endpoint"]
    validate_endpoint(endpoint)
    relative_path = vectors["relative_path"]
    validate_logical_references(
        vectors["artifact_ref"],
        vectors["content_ref"],
        endpoint["endpoint_ref"],
        relative_path,
    )
    portable_path = PurePosixPath(relative_path)
    payload_text = vectors["payload_utf8"]
    if not isinstance(payload_text, str):
        raise ValidationFailure("invalid-vector", "payload_utf8 must be a string")
    payload = payload_text.encode("utf-8")
    payload_digest = hashlib.sha256(payload).hexdigest()
    if vectors["content_ref"] != f"content://sha-256/{payload_digest}":
        raise ValidationFailure("vector-mismatch", "content_ref does not identify payload_utf8")
    content_object = {
        "schema_id": "artifact-memory/content-object/v2",
        "content_id": vectors["content_ref"],
        "digest": f"sha-256:{payload_digest}",
        "byte_size": len(payload),
        "media_type": "text/plain",
    }
    platforms = vectors["platforms"]
    if not isinstance(platforms, list) or [item.get("platform") for item in platforms if isinstance(item, dict)] != ["macos", "windows", "linux"]:
        raise ValidationFailure("invalid-vector-set", "macOS, Windows, and Linux cases are required in order")

    platform_results: list[dict[str, str]] = []
    seen_tokens: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="artifact-memory-location-") as temporary:
        temp_root = Path(temporary).resolve()
        for item in platforms:
            if not isinstance(item, dict) or set(item) != {"platform", "layout_style", "root_token"}:
                raise ValidationFailure("invalid-vector", "platform vector fields are invalid")
            platform = item["platform"]
            root_token = item["root_token"]
            if not isinstance(root_token, str) or ROOT_TOKEN.fullmatch(root_token) is None or root_token in {".", ".."} or root_token in seen_tokens:
                raise ValidationFailure("invalid-vector", "root_token must be a unique safe path segment")
            seen_tokens.add(root_token)
            native_root = _native_root(platform, root_token)
            local_root = (temp_root / root_token).resolve()
            if not local_root.is_relative_to(temp_root):
                raise ValidationFailure("invalid-vector", "root_token escapes the temporary root")
            try:
                local_root.mkdir()
                content_path = local_root.joinpath(*portable_path.parts).resolve()
                if not content_path.is_relative_to(local_root):
                    raise ValidationFailure("invalid-vector", "relative_path escapes the synthetic platform root")
                content_path.parent.mkdir(parents=True)
                content_path.write_bytes(payload)
            except OSError as exc:
                raise ValidationFailure("invalid-vector", "synthetic platform root could not be created") from exc
            resolution = resolve(
                [{"endpoint_ref": endpoint["endpoint_ref"], "platform": platform, "root": str(local_root), "authorized": True}],
                endpoint["endpoint_ref"],
                relative_path,
            )
            if resolution["outcome"] != "resolved":
                raise ValidationFailure("vector-mismatch", f"logical resolution failed for {platform}")
            verification = verify_content(content_path, content_object)
            if verification["outcome"] != "verified":
                raise ValidationFailure("vector-mismatch", f"content verification failed for {platform}")
            discovery = {
                "schema_id": "artifact-memory/endpoint-discovery-evidence/v1",
                "evidence_id": f"endpoint-discovery-evidence://synthetic/{platform}",
                "endpoint_ref": endpoint["endpoint_ref"],
                "observed_at": vectors["observed_at"],
                "evidence_kind": "test-double",
                "match_state": "matched",
                "evidence_digest": _digest_text(f"synthetic:{platform}:{native_root}"),
                "limitations": ["synthetic discovery evidence; not endpoint identity"],
            }
            observation = {
                "schema_id": "artifact-memory/location-observation/v2",
                "observation_id": f"location-observation://synthetic/{platform}",
                "artifact_ref": vectors["artifact_ref"],
                "content_ref": vectors["content_ref"],
                "endpoint_ref": endpoint["endpoint_ref"],
                "relative_path": relative_path,
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
                "native_layout_digest": _digest_text(native_root),
                "resolution_outcome": resolution["outcome"],
                "observation_id": observation["observation_id"],
                "discovery_evidence_id": discovery["evidence_id"],
            })

    body = {
        "outcome": "complete",
        "vector_set_digest": sha256_bytes(canonical_bytes(vectors)),
        "endpoint_ref": endpoint["endpoint_ref"],
        "relative_path": relative_path,
        "platform_results": platform_results,
        "portable_fields": ["artifact_ref", "content_ref", "endpoint_ref", "relative_path"],
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": ["native mount spellings are exercised by platform-specific pure-path adapters and retained only as digests", "synthetic fixture does not claim physical-device interoperability"],
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
        "| Platform | Synthetic layout | Native-layout digest | Resolution | Observation |",
        "| --- | --- | --- | --- | --- |",
    ]
    for result in receipt["platform_results"]:
        lines.append(
            f"| `{result['platform']}` | `{result['layout_style']}` | `{result['native_layout_digest']}` | "
            f"`{result['resolution_outcome']}` | `{result['observation_id']}` |"
        )
    lines.extend(["", "No mount root, hostname, provider URL, bearer URL, or credential is present in this receipt.", ""])
    return "\n".join(lines)
