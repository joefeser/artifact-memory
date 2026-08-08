"""Release-manifest validation without signing or publication authority."""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
import shlex
import stat
import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any, BinaryIO

from . import __version__
from .canonical import CanonicalizationFailure, expected_receipt_id, receipt_with_digest
from .extensions import ExtensionFailure, preserve_extensions
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json_bytes, validate


SSH_VERIFICATION_OUTPUT_PROFILE = "git-verify-tag-filtered-allowed-signers-v1"
SSH_FINGERPRINT_PATTERN = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")
ALLOWED_SIGNER_OPTIONS = ("namespaces=", "valid-after=", "valid-before=")
SIGNED_MANIFEST_TRAILER = "Artifact-Memory-Manifest-SHA256:"
RELEASE_VERIFICATION_SCHEMA_ID = "artifact-memory/release-candidate-verification-receipt/v2"
RELEASE_VERIFICATION_RECEIPT_PREFIX = "release-candidate-verification-receipt://"
RELEASE_ASSET_CHUNK_BYTES = 1024 * 1024


def validate_release_manifest(
    manifest: dict[str, Any],
    *,
    supported_required_extensions: Iterable[tuple[str, str]] | None = None,
) -> None:
    if isinstance(manifest, dict) and manifest.get("schema_id") == "artifact-memory/release-manifest/v1":
        validate(manifest, load_schema("core", "release-manifest.v1.schema.json"))
        if manifest["status"] == "release":
            raise ValidationFailure(
                "release-manifest-migration-required",
                "v1 manifests lack the identity and signing evidence required for release use",
                "$.status",
            )
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
    if manifest["status"] in {"release-candidate", "release"}:
        fingerprint = manifest["signature"]["public_key_fingerprint"]
        if not isinstance(fingerprint, str) or SSH_FINGERPRINT_PATTERN.fullmatch(fingerprint) is None:
            raise ValidationFailure(
                "release-fingerprint-migration-required",
                "legacy v2 release fingerprint must be replaced by the canonical owner-published fingerprint before release use",
                "$.signature.public_key_fingerprint",
            )
        version = manifest["release_id"].removeprefix("artifact-memory/")
        if manifest["signature"]["tag"] != version:
            raise ValidationFailure(
                "release-tag-mismatch",
                "declared release tag must match the release identifier",
                "$.signature.tag",
            )


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


def _validate_v2_release_candidate_manifest(manifest: Any) -> None:
    """Apply the shared non-Git release-candidate contract."""

    if not isinstance(manifest, dict):
        raise ValidationFailure(
            "release-candidate-manifest-not-object",
            "release candidate manifest must be a JSON object",
        )
    if manifest.get("schema_id") != "artifact-memory/release-manifest/v2":
        raise ValidationFailure(
            "release-candidate-schema-unsupported",
            "release candidate identity verification requires a v2 release manifest",
        )
    if manifest.get("status") not in {"release-candidate", "release"}:
        raise ValidationFailure(
            "release-candidate-status-invalid",
            "verification requires pending release-candidate or historical release status",
        )
    signature = manifest.get("signature")
    fingerprint = (
        signature.get("public_key_fingerprint") if isinstance(signature, dict) else None
    )
    try:
        _require_canonical_owner_fingerprint(fingerprint)
    except ValidationFailure as exc:
        raise ValidationFailure(
            "release-candidate-owner-fingerprint-invalid",
            "candidate manifest fingerprint must use canonical unpadded SHA-256 form",
            "$.signature.public_key_fingerprint",
        ) from exc
    try:
        validate_release_manifest(manifest)
    except ValidationFailure as exc:
        if exc.code == "release-fingerprint-migration-required":
            raise ValidationFailure(
                "release-candidate-owner-fingerprint-invalid",
                "candidate manifest fingerprint must use canonical unpadded SHA-256 form",
                "$.signature.public_key_fingerprint",
            ) from exc
        raise


