"""Minimal namespaced extension preservation and fail-closed handling."""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from typing import Any

from .canonical import CanonicalizationFailure, canonical_bytes
from .schema_resources import load_schema
from .validator import ValidationFailure, validate

EXTENSION_ID = re.compile(r"^https://[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~/-]+)?$")


class ExtensionFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_canonical = canonical_bytes


def validate_extension_bundle(extension_bundle: dict[str, Any]) -> None:
    """Validate the public declaration shape and optional digest binding."""
    try:
        validate(extension_bundle, load_schema("core", "extension-bundle.v1.schema.json"))
        observed_digest = extension_digest(extension_bundle)
    except ValidationFailure as exc:
        raise ExtensionFailure(exc.code, exc.message) from exc
    except CanonicalizationFailure as exc:
        raise ExtensionFailure("extension-canonicalization-failed", str(exc)) from exc
    declared_digest = extension_bundle.get("extensions_digest")
    if declared_digest is not None and declared_digest != observed_digest:
        raise ExtensionFailure("extension-digest-invalid", "extension digest does not match its canonical declarations")


def preserve_extensions(core_record: dict[str, Any], extension_bundle: dict[str, Any], supported_required: set[tuple[str, str]] | None = None) -> dict[str, Any]:
    if not isinstance(core_record, dict) or not isinstance(core_record.get("extensions", {}), dict):
        raise ExtensionFailure("invalid-core-record", "core record and its extensions must be objects")
    validate_extension_bundle(extension_bundle)
    supported_required = supported_required or set()
    extensions = extension_bundle["extensions"]
    result = deepcopy(core_record)
    result["extensions"] = deepcopy(core_record.get("extensions", {}))
    for identifier, extension in extensions.items():
        if not EXTENSION_ID.fullmatch(identifier):
            raise ExtensionFailure("invalid-extension-identifier", "extension identifier must be globally namespaced")
        if extension.get("required") and (identifier, extension["version"]) not in supported_required:
            raise ExtensionFailure("required-extension-unsupported", "required extension is unsupported")
        if identifier in result["extensions"] and result["extensions"][identifier] != extension:
            raise ExtensionFailure("extension-conflict", "extension declaration conflicts with an existing value")
        result["extensions"][identifier] = deepcopy(extension)
    return result


def extension_digest(extension_bundle: dict[str, Any]) -> str:
    return "sha-256:" + hashlib.sha256(_canonical(extension_bundle.get("extensions", {}))).hexdigest()
