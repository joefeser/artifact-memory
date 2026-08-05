"""Reproduce the unsigned release-preview manifest without publishing it."""

from __future__ import annotations

import io
import re
import subprocess
import tarfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .canonical import receipt_with_digest, sha256_bytes
from .release import validate_release_manifest
from .release_metadata import read_package_version, schema_inventory
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, validate


ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> bytes:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValidationFailure("release-source-unavailable", "release source evidence could not be read from Git") from exc


def _schema_inventory(commit: str) -> tuple[int, str]:
    paths = _git("ls-tree", "-r", "--name-only", commit, "artifact_memory/schemas").decode("utf-8").splitlines()
    return schema_inventory(
        _git("show", f"{commit}:{path}")
        for path in paths
        if path.endswith(".json")
    )


def run_release_conformance(
    fixture: Path,
    *,
    supported_required_extensions: Iterable[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    manifest_path = fixture / "v0-preview-manifest.v2.json"
    if not manifest_path.is_file():
        legacy_path = fixture / "v0-preview-manifest.json"
        if legacy_path.is_file():
            validate_release_manifest(load_json(legacy_path))
            raise ValidationFailure(
                "release-manifest-migration-required",
                "v1 preview evidence requires migration to v2 byte-size and checksum bindings",
            )
        raise ValidationFailure("release-preview-fixture-invalid", "selected fixture lacks the v0 preview manifest")
    manifest = load_json(manifest_path)
    validate_release_manifest(
        manifest,
        supported_required_extensions=supported_required_extensions,
    )
    commit = manifest["source"]["commit"]

    tree_listing = _git("ls-tree", "-r", "--full-tree", commit)
    tree_digest = sha256_bytes(tree_listing)
    if tree_digest != manifest["source"]["tree_digest"]:
        raise ValidationFailure("release-tree-digest-mismatch", "source tree digest does not reproduce")

    archive_name = next(artifact["name"] for artifact in manifest["artifacts"] if artifact["kind"] == "source-archive")
    prefix = archive_name.removesuffix(".tar") + "/"
    archive_bytes = _git("archive", "--format=tar", f"--prefix={prefix}", commit)
    archive_artifact = next(artifact for artifact in manifest["artifacts"] if artifact["name"] == archive_name)
    expected_provenance = f"git archive --format=tar --prefix={prefix} {commit}"
    if archive_artifact["provenance"] != expected_provenance:
        raise ValidationFailure("release-artifact-provenance-mismatch", "source archive provenance command is not exact")
    if len(archive_bytes) != archive_artifact["byte_size"] or sha256_bytes(archive_bytes) != archive_artifact["sha256"]:
        raise ValidationFailure("release-artifact-digest-mismatch", "source archive size or digest does not reproduce")
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as archive:
            names = set(archive.getnames())
    except (tarfile.TarError, UnicodeError) as exc:
        raise ValidationFailure("release-artifact-invalid", "source archive could not be parsed") from exc
    for required in (f"{prefix}README.md", f"{prefix}pyproject.toml"):
        if required not in names:
            raise ValidationFailure("release-artifact-content-missing", "source archive lacks an install or documentation input")
    if not any(name.startswith(f"{prefix}artifact_memory/") for name in names):
        raise ValidationFailure("release-artifact-content-missing", "source archive lacks package contents")

    reproduced_assets = {archive_name: archive_bytes}
    for artifact in manifest["artifacts"]:
        if artifact["kind"] in {"source-archive", "checksum-file"}:
            continue
        try:
            artifact_bytes = (fixture / artifact["name"]).read_bytes()
        except OSError as exc:
            raise ValidationFailure("release-artifact-unavailable", "release asset bytes are unavailable") from exc
        if len(artifact_bytes) != artifact["byte_size"] or sha256_bytes(artifact_bytes) != artifact["sha256"]:
            raise ValidationFailure("release-artifact-digest-mismatch", "release asset size or digest does not reproduce")
        reproduced_assets[artifact["name"]] = artifact_bytes

    checksum_name = manifest["checksum_manifest"]["artifact_name"]
    checksum_bytes = (fixture / checksum_name).read_bytes()
    checksum_artifact = next(artifact for artifact in manifest["artifacts"] if artifact["name"] == checksum_name)
    if len(checksum_bytes) != checksum_artifact["byte_size"] or sha256_bytes(checksum_bytes) != checksum_artifact["sha256"]:
        raise ValidationFailure("release-checksum-file-mismatch", "checksum manifest size or digest does not reproduce")
    try:
        lines = checksum_bytes.decode("ascii").splitlines()
    except UnicodeError as exc:
        raise ValidationFailure("release-checksum-encoding-invalid", "checksum manifest must be ASCII") from exc
    expected_assets = [artifact for artifact in manifest["artifacts"] if artifact["kind"] != "checksum-file"]
    parsed: dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if match is None or match.group(2) in parsed:
            raise ValidationFailure("release-checksum-format-invalid", "checksum manifest is not canonical sha256sum-v1")
        parsed[match.group(2)] = "sha-256:" + match.group(1)
    if parsed != {artifact["name"]: artifact["sha256"] for artifact in expected_assets}:
        raise ValidationFailure("release-checksum-scope-mismatch", "checksum manifest does not cover every non-checksum asset exactly once")
    for artifact in expected_assets:
        asset_bytes = reproduced_assets.get(artifact["name"])
        if asset_bytes is None or len(asset_bytes) != artifact["byte_size"] or sha256_bytes(asset_bytes) != artifact["sha256"]:
            raise ValidationFailure("release-artifact-digest-mismatch", "checksummed release asset bytes do not reproduce")

    schema_count, schema_digest = _schema_inventory(commit)
    if schema_count != manifest["surfaces"]["schemas"]["inventory_count"] or schema_digest != manifest["surfaces"]["schemas"]["inventory_digest"]:
        raise ValidationFailure("release-schema-inventory-mismatch", "schema inventory does not reproduce")
    package_version = read_package_version(_git("show", f"{commit}:pyproject.toml"))
    if package_version != manifest["surfaces"]["reference_cli"]["package_version"]:
        raise ValidationFailure("release-package-version-mismatch", "reference CLI package version does not reproduce")

    body = {
        "outcome": "pass",
        "release_id": manifest["release_id"],
        "status": manifest["status"],
        "source_commit": commit,
        "tree_digest": tree_digest,
        "source_archive_digest": archive_artifact["sha256"],
        "source_archive_byte_size": len(archive_bytes),
        "checksum_manifest_digest": checksum_artifact["sha256"],
        "schema_inventory_count": schema_count,
        "schema_inventory_digest": schema_digest,
        "package_version": package_version,
        "signature_state": manifest["signature"]["state"],
        "publication_state": "not-authorized",
        "claims": [
            "source tree, source archive, checksum manifest, schema inventory, and package version reproduce from the named commit",
            "preview signature and publication remain explicitly absent",
            "protocol, schema, CLI, adapter, and fixture surfaces carry separate version policies",
        ],
        "authority_boundary": manifest["authority_boundary"],
        "limitations": manifest["limitations"],
    }
    if "extensions" in manifest:
        body["extensions"] = manifest["extensions"]
    receipt = receipt_with_digest(
        "artifact-memory/release-conformance-receipt/v1",
        "release-conformance-receipt://",
        body,
    )
    validate(receipt, load_schema("core", "release-conformance-receipt.v1.schema.json"))
    return receipt


def render_release_conformance(receipt: dict[str, Any]) -> str:
    return (
        "# Release preview conformance receipt\n\n"
        f"- Outcome: `{receipt['outcome']}`\n"
        f"- Receipt: `{receipt['receipt_id']}`\n"
        f"- Preview: `{receipt['release_id']}`\n"
        f"- Source commit: `{receipt['source_commit']}`\n"
        f"- Source archive: `{receipt['source_archive_digest']}` ({receipt['source_archive_byte_size']} bytes)\n"
        f"- Schema inventory: {receipt['schema_inventory_count']} (`{receipt['schema_inventory_digest']}`)\n"
        f"- Reference CLI package: `{receipt['package_version']}`\n"
        f"- Signature: `{receipt['signature_state']}`\n"
        f"- Publication: `{receipt['publication_state']}`\n\n"
        "The preview reproduces public-safe release materials but is neither signed nor authorized for publication. Owner signing, anonymous public-clone verification, visibility change, and push-rule restoration remain pending.\n"
    )
