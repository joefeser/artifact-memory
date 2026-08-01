"""Logical artifact identity, immutable versions, and explicit lineage."""

from __future__ import annotations

import re
from typing import Any

from .extensions import ExtensionFailure, preserve_extensions
from .schema_resources import load_schema
from .validator import ValidationFailure, validate


ARTIFACT_AUTHORITY_BOUNDARY = "artifact identity grants no content access, execution, disclosure, mutation, authenticity, trust, or authorization"
VERSION_AUTHORITY_BOUNDARY = "artifact version lineage grants no content access, execution, disclosure, mutation, authenticity, trust, or authorization"
VERSION_ID = re.compile(r"^artifact-version://([A-Za-z0-9._~-]+)/([A-Za-z0-9._~-]+)/([1-9][0-9]*)$")
ROLE_SOURCE_RELATION = {
    "normalized": "normalized-from",
    "redacted": "redacted-from",
    "derived": "derived-from",
    "released": "released-from",
}
LINEAGE_RELATIONS = {*ROLE_SOURCE_RELATION.values(), "supersedes"}


def _validate_extensions(value: dict[str, Any]) -> None:
    try:
        preserve_extensions({}, {
            "schema_id": "artifact-memory/extension-bundle/v1",
            "extensions": value.get("extensions", {}),
        })
    except ExtensionFailure as exc:
        raise ValidationFailure(exc.code, exc.message, "$.extensions") from exc


def validate_artifact(artifact: dict[str, Any]) -> None:
    """Validate one stable logical artifact record."""
    validate(artifact, load_schema("core", "artifact.v1.schema.json"))
    _validate_extensions(artifact)


def _version_parts(version_id: str) -> tuple[str, int]:
    match = VERSION_ID.fullmatch(version_id)
    if match is None:
        raise ValidationFailure("artifact-version-identity-invalid", "artifact version identity is malformed", "$.version_id")
    artifact_id = f"artifact://{match.group(1)}/{match.group(2)}"
    return artifact_id, int(match.group(3))


def validate_artifact_version(version: dict[str, Any]) -> None:
    """Validate one immutable artifact version and its local invariants."""
    validate(version, load_schema("core", "artifact-version.v2.schema.json"))
    _validate_extensions(version)
    artifact_id, revision = _version_parts(version["version_id"])
    if artifact_id != version["artifact_id"] or revision != version["revision"]:
        raise ValidationFailure("artifact-version-identity-invalid", "version identity does not match artifact identity and revision")
    content_refs = version["content_refs"]
    if content_refs != sorted(set(content_refs)):
        raise ValidationFailure("artifact-version-content-invalid", "content references must be unique and sorted", "$.content_refs")
    provenance_keys = [(item["kind"], item["source_ref"]) for item in version["provenance"]]
    if len(provenance_keys) != len(set(provenance_keys)):
        raise ValidationFailure("artifact-version-provenance-invalid", "provenance entries must be unique", "$.provenance")
    relationship_keys = [(item["type"], item["target_ref"]) for item in version["relationships"]]
    if relationship_keys != sorted(set(relationship_keys)):
        raise ValidationFailure("artifact-version-relationship-invalid", "relationships must be unique and sorted", "$.relationships")
    if any(item["target_ref"] == version["version_id"] for item in version["relationships"]):
        raise ValidationFailure("artifact-version-relationship-invalid", "a version cannot relate to itself", "$.relationships")
    source_relation = ROLE_SOURCE_RELATION.get(version["role"])
    if source_relation and not any(item["type"] == source_relation for item in version["relationships"]):
        raise ValidationFailure("artifact-version-source-required", f"{version['role']} versions require {source_relation} lineage", "$.relationships")


def validate_artifact_lineage(artifact: dict[str, Any], versions: list[dict[str, Any]]) -> None:
    """Validate a bounded artifact history without treating omission as replacement."""
    validate_artifact(artifact)
    if not versions:
        raise ValidationFailure("artifact-version-missing", "artifact lineage requires at least one version", "$.versions")
    by_id: dict[str, dict[str, Any]] = {}
    revisions: set[int] = set()
    for index, version in enumerate(versions):
        try:
            validate_artifact_version(version)
        except ValidationFailure as exc:
            raise ValidationFailure(exc.code, exc.message, f"$.versions[{index}]{exc.path.removeprefix('$')}") from exc
        if version["artifact_id"] != artifact["artifact_id"]:
            raise ValidationFailure("artifact-version-artifact-mismatch", "version belongs to a different artifact", f"$.versions[{index}].artifact_id")
        if version["version_id"] in by_id or version["revision"] in revisions:
            raise ValidationFailure("artifact-version-duplicate", "version identities and revisions must be unique", f"$.versions[{index}]")
        by_id[version["version_id"]] = version
        revisions.add(version["revision"])
    if [item["revision"] for item in versions] != sorted(revisions):
        raise ValidationFailure("artifact-version-order-invalid", "versions must be sorted by revision", "$.versions")

    superseded_targets: set[str] = set()
    for index, version in enumerate(versions):
        for relationship in version["relationships"]:
            if relationship["type"] not in LINEAGE_RELATIONS:
                continue
            target = by_id.get(relationship["target_ref"])
            target_artifact_id, target_revision = _version_parts(relationship["target_ref"])
            if target_artifact_id == artifact["artifact_id"]:
                if target is None:
                    raise ValidationFailure("artifact-version-lineage-target-missing", "same-artifact lineage target is not retained", f"$.versions[{index}].relationships")
                if target_revision >= version["revision"]:
                    raise ValidationFailure("artifact-version-lineage-order-invalid", "lineage must point to an earlier retained revision", f"$.versions[{index}].relationships")
            if relationship["type"] == "supersedes":
                if target_artifact_id != artifact["artifact_id"] or target is None:
                    raise ValidationFailure("artifact-version-supersession-target-invalid", "supersession must name an earlier retained version of the same artifact", f"$.versions[{index}].relationships")
                if relationship["target_ref"] in superseded_targets:
                    raise ValidationFailure("artifact-version-supersession-conflict", "one retained version has multiple superseding successors", f"$.versions[{index}].relationships")
                superseded_targets.add(relationship["target_ref"])
