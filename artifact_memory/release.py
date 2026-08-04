"""Release-manifest validation without signing or publication authority."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from . import __version__
from .canonical import receipt_with_digest
from .extensions import ExtensionFailure, preserve_extensions
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, validate


SSH_VERIFICATION_LINE = re.compile(
    r'^Good "git" signature for .+ with ED25519 key '
    r'(?P<fingerprint>SHA256:[A-Za-z0-9+/]{20,}={0,2})$'
)
RELEASE_VERIFICATION_SCHEMA_ID = "artifact-memory/release-candidate-verification-receipt/v1"
RELEASE_VERIFICATION_RECEIPT_PREFIX = "release-candidate-verification-receipt://"


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


def _repository_root(repository: Path) -> Path:
    try:
        output = subprocess.check_output(
            ["git", "-C", str(repository.resolve()), "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.STDOUT,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValidationFailure(
            "release-candidate-repository-invalid",
            "release verification requires an explicit Git checkout",
        ) from exc
    return Path(output.strip()).resolve()


def _verified_ssh_fingerprint(output: str) -> str:
    matches = [
        match.group("fingerprint")
        for line in output.splitlines()
        if (match := SSH_VERIFICATION_LINE.fullmatch(line.strip())) is not None
    ]
    if len(matches) != 1:
        raise ValidationFailure(
            "release-candidate-signer-evidence-invalid",
            "Git verification must emit exactly one authoritative SSH signer record",
        )
    return matches[0]


def validate_release_candidate_verification_receipt(receipt: dict[str, Any]) -> None:
    validate(
        receipt,
        load_schema("core", "release-candidate-verification-receipt.v1.schema.json"),
    )
    body = {key: value for key, value in receipt.items() if key not in {"schema_id", "receipt_id"}}
    expected = receipt_with_digest(
        RELEASE_VERIFICATION_SCHEMA_ID,
        RELEASE_VERIFICATION_RECEIPT_PREFIX,
        body,
    )
    if receipt != expected:
        raise ValidationFailure(
            "release-candidate-receipt-identity-mismatch",
            "release verification receipt identity does not match its content",
        )


def render_release_candidate_verification_receipt(receipt: dict[str, Any]) -> str:
    validate_release_candidate_verification_receipt(receipt)
    return (
        "# Release candidate verification receipt\n\n"
        f"- Outcome: `{receipt['outcome']}`\n"
        f"- Receipt: `{receipt['receipt_id']}`\n"
        f"- Release/tag: `{receipt['release_id']}` / `{receipt['tag']}`\n"
        f"- Tag, HEAD, and manifest commit: `{receipt['head_commit']}`\n"
        f"- Package version: `{receipt['package_version']}`\n"
        f"- Verified signer: `{receipt['verified_signer_fingerprint']}`\n"
        f"- Signing key generation: `{receipt['signing_key_generation']}`\n"
        f"- Annotated tag verified: `{str(receipt['annotated_tag_verified']).lower()}`\n"
        f"- Repository scope: `{receipt['repository_scope']}`\n"
    )


def verify_checked_out_release_candidate(
    manifest_path: Path,
    tag: str,
    repository: Path,
) -> dict[str, str | bool]:
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ValidationFailure("release-candidate-manifest-invalid", "release manifest must be an object")
    validate_release_manifest(manifest)
    if manifest.get("schema_id") != "artifact-memory/release-manifest/v2":
        raise ValidationFailure(
            "release-candidate-schema-unsupported",
            "release candidate identity verification requires a v2 release manifest",
        )
    if manifest.get("status") != "release" or manifest.get("signature", {}).get("tag") != tag:
        raise ValidationFailure(
            "release-candidate-tag-mismatch",
            "requested tag must match the v2 release manifest signature",
        )
    repository_root = _repository_root(repository)
    try:
        verification = subprocess.run(
            ["git", "verify-tag", "--raw", tag],
            check=True,
            cwd=repository_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        head_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repository_root, text=True
        ).strip()
        tag_commit = subprocess.check_output(
            ["git", "rev-parse", f"{tag}^{{commit}}"], cwd=repository_root, text=True
        ).strip()
        tag_type = subprocess.check_output(
            ["git", "cat-file", "-t", f"refs/tags/{tag}"], cwd=repository_root, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValidationFailure("release-candidate-git-verification-failed", "signed release tag or Git identity could not be verified") from exc
    if tag_type != "tag":
        raise ValidationFailure(
            "release-candidate-tag-not-annotated",
            "release tag must be an owner-signed annotated tag object",
        )
    verified_fingerprint = _verified_ssh_fingerprint(verification.stderr)
    expected_fingerprint = manifest["signature"]["public_key_fingerprint"]
    if verified_fingerprint != expected_fingerprint:
        raise ValidationFailure(
            "release-candidate-signer-mismatch",
            "verified SSH signer fingerprint must match the release manifest",
        )
    identity = validate_release_candidate_identity(
        manifest,
        tag=tag,
        head_commit=head_commit,
        tag_commit=tag_commit,
        package_version=__version__,
    )
    body: dict[str, str | bool] = {
        **identity,
        "verified_signer_fingerprint": expected_fingerprint,
        "signing_key_generation": manifest["signature"]["key_generation"],
        "annotated_tag_verified": True,
        "signature_algorithm": "ssh-ed25519",
        "repository_scope": "explicit-git-checkout",
    }
    receipt = receipt_with_digest(
        RELEASE_VERIFICATION_SCHEMA_ID,
        RELEASE_VERIFICATION_RECEIPT_PREFIX,
        body,
    )
    validate_release_candidate_verification_receipt(receipt)
    return receipt
