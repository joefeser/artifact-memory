"""Prepare reproducible unsigned preview assets without signing authority."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .adapter_manifest import SUPPORTED_MANIFEST_SCHEMA_IDS
from .canonical import receipt_with_digest, sha256_bytes
from .release import validate_release_manifest
from .release_metadata import read_package_version, schema_inventory
from .schema_resources import load_schema
from .validator import ValidationFailure, validate


AUTHORITY_BOUNDARY = (
    "release preparation grants no signing, tag, publication, visibility, or deployment authority"
)


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
            "release preview preparation supports SHA-1-format Git repositories in v0",
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
            "release preview output must not be a symbolic link",
        )
    resolved = output.resolve()
    if resolved.is_relative_to(root):
        raise ValidationFailure(
            "release-preparation-output-inside-repository",
            "release preview assets must be written outside the audited repository",
        )
    if resolved.exists() and (resolved.is_symlink() or not resolved.is_dir()):
        raise ValidationFailure(
            "release-preparation-output-invalid",
            "release preview output must be a real directory",
        )
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if output.is_symlink() or output.resolve() != resolved:
        raise ValidationFailure(
            "release-preparation-output-invalid",
            "release preview output changed during preparation",
        )
    if resolved.exists() and any(resolved.iterdir()):
        raise ValidationFailure(
            "release-preparation-output-not-empty",
            "release preview output directory must be empty",
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


def _supported_adapter_manifest_schemas(repository: Path, commit: str) -> list[str]:
    paths = set(
        _git(
            repository,
            "ls-tree",
            "-r",
            "--name-only",
            commit,
            "artifact_memory/schemas/adapters",
        ).decode("utf-8").splitlines()
    )
    candidates = {
        SUPPORTED_MANIFEST_SCHEMA_IDS[0]: "artifact_memory/schemas/adapters/adapter-manifest.v1.schema.json",
        SUPPORTED_MANIFEST_SCHEMA_IDS[1]: "artifact_memory/schemas/adapters/adapter-manifest.v2.schema.json",
    }
    supported = [schema_id for schema_id in SUPPORTED_MANIFEST_SCHEMA_IDS if candidates[schema_id] in paths]
    if not supported:
        raise ValidationFailure(
            "release-preparation-adapter-contract-missing",
            "release preview source contains no supported adapter manifest schema",
        )
    return supported


def _write_exclusive(path: Path, content: bytes) -> None:
    try:
        with path.open("xb") as stream:
            stream.write(content)
    except OSError as exc:
        raise ValidationFailure(
            "release-preparation-output-invalid",
            "release preview staging rejected a conflicting output path",
        ) from exc


def _publish_output(output: Path, assets: dict[str, bytes]) -> None:
    """Stage, verify, and atomically expose one complete preview directory."""

    try:
        staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    except OSError as exc:
        raise ValidationFailure(
            "release-preparation-output-invalid",
            "release preview staging directory could not be created",
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
                    "release preview staging evidence could not be reread",
                ) from exc
            if persisted != content:
                raise ValidationFailure(
                    "release-preparation-output-invalid",
                    "release preview staging evidence changed before publication",
                )
        try:
            if output.exists() or output.is_symlink():
                output.rmdir()
            os.replace(staging, output)
            published = True
        except OSError as exc:
            raise ValidationFailure(
                "release-preparation-output-invalid",
                "release preview output changed before atomic publication",
            ) from exc
    finally:
        if not published:
            shutil.rmtree(staging, ignore_errors=True)


def render_release_preparation_receipt(receipt: dict[str, Any]) -> str:
    """Render the validated unsigned preview preparation evidence."""

    validate(receipt, load_schema("core", "release-preparation-receipt.v1.schema.json"))
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


def prepare_unsigned_release_preview(
    repository: Path,
    candidate: str,
    output: Path,
) -> dict[str, Any]:
    """Write reproducible preview assets for one exact commit outside its repository."""

    root = _repository_root(repository)
    commit = _exact_commit(root, candidate)
    output = _prepare_output(root, output)
    release_name = "artifact-memory-0.1.0-preview"
    release_id = "artifact-memory/v0.1.0-preview"
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
    package_version = _package_version(root, commit)
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
        "surfaces": {
            "protocol": {"version": "v0", "stability": "development-preview"},
            "schemas": {
                "versioning": "independent-schema-id-vN",
                "inventory_count": schema_count,
                "inventory_digest": schema_digest,
                "inventory_digest_profile": "sha256-of-canonical-sorted-schema-id-array-v1",
            },
            "reference_cli": {
                "package_version": package_version,
                "stability": "development-preview",
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
        },
        "compatibility_policy": {
            "unknown_optional": "preserve-without-interpretation",
            "unknown_required": "fail-closed",
            "breaking_change": "new-version-and-explicit-migration-or-rejection-rule",
            "deprecation_window": "at-least-one-minor-release-and-90-days-after-announcement",
            "pre_1_0_api_stability": "implementation-APIs-unstable-contracts-remain-versioned",
        },
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
        "artifact-memory/release-preparation-receipt/v1",
        "release-preparation-receipt://",
        body,
    )
    validate(receipt, load_schema("core", "release-preparation-receipt.v1.schema.json"))
    assets = {
        archive_name: archive_bytes,
        "SHA256SUMS": checksum_bytes,
        "release-manifest.json": (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        "release-preparation-receipt.json": (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        "release-preparation-receipt.md": render_release_preparation_receipt(receipt).encode("utf-8"),
    }
    _publish_output(output, assets)
    return receipt
