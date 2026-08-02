"""Replay the synthetic issue #8 artifact/version lineage vectors."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_lineage import validate_artifact_lineage
from .canonical import canonical_bytes, receipt_with_digest, sha256_bytes
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, validate


def render_artifact_lineage_receipt(receipt: dict[str, Any]) -> str:
    roles = receipt["role_counts"]
    return (
        "# Artifact and immutable-version conformance receipt\n\n"
        f"- Outcome: `{receipt['outcome']}`\n"
        f"- Artifact: `{receipt['artifact_ref']}`\n"
        f"- Retained versions: {receipt['version_count']}\n"
        f"- Roles: original={roles['original']}, normalized={roles['normalized']}, redacted={roles['redacted']}, derived={roles['derived']}, released={roles['released']}\n"
        f"- Content bindings: {receipt['content_binding_count']}\n"
        f"- Lineage relationships: {receipt['lineage_relationship_count']}\n"
        f"- Explicit supersessions: {receipt['supersession_count']}\n"
        f"- Vector-set digest: `{receipt['vector_set_digest']}`\n\n"
        "The fixture is newly authored synthetic data. It proves logical artifact identity, immutable retained revisions, multi-content binding, typed derivative lineage, and explicit supersession without treating content, paths, or provenance as authenticity or authority.\n"
    )


def run_artifact_lineage_conformance(vector_path: Path) -> dict[str, Any]:
    vectors = load_json(vector_path)
    if not isinstance(vectors, dict) or vectors.get("synthetic") is not True:
        raise ValidationFailure("invalid-vector", "artifact lineage vectors must declare synthetic provenance")
    artifact = vectors.get("artifact")
    versions = vectors.get("versions")
    if not isinstance(artifact, dict) or not isinstance(versions, list) or not all(isinstance(item, dict) for item in versions):
        raise ValidationFailure("invalid-vector", "artifact lineage vectors are malformed")
    validate_artifact_lineage(artifact, versions)
    role_counts = {role: sum(item["role"] == role for item in versions) for role in ("original", "normalized", "redacted", "derived", "released")}
    relationships = [relationship for version in versions for relationship in version["relationships"]]
    body = {
        "outcome": "complete",
        "synthetic": True,
        "artifact_ref": artifact["artifact_id"],
        "version_count": len(versions),
        "role_counts": role_counts,
        "content_binding_count": sum(len(item["content_refs"]) for item in versions),
        "multi_content_version_count": sum(len(item["content_refs"]) > 1 for item in versions),
        "lineage_relationship_count": len(relationships),
        "supersession_count": sum(item["type"] == "supersedes" for item in relationships),
        "retained_history": all(version["version_id"] for version in versions),
        "vector_set_digest": sha256_bytes(canonical_bytes(vectors)),
        "claims": [
            "artifact identity is logical and separate from versions and content",
            "every non-original role names typed source lineage",
            "supersession points to an earlier retained version without overwriting it",
            "one immutable version can bind one or more exact content objects",
        ],
        "limitations": [
            "synthetic lineage does not establish source truth, authenticity, custody, or disclosure permission",
            "v0 validates a bounded supplied history and does not claim that undisclosed versions do not exist",
        ],
    }
    receipt = receipt_with_digest(
        "artifact-memory/artifact-lineage-conformance-receipt/v1",
        "artifact-lineage-conformance-receipt://",
        body,
    )
    validate(receipt, load_schema("core", "artifact-lineage-conformance-receipt.v1.schema.json"))
    return receipt
