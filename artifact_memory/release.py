"""Release-manifest validation without signing or publication authority."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from . import __version__
from .canonical import receipt_with_digest
from .extensions import ExtensionFailure, preserve_extensions
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json_bytes, validate


SSH_VERIFICATION_LINE = re.compile(
    r'^Good "git" signature for .+ with ED25519 key '
    r'(?P<fingerprint>SHA256:[A-Za-z0-9+/]{20,}={0,2})$'
)
SSH_VERIFICATION_OUTPUT_PROFILE = "git-verify-tag-ssh-c-locale-v1"
SIGNED_MANIFEST_TRAILER = "Artifact-Memory-Manifest-SHA256:"
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

    _validate_v2_release_candidate_manifest(manifest)
    expected_version = tag.removeprefix("v")
    if manifest["release_id"] != f"artifact-memory/{tag}":
        raise ValidationFailure("release-candidate-id-mismatch", "release identifier must match the verified tag")
    if manifest["signature"]["tag"] != tag:
        raise ValidationFailure("release-candidate-tag-mismatch", "requested tag must match the v2 release manifest signature")
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


def _validate_v2_release_candidate_manifest(manifest: dict[str, Any]) -> None:
    """Apply the shared non-Git release-candidate contract."""

    if manifest.get("schema_id") != "artifact-memory/release-manifest/v2":
        raise ValidationFailure(
            "release-candidate-schema-unsupported",
            "release candidate identity verification requires a v2 release manifest",
        )
    validate_release_manifest(manifest)
    if manifest["status"] != "release":
        raise ValidationFailure("release-candidate-status-invalid", "candidate manifest must have release status")


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
            f"Git verification must emit exactly one SSH signer record supported by {SSH_VERIFICATION_OUTPUT_PROFILE}",
        )
    return matches[0]


def _signed_manifest_digest(tag_object: bytes) -> str:
    """Extract the one manifest digest covered by the annotated-tag signature."""

    try:
        unsigned_diagnostics = tag_object.decode("utf-8").split("-----BEGIN SSH SIGNATURE-----", 1)[0]
    except UnicodeError as exc:
        raise ValidationFailure(
            "release-candidate-manifest-binding-invalid",
            "annotated tag manifest binding must be UTF-8 text",
        ) from exc
    matches = [
        line.removeprefix(SIGNED_MANIFEST_TRAILER).strip()
        for line in unsigned_diagnostics.splitlines()
        if line.startswith(SIGNED_MANIFEST_TRAILER)
    ]
    if len(matches) != 1 or re.fullmatch(r"sha-256:[0-9a-f]{64}", matches[0]) is None:
        raise ValidationFailure(
            "release-candidate-manifest-binding-invalid",
            "signed annotated tag must contain exactly one valid manifest SHA-256 trailer",
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
        f"- Tag object: `{receipt['tag_object_id']}`\n"
        f"- Tag commit: `{receipt['tag_commit']}`\n"
        f"- HEAD commit: `{receipt['head_commit']}`\n"
        f"- Manifest source commit: `{receipt['manifest_source_commit']}`\n"
        f"- Manifest SHA-256: `{receipt['manifest_sha256']}`\n"
        f"- Manifest binding: `{receipt['manifest_binding']}`\n"
        f"- Manifest tree digest: `{receipt['manifest_tree_digest']}`\n"
        f"- Manifest package version: `{receipt['manifest_package_version']}`\n"
        f"- Installed package version: `{receipt['package_version']}`\n"
        f"- Verified signer: `{receipt['verified_signer_fingerprint']}`\n"
        f"- Signing key generation: `{receipt['signing_key_generation']}`\n"
        f"- Annotated tag verified: `{str(receipt['annotated_tag_verified']).lower()}`\n"
        f"- Verification output profile: `{receipt['verification_output_profile']}`\n"
        f"- Repository scope: `{receipt['repository_scope']}`\n"
        f"- Authority boundary: {receipt['authority_boundary']}\n"
        "- Limitations:\n"
        + "".join(f"  - {limitation}\n" for limitation in receipt["limitations"])
    )


def verify_checked_out_release_candidate(
    manifest_path: Path,
    tag: str,
    repository: Path,
) -> dict[str, Any]:
    resolved_manifest = manifest_path.resolve()
    try:
        manifest_bytes = resolved_manifest.read_bytes()
    except OSError as exc:
        raise ValidationFailure("release-candidate-manifest-invalid", "release manifest could not be read") from exc
    manifest = load_json_bytes(manifest_bytes)
    if not isinstance(manifest, dict):
        raise ValidationFailure("release-candidate-manifest-invalid", "release manifest must be an object")
    _validate_v2_release_candidate_manifest(manifest)
    if manifest["signature"]["tag"] != tag:
        raise ValidationFailure(
            "release-candidate-tag-mismatch",
            "requested tag must match the v2 release manifest signature",
        )
    repository_root = _repository_root(repository)
    tag_ref = f"refs/tags/{tag}"
    try:
        verification = subprocess.run(
            ["git", "verify-tag", "--raw", tag_ref],
            check=True,
            cwd=repository_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
        head_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repository_root, text=True
        ).strip()
        tag_commit = subprocess.check_output(
            ["git", "rev-parse", f"{tag_ref}^{{commit}}"], cwd=repository_root, text=True
        ).strip()
        tag_object_id = subprocess.check_output(
            ["git", "rev-parse", tag_ref], cwd=repository_root, text=True
        ).strip()
        tag_type = subprocess.check_output(
            ["git", "cat-file", "-t", tag_ref], cwd=repository_root, text=True
        ).strip()
        tag_object = subprocess.check_output(
            ["git", "cat-file", "tag", tag_ref], cwd=repository_root
        )
        tree_listing = subprocess.check_output(
            ["git", "ls-tree", "-r", "--full-tree", f"{tag_ref}^{{commit}}"], cwd=repository_root
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValidationFailure("release-candidate-git-verification-failed", "signed release tag or Git identity could not be verified") from exc
    if tag_type != "tag":
        raise ValidationFailure(
            "release-candidate-tag-not-annotated",
            "release tag must be an owner-signed annotated tag object",
        )
    manifest_digest = f"sha-256:{hashlib.sha256(manifest_bytes).hexdigest()}"
    if _signed_manifest_digest(tag_object) != manifest_digest:
        raise ValidationFailure(
            "release-candidate-manifest-binding-mismatch",
            "release manifest digest must match the digest in the verified signed tag",
        )
    tree_digest = f"sha-256:{hashlib.sha256(tree_listing).hexdigest()}"
    if manifest["source"]["tree_digest"] != tree_digest:
        raise ValidationFailure(
            "release-candidate-tree-digest-mismatch",
            "manifest source tree digest must match the verified tag tree",
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
    body: dict[str, Any] = {
        **identity,
        "tag_object_id": tag_object_id,
        "manifest_sha256": manifest_digest,
        "manifest_binding": "signed-annotated-tag-trailer-v1",
        "manifest_tree_digest": tree_digest,
        "verified_signer_fingerprint": expected_fingerprint,
        "signing_key_generation": manifest["signature"]["key_generation"],
        "annotated_tag_verified": True,
        "signature_algorithm": "ssh-ed25519",
        "verification_output_profile": SSH_VERIFICATION_OUTPUT_PROFILE,
        "repository_scope": "explicit-git-checkout",
        "authority_boundary": manifest["authority_boundary"],
        "limitations": manifest["limitations"],
    }
    receipt = receipt_with_digest(
        RELEASE_VERIFICATION_SCHEMA_ID,
        RELEASE_VERIFICATION_RECEIPT_PREFIX,
        body,
    )
    validate_release_candidate_verification_receipt(receipt)
    return receipt
