"""Prepare reproducible preview and release-candidate assets without signing authority."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .adapter_manifest import SUPPORTED_MANIFEST_SCHEMA_IDS
from .canonical import CanonicalizationFailure, expected_receipt_id, receipt_with_digest, sha256_bytes
from .release import SIGNED_MANIFEST_TRAILER, SSH_FINGERPRINT_PATTERN, validate_release_manifest
from .release_metadata import (
    read_package_version,
    read_runtime_version,
    schema_inventory,
    supported_adapter_manifest_schemas,
)
from .schema_resources import load_schema
from .validator import ValidationFailure, validate


AUTHORITY_BOUNDARY = (
    "release preparation grants no signing, tag, publication, visibility, or deployment authority"
)
RELEASE_PREPARATION_SCHEMAS = {
    "artifact-memory/release-preparation-receipt/v1": "release-preparation-receipt.v1.schema.json",
    "artifact-memory/release-preparation-receipt/v2": "release-preparation-receipt.v2.schema.json",
}
RELEASE_PREPARATION_RECEIPT_PREFIX = "release-preparation-receipt://"
RELEASE_CANDIDATE_PREPARATION_SCHEMAS = {
    "artifact-memory/release-candidate-preparation-receipt/v1": "release-candidate-preparation-receipt.v1.schema.json",
    "artifact-memory/release-candidate-preparation-receipt/v2": "release-candidate-preparation-receipt.v2.schema.json",
}
RELEASE_CANDIDATE_PREPARATION_SCHEMA_ID = (
    "artifact-memory/release-candidate-preparation-receipt/v1"
)
RELEASE_CANDIDATE_PREPARATION_RECEIPT_PREFIX = (
    "release-candidate-preparation-receipt://"
)


def _release_version(package_version: str, *, allow_development: bool) -> str:
    """Return the X.Y.Z release identity bound to one validated package version."""

    release_version = package_version.split(".dev", 1)[0]
    if not allow_development and release_version != package_version:
        raise ValidationFailure(
            "release-candidate-package-version-invalid",
            "release candidate package version must use final X.Y.Z form",
        )
    return release_version


def _preparation_schema_id(package_version: str, *, candidate: bool) -> str:
    """Preserve the frozen 0.1.0 receipt contract and negotiate v2 thereafter."""

    suffix = "release-candidate-preparation-receipt" if candidate else "release-preparation-receipt"
    version = "v1" if _release_version(package_version, allow_development=True) == "0.1.0" else "v2"
    return f"artifact-memory/{suffix}/{version}"


def _git(repository: Path, *args: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "-C", str(repository), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValidationFailure(
            "release-preparation-git-failed",
            "release preparation could not read the explicit Git repository",
        ) from exc


def _repository_root(repository: Path) -> Path:
    try:
        return Path(_git(repository, "rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve()
    except UnicodeError as exc:
        raise ValidationFailure(
            "release-preparation-repository-invalid",
            "release preparation requires a UTF-8-addressable Git checkout",
        ) from exc


def _exact_commit(repository: Path, candidate: str) -> str:
    try:
        commit = _git(repository, "rev-parse", "--verify", f"{candidate}^{{commit}}").decode("ascii").strip()
    except UnicodeError as exc:
        raise ValidationFailure(
            "release-preparation-candidate-invalid",
            "release preparation candidate is not an ASCII Git object identifier",
        ) from exc
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise ValidationFailure(
            "release-preparation-object-format-unsupported",
            "release preparation supports SHA-1-format Git repositories in v0",
        )
    if candidate != commit:
        raise ValidationFailure(
            "release-preparation-candidate-not-exact",
            "release preparation requires the exact full candidate commit identifier",
        )
    return commit


def _prepare_output(root: Path, output: Path) -> Path:
    if output.is_symlink():
        raise ValidationFailure(
            "release-preparation-output-invalid",
            "release output must not be a symbolic link",
        )
    resolved = output.resolve()
    if resolved.is_relative_to(root):
        raise ValidationFailure(
            "release-preparation-output-inside-repository",
            "release assets must be written outside the audited repository",
        )
    if resolved.exists() and (resolved.is_symlink() or not resolved.is_dir()):
        raise ValidationFailure(
            "release-preparation-output-invalid",
            "release output must be a real directory",
        )
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if output.is_symlink() or output.resolve() != resolved:
        raise ValidationFailure(
            "release-preparation-output-invalid",
            "release output changed during preparation",
        )
    if resolved.exists() and any(resolved.iterdir()):
        raise ValidationFailure(
            "release-preparation-output-not-empty",
            "release output directory must be empty",
        )
    return resolved


def _schema_inventory(repository: Path, commit: str) -> tuple[int, str]:
    paths = _git(
        repository,
        "ls-tree",
        "-r",
        "--name-only",
        commit,
        "artifact_memory/schemas",
    ).decode("utf-8").splitlines()
    return schema_inventory(
        _git(repository, "show", f"{commit}:{path}")
        for path in paths
        if path.endswith(".json")
    )


def _package_version(repository: Path, commit: str) -> str:
    return read_package_version(_git(repository, "show", f"{commit}:pyproject.toml"))


def _runtime_version(repository: Path, commit: str) -> str:
    try:
        source = _git(repository, "show", f"{commit}:artifact_memory/__init__.py")
    except ValidationFailure as exc:
        raise ValidationFailure(
            "release-runtime-version-unavailable",
            "release candidate runtime version source is unavailable at the exact commit",
        ) from exc
    return read_runtime_version(source)


def _regular_commit_file(repository: Path, commit: str, path: str) -> bytes:
    try:
        listing = _git(repository, "ls-tree", commit, "--", path).decode("utf-8")
        metadata, listed_path = listing.rstrip("\n").split("\t", 1)
        mode, object_type, _object_id = metadata.split(" ", 2)
    except (UnicodeError, ValueError, ValidationFailure) as exc:
        raise ValidationFailure(
            "release-candidate-notes-unavailable",
            "release candidate requires final release notes at the exact source commit",
        ) from exc
    if listed_path != path or mode not in {"100644", "100755"} or object_type != "blob":
        raise ValidationFailure(
            "release-candidate-notes-not-regular",
            "release candidate final release notes must be one regular Git file",
        )
    try:
        return _git(repository, "show", f"{commit}:{path}")
    except ValidationFailure as exc:
        raise ValidationFailure(
            "release-candidate-notes-unavailable",
            "release candidate requires final release notes at the exact source commit",
        ) from exc


def _supported_adapter_manifest_schemas(repository: Path, commit: str) -> list[str]:
    supported = supported_adapter_manifest_schemas(
        lambda: _git(
            repository,
            "ls-tree",
            "-r",
            "--name-only",
            commit,
            "artifact_memory/schemas/adapters",
        ).decode("utf-8").splitlines(),
        lambda path: _git(repository, "show", f"{commit}:{path}"),
        error_code_prefix="release-preparation",
    )
    if not supported:
        raise ValidationFailure(
            "release-preparation-adapter-contract-missing",
            "release source contains no supported adapter manifest schema",
        )
    if SUPPORTED_MANIFEST_SCHEMA_IDS[0] not in supported:
        raise ValidationFailure(
            "release-preparation-adapter-primary-schema-unsupported",
            "release preview preparation requires the v1 adapter manifest schema as the "
            "release surface's primary contract; v2-only candidates cannot yet publish previews",
        )
    return supported


def _release_surfaces(
    package_version: str,
    schema_count: int,
    schema_digest: str,
    adapter_manifest_schemas: list[str],
    *,
    stability: str,
) -> dict[str, Any]:
    return {
        "protocol": {"version": "v0", "stability": stability},
        "schemas": {
            "versioning": "independent-schema-id-vN",
            "inventory_count": schema_count,
            "inventory_digest": schema_digest,
            "inventory_digest_profile": "sha256-of-canonical-sorted-schema-id-array-v1",
        },
        "reference_cli": {
            "package_version": package_version,
            "stability": stability,
        },
        "adapters": {
            "versioning": "provider-contract-vN",
            "manifest_schema": "artifact-memory/adapter-manifest/v1",
            "supported_manifest_schemas": adapter_manifest_schemas,
        },
        "fixtures": {
            "versioning": "fixture-and-receipt-vN",
            "aggregate_schema": "artifact-memory/conformance-fixture-receipt/v1",
        },
    }


def _compatibility_policy() -> dict[str, str]:
    return {
        "unknown_optional": "preserve-without-interpretation",
        "unknown_required": "fail-closed",
        "breaking_change": "new-version-and-explicit-migration-or-rejection-rule",
        "deprecation_window": "at-least-one-minor-release-and-90-days-after-announcement",
        "pre_1_0_api_stability": "implementation-APIs-unstable-contracts-remain-versioned",
    }


def _write_exclusive(path: Path, content: bytes) -> None:
    try:
        with path.open("xb") as stream:
            stream.write(content)
    except OSError as exc:
        raise ValidationFailure(
            "release-preparation-output-invalid",
            "release staging rejected a conflicting output path",
        ) from exc


def _publish_output(output: Path, assets: dict[str, bytes]) -> None:
    """Stage, verify, and atomically expose one complete release directory."""

    try:
        staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    except OSError as exc:
        raise ValidationFailure(
            "release-preparation-output-invalid",
            "release staging directory could not be created",
        ) from exc
    published = False
    try:
        for name, content in assets.items():
            _write_exclusive(staging / name, content)
        for name, content in assets.items():
            try:
                persisted = (staging / name).read_bytes()
            except OSError as exc:
                raise ValidationFailure(
                    "release-preparation-output-invalid",
                    "release staging evidence could not be reread",
                ) from exc
            if persisted != content:
                raise ValidationFailure(
                    "release-preparation-output-invalid",
                    "release staging evidence changed before publication",
                )
        try:
            if output.exists() or output.is_symlink():
                output.rmdir()
            os.replace(staging, output)
            published = True
        except OSError as exc:
            raise ValidationFailure(
                "release-preparation-output-invalid",
                "release output changed before atomic publication",
            ) from exc
    finally:
        if not published:
            shutil.rmtree(staging, ignore_errors=True)


def validate_release_preparation_receipt(receipt: dict[str, Any]) -> None:
    """Validate one versioned unsigned-preview receipt and its version binding."""

    schema_id = receipt.get("schema_id") if isinstance(receipt, dict) else None
    schema_name = RELEASE_PREPARATION_SCHEMAS.get(schema_id)
    if schema_name is None:
        raise ValidationFailure(
            "release-preparation-receipt-schema-unsupported",
            "release preparation receipt schema is unsupported",
        )
    validate(receipt, load_schema("core", schema_name))
    if schema_id == "artifact-memory/release-preparation-receipt/v2":
        release_version = _release_version(
            receipt["package_version"],
            allow_development=True,
        )
        if release_version == "0.1.0":
            raise ValidationFailure(
                "release-preparation-receipt-version-mismatch",
                "the frozen 0.1.0 preview identity requires the v1 receipt contract",
            )
        if receipt["release_id"] != f"artifact-memory/v{release_version}-preview":
            raise ValidationFailure(
                "release-preparation-receipt-version-binding-invalid",
                "preview release identity does not match its package version",
            )
    try:
        expected_id = expected_receipt_id(
            receipt,
            RELEASE_PREPARATION_RECEIPT_PREFIX,
        )
    except CanonicalizationFailure as exc:
        raise ValidationFailure(
            "release-preparation-receipt-noncanonical",
            "release preparation receipt contains noncanonical content",
        ) from exc
    if receipt["receipt_id"] != expected_id:
        raise ValidationFailure(
            "release-preparation-receipt-identity-mismatch",
            "release preparation receipt identity does not match its content",
        )


def render_release_preparation_receipt(receipt: dict[str, Any]) -> str:
    """Render the validated unsigned preview preparation evidence."""

    validate_release_preparation_receipt(receipt)
    return (
        "# Unsigned release preview preparation receipt\n\n"
        f"- Outcome: `{receipt['outcome']}`\n"
        f"- Receipt: `{receipt['receipt_id']}`\n"
        f"- Preview: `{receipt['release_id']}`\n"
        f"- Source commit: `{receipt['source_commit']}`\n"
        f"- Source archive: `{receipt['source_archive_digest']}` ({receipt['source_archive_byte_size']} bytes)\n"
        f"- SHA256SUMS: `{receipt['checksum_manifest_digest']}`\n"
        f"- Schema inventory: {receipt['schema_inventory_count']} (`{receipt['schema_inventory_digest']}`)\n"
        f"- Reference CLI package: `{receipt['package_version']}`\n"
        f"- Signature: `{receipt['signature_state']}`\n"
        f"- Publication: `{receipt['publication_state']}`\n"
        f"- Authority boundary: {receipt['authority_boundary']}\n\n"
        "These assets are reproducible unsigned preview evidence. They are not a signed tag, release, publication, or visibility approval.\n"
    )


def validate_release_candidate_preparation_receipt(receipt: dict[str, Any]) -> None:
    """Validate structure and canonical identity of pending-signature evidence."""

    schema_id = receipt.get("schema_id") if isinstance(receipt, dict) else None
    schema_name = RELEASE_CANDIDATE_PREPARATION_SCHEMAS.get(schema_id)
    if schema_name is None:
        raise ValidationFailure(
            "release-candidate-preparation-receipt-schema-unsupported",
            "release candidate preparation receipt schema is unsupported",
        )
    validate(receipt, load_schema("core", schema_name))
    if schema_id == "artifact-memory/release-candidate-preparation-receipt/v2":
        release_version = _release_version(
            receipt["package_version"],
            allow_development=False,
        )
        if release_version == "0.1.0":
            raise ValidationFailure(
                "release-candidate-preparation-receipt-version-mismatch",
                "the frozen 0.1.0 release identity requires the v1 receipt contract",
            )
        if (
            receipt["release_id"] != f"artifact-memory/v{release_version}"
            or receipt["tag"] != f"v{release_version}"
        ):
            raise ValidationFailure(
                "release-candidate-preparation-version-binding-invalid",
                "release identity and tag must match the exact package version",
            )
    try:
        expected_id = expected_receipt_id(
            receipt,
            RELEASE_CANDIDATE_PREPARATION_RECEIPT_PREFIX,
        )
    except CanonicalizationFailure as exc:
        raise ValidationFailure(
            "release-candidate-preparation-receipt-noncanonical",
            "release candidate preparation receipt contains noncanonical content",
        ) from exc
    if receipt["receipt_id"] != expected_id:
        raise ValidationFailure(
            "release-candidate-preparation-receipt-identity-mismatch",
            "release candidate preparation receipt identity does not match its content",
        )
    expected_trailer = f"{SIGNED_MANIFEST_TRAILER} {receipt['release_manifest_digest']}"
    if receipt["tag_message_trailer"] != expected_trailer:
        raise ValidationFailure(
            "release-candidate-preparation-manifest-binding-invalid",
            "tag message trailer must bind the exact prepared release manifest digest",
        )


def render_release_candidate_preparation_receipt(receipt: dict[str, Any]) -> str:
    """Render pending owner-signature evidence without implying release authority."""

    validate_release_candidate_preparation_receipt(receipt)
    return (
        "# Release candidate preparation receipt\n\n"
        f"- Outcome: `{receipt['outcome']}`\n"
        f"- Receipt: `{receipt['receipt_id']}`\n"
        f"- Release/tag: `{receipt['release_id']}` / `{receipt['tag']}`\n"
        f"- Source commit: `{receipt['source_commit']}`\n"
        f"- Release manifest: `{receipt['release_manifest_digest']}`\n"
        f"- Required tag trailer: `{receipt['tag_message_trailer']}`\n"
        f"- Source archive: `{receipt['source_archive_digest']}` ({receipt['source_archive_byte_size']} bytes)\n"
        f"- Release notes: `{receipt['release_notes_digest']}` ({receipt['release_notes_byte_size']} bytes)\n"
        f"- SHA256SUMS: `{receipt['checksum_manifest_digest']}`\n"
        f"- Schema inventory: {receipt['schema_inventory_count']} (`{receipt['schema_inventory_digest']}`)\n"
        f"- Reference CLI package: `{receipt['package_version']}`\n"
        f"- Public signing-key fingerprint: `{receipt['public_key_fingerprint']}`\n"
        f"- Signing-key generation: `{receipt['key_generation']}`\n"
        f"- Signature verification: `{receipt['signature_verification_state']}`\n"
        f"- Publication: `{receipt['publication_state']}`\n"
        f"- Authority boundary: {receipt['authority_boundary']}\n\n"
        "These bytes are an exact release candidate awaiting the owner's signature. "
        "No key was generated or invoked, no tag was created, and no release was published.\n"
    )


def prepare_unsigned_release_preview(
    repository: Path,
    candidate: str,
    output: Path,
) -> dict[str, Any]:
    """Write reproducible preview assets for one exact commit outside its repository."""

    root = _repository_root(repository)
    commit = _exact_commit(root, candidate)
    output = _prepare_output(root, output)
    package_version = _package_version(root, commit)
    release_version = _release_version(package_version, allow_development=True)
    receipt_schema_id = _preparation_schema_id(package_version, candidate=False)
    release_name = f"artifact-memory-{release_version}-preview"
    release_id = f"artifact-memory/v{release_version}-preview"
    archive_name = f"{release_name}.tar"
    archive_bytes = _git(
        root,
        "archive",
        "--format=tar",
        f"--prefix={release_name}/",
        commit,
    )
    archive_digest = sha256_bytes(archive_bytes)
    checksum_bytes = f"{archive_digest.removeprefix('sha-256:')}  {archive_name}\n".encode("ascii")
    checksum_digest = sha256_bytes(checksum_bytes)
    tree_digest = sha256_bytes(_git(root, "ls-tree", "-r", "--full-tree", commit))
    schema_count, schema_digest = _schema_inventory(root, commit)
    adapter_manifest_schemas = _supported_adapter_manifest_schemas(root, commit)
    manifest = {
        "schema_id": "artifact-memory/release-manifest/v2",
        "release_id": release_id,
        "status": "preview",
        "source": {
            "commit": commit,
            "tree_digest": tree_digest,
            "tree_digest_profile": "sha256-of-git-ls-tree-r-full-tree-v1",
        },
        "surfaces": _release_surfaces(
            package_version,
            schema_count,
            schema_digest,
            adapter_manifest_schemas,
            stability="development-preview",
        ),
        "compatibility_policy": _compatibility_policy(),
        "artifacts": [
            {
                "name": archive_name,
                "kind": "source-archive",
                "format": "git-archive-tar",
                "byte_size": len(archive_bytes),
                "sha256": archive_digest,
                "provenance": f"git archive --format=tar --prefix={release_name}/ {commit}",
            },
            {
                "name": "SHA256SUMS",
                "kind": "checksum-file",
                "format": "sha256sum-v1",
                "byte_size": len(checksum_bytes),
                "sha256": checksum_digest,
                "provenance": "one lowercase SHA-256 line over the exact source archive bytes",
            },
        ],
        "checksum_manifest": {
            "artifact_name": "SHA256SUMS",
            "format": "sha256sum-v1",
            "scope": "all-manifest-listed-artifacts-except-checksum-manifest-itself",
        },
        "signature": {
            "state": "unsigned-preview",
            "tag": None,
            "algorithm": "ssh-ed25519",
            "public_key_fingerprint": None,
            "key_generation": None,
            "owner_signed_annotated_tag": False,
        },
        "attestations": {
            "state": "deferred-private-incubation",
            "requirement": "keyless-build-artifact-attestations-after-public-workflow-review",
        },
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": [
            "preview evidence is unsigned and is not a release",
            "anonymous public-clone verification and push-rule restoration require later owner-authorized publication",
        ],
    }
    validate_release_manifest(manifest)
    body = {
        "outcome": "pass",
        "release_id": release_id,
        "status": "preview",
        "source_commit": commit,
        "tree_digest": tree_digest,
        "source_archive_digest": archive_digest,
        "source_archive_byte_size": len(archive_bytes),
        "checksum_manifest_digest": checksum_digest,
        "schema_inventory_count": schema_count,
        "schema_inventory_digest": schema_digest,
        "package_version": package_version,
        "signature_state": "unsigned-preview",
        "publication_state": "not-authorized",
        "claims": [
            "source tree, source archive, checksum manifest, schema inventory, and package version reproduce from the named commit",
            "preview signature and publication remain explicitly absent",
            "protocol, schema, CLI, adapter, and fixture surfaces carry separate version policies",
        ],
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": manifest["limitations"],
    }
    receipt = receipt_with_digest(
        receipt_schema_id,
        RELEASE_PREPARATION_RECEIPT_PREFIX,
        body,
    )
    validate_release_preparation_receipt(receipt)
    assets = {
        archive_name: archive_bytes,
        "SHA256SUMS": checksum_bytes,
        "release-manifest.json": (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        "release-preparation-receipt.json": (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        "release-preparation-receipt.md": render_release_preparation_receipt(receipt).encode("utf-8"),
    }
    _publish_output(output, assets)
    return receipt


def prepare_release_candidate(
    repository: Path,
    candidate: str,
    output: Path,
    *,
    owner_fingerprint: str,
    key_generation: str,
) -> dict[str, Any]:
    """Prepare exact versioned assets that still require owner signing and publication."""

    if (
        not isinstance(owner_fingerprint, str)
        or SSH_FINGERPRINT_PATTERN.fullmatch(owner_fingerprint) is None
    ):
        raise ValidationFailure(
            "release-candidate-owner-fingerprint-invalid",
            "owner-published fingerprint must use canonical unpadded SHA-256 form",
        )
    if not isinstance(key_generation, str) or re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}",
        key_generation,
    ) is None:
        raise ValidationFailure(
            "release-candidate-key-generation-invalid",
            "release candidate preparation requires the public signing-key generation identifier",
        )
    root = _repository_root(repository)
    commit = _exact_commit(root, candidate)
    output = _prepare_output(root, output)

    package_version = _package_version(root, commit)
    release_version = _release_version(package_version, allow_development=False)
    receipt_schema_id = _preparation_schema_id(package_version, candidate=True)
    release_name = f"artifact-memory-{release_version}"
    release_id = f"artifact-memory/v{release_version}"
    tag = f"v{release_version}"
    archive_name = f"{release_name}.tar"
    notes_source = f"docs/release/v{release_version}-release-notes.md"
    notes_name = f"{release_name}-release-notes.md"
    archive_bytes = _git(
        root,
        "archive",
        "--format=tar",
        f"--prefix={release_name}/",
        commit,
    )
    notes_bytes = _regular_commit_file(root, commit, notes_source)
    try:
        notes_text = notes_bytes.decode("utf-8")
    except UnicodeError as exc:
        raise ValidationFailure(
            "release-candidate-notes-invalid",
            "release candidate final release notes must be UTF-8 text",
        ) from exc
    if not notes_text.strip():
        raise ValidationFailure(
            "release-candidate-notes-empty",
            "release candidate final release notes must not be empty",
        )

    archive_digest = sha256_bytes(archive_bytes)
    notes_digest = sha256_bytes(notes_bytes)
    checksum_bytes = (
        f"{archive_digest.removeprefix('sha-256:')}  {archive_name}\n"
        f"{notes_digest.removeprefix('sha-256:')}  {notes_name}\n"
    ).encode("ascii")
    checksum_digest = sha256_bytes(checksum_bytes)
    tree_digest = sha256_bytes(_git(root, "ls-tree", "-r", "--full-tree", commit))
    schema_count, schema_digest = _schema_inventory(root, commit)
    runtime_version = _runtime_version(root, commit)
    if runtime_version != package_version:
        raise ValidationFailure(
            "release-candidate-runtime-version-mismatch",
            "release candidate runtime and project package versions must match at the exact commit",
        )
    adapter_manifest_schemas = _supported_adapter_manifest_schemas(root, commit)
    manifest = {
        "schema_id": "artifact-memory/release-manifest/v2",
        "release_id": release_id,
        "status": "release-candidate",
        "source": {
            "commit": commit,
            "tree_digest": tree_digest,
            "tree_digest_profile": "sha256-of-git-ls-tree-r-full-tree-v1",
        },
        "surfaces": _release_surfaces(
            package_version,
            schema_count,
            schema_digest,
            adapter_manifest_schemas,
            stability="development-preview",
        ),
        "compatibility_policy": _compatibility_policy(),
        "artifacts": [
            {
                "name": archive_name,
                "kind": "source-archive",
                "format": "git-archive-tar",
                "byte_size": len(archive_bytes),
                "sha256": archive_digest,
                "provenance": f"git archive --format=tar --prefix={release_name}/ {commit}",
            },
            {
                "name": notes_name,
                "kind": "documentation",
                "format": "markdown",
                "byte_size": len(notes_bytes),
                "sha256": notes_digest,
                "provenance": f"exact bytes from {commit}:{notes_source}",
            },
            {
                "name": "SHA256SUMS",
                "kind": "checksum-file",
                "format": "sha256sum-v1",
                "byte_size": len(checksum_bytes),
                "sha256": checksum_digest,
                "provenance": "lowercase SHA-256 lines over the exact source archive and release notes bytes",
            },
        ],
        "checksum_manifest": {
            "artifact_name": "SHA256SUMS",
            "format": "sha256sum-v1",
            "scope": "all-manifest-listed-artifacts-except-checksum-manifest-itself",
        },
        "signature": {
            "state": "pending-owner-signature",
            "tag": tag,
            "algorithm": "ssh-ed25519",
            "public_key_fingerprint": owner_fingerprint,
            "key_generation": key_generation,
            "owner_signed_annotated_tag": False,
        },
        "attestations": {
            "state": "deferred-public-workflow-review",
            "requirement": "keyless-build-artifact-attestations-after-public-workflow-review",
        },
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": [
            "the manifest is pending candidate evidence until its digest is bound by the owner-signed annotated tag",
            "preparation does not authorize tag creation, release publication, deployment, or any authority conveyed by Artifact Memory records",
            "keyless build and artifact attestations remain deferred pending public workflow review",
        ],
    }
    validate_release_manifest(manifest)
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    manifest_digest = sha256_bytes(manifest_bytes)
    tag_message_trailer = f"{SIGNED_MANIFEST_TRAILER} {manifest_digest}"
    body = {
        "outcome": "pass",
        "release_id": release_id,
        "status": "release-candidate",
        "source_commit": commit,
        "tree_digest": tree_digest,
        "release_manifest_digest": manifest_digest,
        "tag_message_trailer": tag_message_trailer,
        "source_archive_digest": archive_digest,
        "source_archive_byte_size": len(archive_bytes),
        "release_notes_digest": notes_digest,
        "release_notes_byte_size": len(notes_bytes),
        "checksum_manifest_digest": checksum_digest,
        "schema_inventory_count": schema_count,
        "schema_inventory_digest": schema_digest,
        "package_version": package_version,
        "tag": tag,
        "public_key_fingerprint": owner_fingerprint,
        "key_generation": key_generation,
        "signature_verification_state": "pending-owner-signature",
        "publication_state": "not-authorized",
        "claims": [
            "source tree, source archive, release notes, checksum manifest, release manifest, schema inventory, and package version reproduce from the named commit",
            "the required annotated-tag trailer binds the exact prepared release manifest bytes",
            "owner signature verification and publication remain explicitly absent",
        ],
        "authority_boundary": AUTHORITY_BOUNDARY,
        "limitations": [
            "the release manifest remains explicitly pending until the owner-signed annotated tag is independently verified",
            "the owner must independently verify the public fingerprint and sign the exact tag message trailer",
            "publication requires separate owner authorization after signed-candidate verification",
        ],
    }
    receipt = receipt_with_digest(
        receipt_schema_id,
        RELEASE_CANDIDATE_PREPARATION_RECEIPT_PREFIX,
        body,
    )
    validate_release_candidate_preparation_receipt(receipt)
    assets = {
        archive_name: archive_bytes,
        notes_name: notes_bytes,
        "SHA256SUMS": checksum_bytes,
        "release-manifest.json": manifest_bytes,
        "release-candidate-preparation-receipt.json": (
            json.dumps(receipt, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8"),
        "release-candidate-preparation-receipt.md": (
            render_release_candidate_preparation_receipt(receipt).encode("utf-8")
        ),
    }
    _publish_output(output, assets)
    return receipt
