"""Shared extraction rules for versioned release metadata."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable

from .canonical import CanonicalizationFailure, canonical_bytes, sha256_bytes
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