def _open_regular_release_asset(asset_directory: Path, name: str) -> BinaryIO:
    """Open one staged regular file without a pathname-check/read race."""

    path = asset_directory / name
    descriptor = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        opened_metadata = os.fstat(descriptor)
        path_metadata = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened_metadata.st_mode)
            or not stat.S_ISREG(path_metadata.st_mode)
            or (opened_metadata.st_dev, opened_metadata.st_ino)
            != (path_metadata.st_dev, path_metadata.st_ino)
        ):
            raise OSError("not a regular file")
        stream = os.fdopen(descriptor, "rb")
        descriptor = -1
        return stream
    except OSError as exc:
        raise ValidationFailure(
            "release-candidate-asset-unavailable",
            "every manifest-listed release asset must be one staged regular file",
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _snapshot_release_asset(asset_directory: Path, name: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    byte_size = 0
    with _open_regular_release_asset(asset_directory, name) as stream:
        while chunk := stream.read(RELEASE_ASSET_CHUNK_BYTES):
            byte_size += len(chunk)
            digest.update(chunk)
    return byte_size, f"sha-256:{digest.hexdigest()}"


def _regular_release_asset_equals_bytes(
    asset_directory: Path,
    name: str,
    expected: bytes,
) -> bool:
    offset = 0
    with _open_regular_release_asset(asset_directory, name) as stream:
        while chunk := stream.read(RELEASE_ASSET_CHUNK_BYTES):
            if chunk != expected[offset : offset + len(chunk)]:
                return False
            offset += len(chunk)
    return offset == len(expected)


def _replay_git_output_against_asset(
    git_args: list[str],
    repository_root: Path,
    asset_directory: Path,
    asset_name: str,
) -> None:
    """Stream one Git reproduction and compare it with one opened staged asset."""

    process: subprocess.Popen[bytes] | None = None
    mismatch = False
    try:
        with _open_regular_release_asset(asset_directory, asset_name) as asset:
            process = subprocess.Popen(
                ["git", *git_args],
                cwd=repository_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            if process.stdout is None:
                raise OSError("Git replay stdout unavailable")
            while chunk := process.stdout.read(RELEASE_ASSET_CHUNK_BYTES):
                if chunk != asset.read(len(chunk)):
                    mismatch = True
                    break
            if not mismatch and asset.read(1):
                mismatch = True
            if mismatch and process.poll() is None:
                process.kill()
            return_code = process.wait()
    except OSError as exc:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        raise ValidationFailure(
            "release-candidate-asset-replay-failed",
            "release asset bytes could not be reproduced from the verified tag commit",
        ) from exc
    finally:
        if process is not None and process.stdout is not None:
            process.stdout.close()
    if mismatch:
        raise ValidationFailure(
            "release-candidate-asset-replay-mismatch",
            "staged release asset bytes do not match the verified tag commit",
        )
    if return_code != 0:
        raise ValidationFailure(
            "release-candidate-asset-replay-failed",
            "release asset bytes could not be reproduced from the verified tag commit",
        )


def _require_asset_directory(value: Any) -> Path:
    if value is None:
        raise ValidationFailure(
            "release-candidate-asset-directory-required",
            "asset-aware release verification requires an explicit staged-asset Path",
        )
    if not isinstance(value, Path):
        raise ValidationFailure(
            "release-candidate-asset-directory-invalid",
            "release candidate asset directory must be supplied as a Path",
        )
    return value


def _verify_release_assets(
    manifest: dict[str, Any],
    asset_directory: Path | None,
    repository_root: Path,
    tag_commit: str,
) -> dict[str, Any]:
    """Replay staged assets against the manifest, checksum file, and tagged source."""

    asset_directory = _require_asset_directory(asset_directory)
    try:
        resolved_assets = asset_directory.resolve(strict=True)
        if not resolved_assets.is_dir() or asset_directory.is_symlink():
            raise OSError("not a real directory")
    except OSError as exc:
        raise ValidationFailure(
            "release-candidate-asset-directory-invalid",
            "release verification requires an explicit real staged-asset directory",
        ) from exc

    initial = {
        artifact["name"]: _snapshot_release_asset(resolved_assets, artifact["name"])
        for artifact in manifest["artifacts"]
    }
    for artifact in manifest["artifacts"]:
        byte_size, digest = initial[artifact["name"]]
        if byte_size != artifact["byte_size"] or digest != artifact["sha256"]:
            raise ValidationFailure(
                "release-candidate-asset-digest-mismatch",
                "staged release asset size or digest does not match the signed manifest",
            )

    checksum_name = manifest["checksum_manifest"]["artifact_name"]
    expected_checksum = "".join(
        f"{artifact['sha256'].removeprefix('sha-256:')}  {artifact['name']}\n"
        for artifact in manifest["artifacts"]
        if artifact["name"] != checksum_name
    ).encode("ascii")
    if not _regular_release_asset_equals_bytes(
        resolved_assets,
        checksum_name,
        expected_checksum,
    ):
        raise ValidationFailure(
            "release-candidate-checksum-scope-mismatch",
            "staged SHA256SUMS must canonically cover every non-checksum manifest asset exactly once",
        )

    for artifact in manifest["artifacts"]:
        if artifact["kind"] == "checksum-file":
            continue
        if artifact["kind"] == "source-archive":
            prefix = artifact["name"].removesuffix(".tar") + "/"
            expected_provenance = (
                f"git archive --format=tar --prefix={prefix} {tag_commit}"
            )
            if artifact["provenance"] != expected_provenance:
                if manifest["status"] == "release":
                    raise ValidationFailure(
                        "release-candidate-historical-asset-replay-unsupported",
                        "historical release provenance without the strict replay profile remains readable but is not live-verifiable",
                    )
                raise ValidationFailure(
                    "release-candidate-asset-provenance-invalid",
                    "source archive provenance must bind the exact replay command and tag commit",
                )
            replay_args = [
                "archive",
                "--format=tar",
                f"--prefix={prefix}",
                tag_commit,
            ]
        elif artifact["kind"] == "documentation":
            match = re.fullmatch(
                r"exact bytes from ([0-9a-f]{40}):([A-Za-z0-9][A-Za-z0-9._/-]*)",
                artifact["provenance"],
            )
            if match is None or match.group(1) != tag_commit:
                if manifest["status"] == "release":
                    raise ValidationFailure(
                        "release-candidate-historical-asset-replay-unsupported",
                        "historical release provenance without the strict replay profile remains readable but is not live-verifiable",
                    )
                raise ValidationFailure(
                    "release-candidate-asset-provenance-invalid",
                    "documentation provenance must bind one safe path at the tagged commit",
                )
            source_path = Path(match.group(2))
            if (
                source_path.is_absolute()
                or source_path.as_posix() != match.group(2)
                or any(part in {"", ".", ".."} for part in source_path.parts)
            ):
                raise ValidationFailure(
                    "release-candidate-asset-provenance-invalid",
                    "documentation provenance must bind one safe path at the tagged commit",
                )
            replay_args = ["show", f"{tag_commit}:{source_path.as_posix()}"]
        else:
            raise ValidationFailure(
                "release-candidate-asset-kind-unsupported",
                "release asset replay does not support this manifest artifact kind",
            )
        _replay_git_output_against_asset(
            replay_args,
            repository_root,
            resolved_assets,
            artifact["name"],
        )

    final = {
        artifact["name"]: _snapshot_release_asset(resolved_assets, artifact["name"])
        for artifact in manifest["artifacts"]
    }
    if final != initial:
        raise ValidationFailure(
            "release-candidate-assets-changed",
            "staged release assets changed during verification",
        )
    return {
        "asset_replay": "exact-staged-bytes-and-tagged-source-v1",
        "verified_asset_count": len(initial),
        "checksum_manifest_sha256": initial[checksum_name][1],
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


def _ssh_ed25519_fingerprint(encoded_key: str) -> str:
    try:
        key_blob = base64.b64decode(encoded_key, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValidationFailure(
            "release-candidate-allowed-signers-invalid",
            "allowed signers file contains an invalid SSH public key",
        ) from exc
    fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(key_blob).digest()).decode("ascii").rstrip("=")
    if SSH_FINGERPRINT_PATTERN.fullmatch(fingerprint) is None:
        raise ValidationFailure(
            "release-candidate-allowed-signers-invalid",
            "SSH public key did not produce a canonical SHA-256 fingerprint",
        )
    return fingerprint


def _require_canonical_owner_fingerprint(value: Any) -> str:
    if not isinstance(value, str) or SSH_FINGERPRINT_PATTERN.fullmatch(value) is None:
        raise ValidationFailure(
            "release-candidate-owner-fingerprint-invalid",
            "owner-published fingerprint must use canonical unpadded SHA-256 form",
        )
    return value


def _matching_allowed_signer_lines(
    path: Path,
    expected_fingerprint: str,
) -> tuple[list[str], bytes, Path]:
    """Select direct Ed25519 keys matching the manifest fingerprint."""

    try:
        resolved_path = path.resolve(strict=True)
        source_bytes = resolved_path.read_bytes()
        lines = source_bytes.decode("utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValidationFailure(
            "release-candidate-allowed-signers-invalid",
            "configured SSH allowed signers file could not be read as UTF-8 text",
        ) from exc
    expected_fingerprint = _require_canonical_owner_fingerprint(expected_fingerprint)
    matches: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            fields = shlex.split(line, comments=False, posix=True)
        except ValueError as exc:
            raise ValidationFailure(
                "release-candidate-allowed-signers-invalid",
                "configured SSH allowed signers file contains malformed syntax",
            ) from exc
        if len(fields) < 3:
            raise ValidationFailure(
                "release-candidate-allowed-signers-invalid",
                "configured SSH allowed signers file contains an incomplete record",
            )
        key_index = 1
        cert_authority = False
        while key_index < len(fields):
            field = fields[key_index]
            if field == "cert-authority":
                cert_authority = True
                key_index += 1
                continue
            if field.startswith(ALLOWED_SIGNER_OPTIONS):
                key_index += 1
                continue
            break
        if cert_authority or key_index + 1 >= len(fields):
            continue
        key_type = fields[key_index]
        if key_type != "ssh-ed25519" or "-cert-" in key_type:
            continue
        if _ssh_ed25519_fingerprint(fields[key_index + 1]) == expected_fingerprint:
            matches.append(raw_line)
    if not matches:
        raise ValidationFailure(
            "release-candidate-expected-signer-unavailable",
            "configured SSH allowed signers file does not contain the manifest's direct Ed25519 key",
        )
    return matches, source_bytes, resolved_path


def _signed_manifest_digest(tag_object: bytes) -> str:
    """Extract the one manifest digest covered by the annotated-tag signature."""

    try:
        tag_text = tag_object.decode("utf-8")
    except UnicodeError as exc:
        raise ValidationFailure(
            "release-candidate-manifest-binding-invalid",
            "annotated tag manifest binding must be UTF-8 text",
        ) from exc
    signature_boundary = "-----BEGIN SSH SIGNATURE-----"
    if tag_text.count(signature_boundary) != 1:
        raise ValidationFailure(
            "release-candidate-manifest-binding-invalid",
            "annotated tag must contain exactly one SSH signature boundary",
        )
    signed_text = tag_text.split(signature_boundary, 1)[0]
    matches = [
        line.removeprefix(SIGNED_MANIFEST_TRAILER).strip()
        for line in signed_text.splitlines()
        if line.startswith(SIGNED_MANIFEST_TRAILER)
    ]
    if len(matches) != 1 or re.fullmatch(r"sha-256:[0-9a-f]{64}", matches[0]) is None:
        raise ValidationFailure(
            "release-candidate-manifest-binding-invalid",
            "signed annotated tag must contain exactly one valid manifest SHA-256 trailer",
        )
    return matches[0]


def validate_release_candidate_verification_receipt(receipt: dict[str, Any]) -> None:
    schema_id = receipt.get("schema_id") if isinstance(receipt, dict) else None
    schema_files = {
        "artifact-memory/release-candidate-verification-receipt/v1": (
            "release-candidate-verification-receipt.v1.schema.json"
        ),
        "artifact-memory/release-candidate-verification-receipt/v2": (
            "release-candidate-verification-receipt.v2.schema.json"
        ),
    }
    schema_file = schema_files.get(schema_id)
    if schema_file is None:
        raise ValidationFailure(
            "release-candidate-receipt-schema-unsupported",
            "release verification receipt requires a supported versioned schema",
        )
    validate(
        receipt,
        load_schema("core", schema_file),
    )
    if len(
        {
            receipt["head_commit"],
            receipt["tag_commit"],
            receipt["manifest_source_commit"],
        }
    ) != 1:
        raise ValidationFailure(
            "release-candidate-receipt-evidence-incoherent",
            "receipt HEAD, tag commit, and manifest source commit must identify one commit",
        )
    expected_version = receipt["tag"].removeprefix("v")
    if (
        receipt["release_id"] != f"artifact-memory/{receipt['tag']}"
        or receipt["manifest_package_version"] != expected_version
        or receipt["package_version"] != expected_version
    ):
        raise ValidationFailure(
            "release-candidate-receipt-evidence-incoherent",
            "receipt tag, release identifier, and package versions must identify one release",
        )
    try:
        expected_id = expected_receipt_id(receipt, RELEASE_VERIFICATION_RECEIPT_PREFIX)
    except CanonicalizationFailure as exc:
        raise ValidationFailure(
            "release-candidate-receipt-noncanonical",
            "release verification receipt contains noncanonical content",
        ) from exc
    if receipt["receipt_id"] != expected_id:
        raise ValidationFailure(
            "release-candidate-receipt-identity-mismatch",
            "release verification receipt identity does not match its content",
        )


def render_release_candidate_verification_receipt(receipt: dict[str, Any]) -> str:
    validate_release_candidate_verification_receipt(receipt)
    asset_lines = ""
    if receipt["schema_id"] == "artifact-memory/release-candidate-verification-receipt/v2":
        asset_lines = (
            f"- Asset replay: `{receipt['asset_replay']}` ({receipt['verified_asset_count']} assets)\n"
            f"- SHA256SUMS digest: `{receipt['checksum_manifest_sha256']}`\n"
        )
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
        + asset_lines
        + f"- Repository scope: `{receipt['repository_scope']}`\n"
        f"- Checkout isolation: `{receipt['checkout_isolation']}`\n"
        f"- Concurrent mutation detection: `{receipt['concurrent_mutation_detection']}`\n"
        f"- Owner publication authorization evaluated: `{str(receipt['owner_publication_authorization_evaluated']).lower()}`\n"
        f"- Repository settings evidence evaluated: `{str(receipt['repository_settings_evidence_evaluated']).lower()}`\n"
        f"- Authority boundary: {receipt['authority_boundary']}\n"
        "- Limitations:\n"
        + "".join(f"  - {limitation}\n" for limitation in receipt["limitations"])
    )


def verify_checked_out_release_candidate(
    manifest_path: Path,
    tag: str,
    repository: Path,
    *,
    asset_directory: Path | None = None,
    owner_fingerprint: str,
    isolated_checkout: bool,
) -> dict[str, Any]:
    resolved_manifest = manifest_path.resolve()
    try:
        manifest_bytes = resolved_manifest.read_bytes()
    except OSError as exc:
        raise ValidationFailure("release-candidate-manifest-invalid", "release manifest could not be read") from exc
    manifest = load_json_bytes(manifest_bytes)
    if not isinstance(manifest, dict):
        raise ValidationFailure("release-candidate-manifest-invalid", "release manifest must be an object")
    asset_directory = _require_asset_directory(asset_directory)
    repository_root = _repository_root(repository)
    tag_ref = f"refs/tags/{tag}"
    try:
        object_format = subprocess.check_output(
            ["git", "rev-parse", "--show-object-format"], cwd=repository_root, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValidationFailure(
            "release-candidate-object-format-unavailable",
            "Git object format could not be determined for the explicit checkout",
        ) from exc
    if object_format != "sha1":
        raise ValidationFailure(
            "release-candidate-object-format-unsupported",
            "v0 release verification supports only SHA-1 Git object identifiers",
        )
    _validate_v2_release_candidate_manifest(manifest)
    if manifest["signature"]["tag"] != tag:
        raise ValidationFailure(
            "release-candidate-tag-mismatch",
            "requested tag must match the v2 release manifest signature",
        )
    owner_fingerprint = _require_canonical_owner_fingerprint(owner_fingerprint)
    manifest_fingerprint = _require_canonical_owner_fingerprint(
        manifest["signature"]["public_key_fingerprint"]
    )
    if manifest_fingerprint != owner_fingerprint:
        raise ValidationFailure(
            "release-candidate-owner-fingerprint-mismatch",
            "release manifest signer must match the independently supplied owner fingerprint",
        )
    if isolated_checkout is not True:
        raise ValidationFailure(
            "release-candidate-isolation-required",
            "release verification requires caller-asserted exclusive control of a fresh isolated checkout",
        )
    try:
        allowed_signers_setting = subprocess.check_output(
            ["git", "config", "--path", "--get", "gpg.ssh.allowedSignersFile"],
            cwd=repository_root,
            text=True,
        ).strip()
        tag_object_id = subprocess.check_output(
            ["git", "rev-parse", tag_ref], cwd=repository_root, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValidationFailure(
            "release-candidate-git-verification-failed",
            "release tag or SSH allowed-signers configuration could not be resolved",
        ) from exc
    allowed_signers_path = Path(allowed_signers_setting)
    if not allowed_signers_path.is_absolute():
        allowed_signers_path = repository_root / allowed_signers_path
    matching_signers, allowed_signers_bytes, resolved_allowed_signers_path = (
        _matching_allowed_signer_lines(allowed_signers_path, owner_fingerprint)
    )
    try:
        with tempfile.TemporaryDirectory(prefix="artifact-memory-release-") as temporary:
            filtered_allowed_signers = Path(temporary) / "allowed_signers"
            filtered_allowed_signers.write_text("\n".join(matching_signers) + "\n", encoding="utf-8")
            subprocess.run(
                [
                    "git",
                    "-c",
                    f"gpg.ssh.allowedSignersFile={filtered_allowed_signers}",
                    "verify-tag",
                    "--raw",
                    tag_object_id,
                ],
                check=True,
                cwd=repository_root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        head_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repository_root, text=True
        ).strip()
        head_symbolic_name = subprocess.check_output(
            ["git", "rev-parse", "--symbolic-full-name", "HEAD"],
            cwd=repository_root,
            text=True,
        ).strip()
        tag_commit = subprocess.check_output(
            ["git", "rev-parse", f"{tag_object_id}^{{commit}}"], cwd=repository_root, text=True
        ).strip()
        tag_type = subprocess.check_output(
            ["git", "cat-file", "-t", tag_object_id], cwd=repository_root, text=True
        ).strip()
        tag_object = subprocess.check_output(
            ["git", "cat-file", "tag", tag_object_id], cwd=repository_root
        )
        tree_listing = subprocess.check_output(
            ["git", "ls-tree", "-r", "--full-tree", f"{tag_object_id}^{{commit}}"], cwd=repository_root
        )
    except OSError as exc:
        raise ValidationFailure(
            "release-candidate-git-verification-failed",
            "signed release tag or Git identity could not be verified",
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise ValidationFailure(
            "release-candidate-git-verification-failed",
            "signed release tag or Git identity could not be verified",
        ) from exc
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
    identity = validate_release_candidate_identity(
        manifest,
        tag=tag,
        head_commit=head_commit,
        tag_commit=tag_commit,
        package_version=__version__,
    )
    asset_evidence = _verify_release_assets(
        manifest,
        asset_directory,
        repository_root,
        tag_commit,
    )
    try:
        final_tag_object_id = subprocess.check_output(
            ["git", "rev-parse", tag_ref], cwd=repository_root, text=True
        ).strip()
        final_head_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repository_root, text=True
        ).strip()
        final_head_symbolic_name = subprocess.check_output(
            ["git", "rev-parse", "--symbolic-full-name", "HEAD"],
            cwd=repository_root,
            text=True,
        ).strip()
        final_allowed_signers_setting = subprocess.check_output(
            ["git", "config", "--path", "--get", "gpg.ssh.allowedSignersFile"],
            cwd=repository_root,
            text=True,
        ).strip()
        final_allowed_signers_path = Path(final_allowed_signers_setting)
        if not final_allowed_signers_path.is_absolute():
            final_allowed_signers_path = repository_root / final_allowed_signers_path
        final_resolved_allowed_signers_path = final_allowed_signers_path.resolve(strict=True)
        final_allowed_signers_bytes = final_resolved_allowed_signers_path.read_bytes()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValidationFailure(
            "release-candidate-git-verification-failed",
            "final signed release tag, Git identity, or signer policy could not be verified",
        ) from exc
    if final_tag_object_id != tag_object_id:
        raise ValidationFailure(
            "release-candidate-tag-ref-changed",
            "release tag ref changed during verification",
        )
    if (
        final_resolved_allowed_signers_path != resolved_allowed_signers_path
        or final_allowed_signers_bytes != allowed_signers_bytes
    ):
        raise ValidationFailure(
            "release-candidate-signer-policy-changed",
            "configured SSH allowed-signers policy changed during verification",
        )
    if head_symbolic_name != "HEAD" or final_head_symbolic_name != "HEAD":
        raise ValidationFailure(
            "release-candidate-head-not-detached",
            "release verification requires a detached HEAD",
        )
    if final_head_commit != head_commit:
        raise ValidationFailure(
            "release-candidate-head-changed",
            "HEAD changed during release verification",
        )
    body: dict[str, Any] = {
        **identity,
        **asset_evidence,
        "tag_object_id": tag_object_id,
        "manifest_sha256": manifest_digest,
        "manifest_binding": "signed-annotated-tag-trailer-v1",
        "manifest_tree_digest": tree_digest,
        "verified_signer_fingerprint": owner_fingerprint,
        "signing_key_generation": manifest["signature"]["key_generation"],
        "annotated_tag_verified": True,
        "signature_algorithm": "ssh-ed25519",
        "verification_output_profile": SSH_VERIFICATION_OUTPUT_PROFILE,
        "repository_scope": "explicit-git-checkout",
        "checkout_isolation": "caller-asserted-exclusive-fresh-checkout",
        "concurrent_mutation_detection": "initial-final-endpoint-equality-no-aba-detection",
        "owner_publication_authorization_evaluated": False,
        "repository_settings_evidence_evaluated": False,
        "authority_boundary": manifest["authority_boundary"],
        "limitations": [
            *manifest["limitations"],
            "owner publication authorization and explicit visibility approval were not evaluated",
            "required repository-settings evidence was not evaluated",
            "checkout isolation is caller-asserted and endpoint checks do not detect ABA mutations",
        ],
    }
    receipt = receipt_with_digest(
        RELEASE_VERIFICATION_SCHEMA_ID,
        RELEASE_VERIFICATION_RECEIPT_PREFIX,
        body,
    )
    validate_release_candidate_verification_receipt(receipt)
    return receipt
