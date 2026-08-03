"""Release-manifest validation without signing or publication authority."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .extensions import ExtensionFailure, preserve_extensions
from .schema_resources import load_schema
from .validator import ValidationFailure, validate


def validate_release_manifest(
    manifest: dict[str, Any],
    *,
    supported_required_extensions: Iterable[tuple[str, str]] | None = None,
) -> None:
    if isinstance(manifest, dict) and manifest.get("schema_id") == "artifact-memory/release-manifest/v1":
        validate(manifest, load_schema("core", "release-manifest.v1.schema.json"))
        return
    validate(manifest, load_schema("core", "release-manifest.v2.schema.json"))
    try:
        preserve_extensions(
            {},
            {
                "schema_id": "artifact-memory/extension-bundle/v1",
                "extensions": manifest.get("extensions", {}),
            },
            supported_required_extensions,
        )
    except ExtensionFailure as exc:
        raise ValidationFailure(exc.code, exc.message, exc.path) from exc
    names = [artifact["name"] for artifact in manifest["artifacts"]]
    if len(names) != len(set(names)):
        raise ValidationFailure("release-artifact-duplicate", "release artifact names must be unique", "$.artifacts")
    if len(names) != len({name.casefold() for name in names}):
        raise ValidationFailure("release-artifact-case-collision", "release artifact names must not collide by case", "$.artifacts")
    checksum_name = manifest["checksum_manifest"]["artifact_name"]
    checksum_artifacts = [artifact for artifact in manifest["artifacts"] if artifact["kind"] == "checksum-file"]
    if (
        len(checksum_artifacts) != 1
        or checksum_artifacts[0]["name"] != checksum_name
        or checksum_artifacts[0]["format"] != manifest["checksum_manifest"]["format"]
    ):
        raise ValidationFailure("release-checksum-manifest-missing", "checksum manifest must name one checksum-file artifact", "$.checksum_manifest.artifact_name")
    source_archives = [artifact for artifact in manifest["artifacts"] if artifact["kind"] == "source-archive"]
    if len(source_archives) != 1:
        raise ValidationFailure("release-source-archive-count", "release manifest requires exactly one source archive", "$.artifacts")
    if source_archives[0]["format"] != "git-archive-tar" or not source_archives[0]["name"].endswith(".tar"):
        raise ValidationFailure("release-source-archive-format", "v2 source archive must use the reproducible Git tar profile", "$.artifacts")
    if manifest["status"] == "preview" and manifest["attestations"]["state"] != "deferred-private-incubation":
        raise ValidationFailure("release-preview-attestation-invalid", "private preview cannot claim published attestations", "$.attestations.state")
    if manifest["status"] == "release":
        version = manifest["release_id"].removeprefix("artifact-memory/")
        if manifest["signature"]["tag"] != version:
            raise ValidationFailure("release-tag-mismatch", "owner-signed tag must match the release identifier", "$.signature.tag")
