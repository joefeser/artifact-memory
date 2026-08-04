"""Release-manifest validation without signing or publication authority."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from . import __version__
from .extensions import ExtensionFailure, preserve_extensions
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, validate


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


def validate_release_candidate_identity(
    manifest: dict[str, Any],
    *,
    tag: str,
    head_commit: str,
    tag_commit: str,
    package_version: str,
) -> dict[str, str]:
    """Fail closed unless tag, source, and installed package identify one release."""

    if manifest.get("schema_id") != "artifact-memory/release-manifest/v2":
        raise ValidationFailure(
            "release-candidate-schema-unsupported",
            "release candidate identity verification requires a v2 release manifest",
        )
    validate_release_manifest(manifest)
    expected_version = tag.removeprefix("v")
    if manifest["status"] != "release":
        raise ValidationFailure("release-candidate-status-invalid", "candidate manifest must have release status")
    if manifest["release_id"] != f"artifact-memory/{tag}":
        raise ValidationFailure("release-candidate-id-mismatch", "release identifier must match the verified tag")
    if manifest["source"]["commit"] != head_commit or tag_commit != head_commit:
        raise ValidationFailure("release-candidate-commit-mismatch", "tag, HEAD, and manifest source commit must match")
    manifest_version = manifest["surfaces"]["reference_cli"]["package_version"]
    if manifest_version != expected_version or package_version != expected_version:
        raise ValidationFailure(
            "release-candidate-version-mismatch",
            "tag, manifest package version, and installed package version must match",
        )
    return {
        "outcome": "pass",
        "tag": tag,
        "head_commit": head_commit,
        "tag_commit": tag_commit,
        "manifest_source_commit": manifest["source"]["commit"],
        "release_id": manifest["release_id"],
        "manifest_package_version": manifest_version,
        "package_version": package_version,
    }


def verify_checked_out_release_candidate(manifest_path: Path, tag: str) -> dict[str, str]:
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ValidationFailure("release-candidate-manifest-invalid", "release manifest must be an object")
    try:
        subprocess.run(
            ["git", "verify-tag", "--raw", tag],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        head_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        tag_commit = subprocess.check_output(["git", "rev-parse", f"{tag}^{{commit}}"], text=True).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValidationFailure("release-candidate-git-verification-failed", "signed release tag or Git identity could not be verified") from exc
    return validate_release_candidate_identity(
        manifest,
        tag=tag,
        head_commit=head_commit,
        tag_commit=tag_commit,
        package_version=__version__,
    )
