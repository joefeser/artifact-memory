"""Shared extraction rules for versioned release metadata."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable, Iterable

from .adapter_manifest import MANIFEST_SCHEMA_FILES, SUPPORTED_MANIFEST_SCHEMA_IDS
from .canonical import CanonicalizationFailure, canonical_bytes, sha256_bytes
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json_bytes


PACKAGE_VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:\.dev[0-9]+)?")


def read_package_version(pyproject_bytes: bytes) -> str:
    """Read the v0 preview package version with one shared fail-closed contract."""

    try:
        project = tomllib.loads(pyproject_bytes.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ValidationFailure(
            "release-pyproject-invalid",
            "release candidate pyproject metadata is invalid",
        ) from exc
    project_table = project.get("project")
    version = project_table.get("version") if isinstance(project_table, dict) else None
    if not isinstance(version, str) or PACKAGE_VERSION_PATTERN.fullmatch(version) is None:
        raise ValidationFailure(
            "release-pyproject-invalid",
            "release candidate package version must use X.Y.Z or X.Y.Z.devN",
        )
    return version


def schema_inventory(schema_documents: Iterable[bytes]) -> tuple[int, str]:
    """Return the canonical identifier inventory for committed schema bytes."""

    identifiers: list[str] = []
    for document in schema_documents:
        schema = load_json_bytes(document)
        identifier = schema.get("$id") if isinstance(schema, dict) else None
        if not isinstance(identifier, str) or not identifier:
            raise ValidationFailure(
                "release-schema-inventory-invalid",
                "versioned JSON schema lacks an identifier",
            )
        identifiers.append(identifier)
    if len(identifiers) != len(set(identifiers)):
        raise ValidationFailure(
            "release-schema-inventory-invalid",
            "schema inventory contains duplicate identifiers",
        )
    try:
        digest = sha256_bytes(canonical_bytes(sorted(identifiers)))
    except CanonicalizationFailure as exc:
        raise ValidationFailure(
            "release-schema-inventory-invalid",
            "schema inventory contains an invalid identifier",
        ) from exc
    return len(identifiers), digest


def supported_adapter_manifest_schemas(
    list_adapter_schema_paths: Callable[[], Iterable[str]],
    read_adapter_schema_bytes: Callable[[str], bytes],
    *,
    error_code_prefix: str,
) -> list[str]:
    """Re-derive the exact-commit supported adapter manifest schema enumeration.

    Shared by release preparation and release conformance so schema-contract
    changes cannot make the two verification paths diverge. Callers supply
    exact-commit Git accessors and a distinct error-code prefix for their
    fail-closed diagnostics.
    """

    paths = set(list_adapter_schema_paths())
    candidates = {
        schema_id: f"artifact_memory/schemas/adapters/{MANIFEST_SCHEMA_FILES[schema_id]}"
        for schema_id in SUPPORTED_MANIFEST_SCHEMA_IDS
    }
    supported: list[str] = []
    for schema_id in SUPPORTED_MANIFEST_SCHEMA_IDS:
        path = candidates[schema_id]
        if path not in paths:
            continue
        try:
            candidate_schema = load_json_bytes(read_adapter_schema_bytes(path))
            expected_schema = load_schema("adapters", MANIFEST_SCHEMA_FILES[schema_id])
            candidate_schema_bytes = canonical_bytes(candidate_schema)
            expected_schema_bytes = canonical_bytes(expected_schema)
        except (CanonicalizationFailure, ValidationFailure) as exc:
            raise ValidationFailure(
                f"{error_code_prefix}-adapter-contract-invalid",
                "release source contains an invalid supported adapter manifest schema",
            ) from exc
        if not isinstance(candidate_schema, dict) or candidate_schema_bytes != expected_schema_bytes:
            raise ValidationFailure(
                f"{error_code_prefix}-adapter-contract-invalid",
                "release source adapter manifest schema does not match its versioned contract",
            )
        supported.append(schema_id)
    return supported
