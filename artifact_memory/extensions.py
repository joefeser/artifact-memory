"""Minimal namespaced extension preservation and fail-closed handling."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from .canonical import CanonicalizationFailure, canonical_bytes
from .schema_resources import load_schema
from .validator import ValidationFailure, validate

EXTENSION_ID = re.compile(r"^https://[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~/-]+)?$")
_DECLARATION_FIELDS = {"version", "required", "value"}
_VERSION = re.compile(r"^v[0-9]+$")


class ExtensionFailure(Exception):
    def __init__(self, code: str, message: str, path: str = "$") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path


_canonical = canonical_bytes


def is_required_declaration(identifier: Any, declaration: Any) -> bool:
    """Return True only for a complete {version, required, value} declaration with required:true.

    Incomplete or malformed values (including a bare {"required": true}) are
    legacy opaque data per docs/contracts/v0-extensions.md and must not be
    treated as a structured declaration that triggers negotiation.
    """
    return (
        isinstance(identifier, str)
        and EXTENSION_ID.fullmatch(identifier) is not None
        and isinstance(declaration, dict)
        and set(declaration) == _DECLARATION_FIELDS
        and isinstance(declaration.get("version"), str)
        and _VERSION.fullmatch(declaration["version"]) is not None
        and isinstance(declaration.get("required"), bool)
        and declaration["required"] is True
        and isinstance(declaration.get("value"), dict)
    )


def validate_extension_identifiers(extensions: Any) -> None:
    """Reject any non-namespaced extension identifier, regardless of value shape.

    Per docs/contracts/v0-extensions.md, only globally namespaced extension
    identifiers are admitted. The opaque-value exception (a value that is not
    a complete {version, required, value} declaration) applies only to the
    legacy knowledge-record/v1 contract; every other record and envelope
    extension map must use HTTPS-namespaced identifiers even when its value
    is not interpreted as a structured declaration.
    """
    if not isinstance(extensions, dict):
        raise ExtensionFailure("invalid-extension-map", "extensions must be an object")
    invalid_identifiers = [
        identifier
        for identifier in extensions
        if not isinstance(identifier, str) or EXTENSION_ID.fullmatch(identifier) is None
    ]
    if invalid_identifiers:
        identifier = invalid_identifiers[0]
        raise ExtensionFailure(
            "invalid-extension-identifier",
            "extension identifier must be globally namespaced",
            f"$.extensions[{identifier!r}]",
        )


def validate_extension_bundle(extension_bundle: dict[str, Any]) -> None:
    """Validate the public declaration shape and optional digest binding."""
    extensions = extension_bundle.get("extensions") if isinstance(extension_bundle, dict) else None
    if isinstance(extensions, dict):
        invalid_identifiers = [identifier for identifier in extensions if not isinstance(identifier, str) or EXTENSION_ID.fullmatch(identifier) is None]
        if invalid_identifiers:
            identifier = invalid_identifiers[0]
            raise ExtensionFailure(
                "invalid-extension-identifier",
                "extension identifier must be globally namespaced",
                f"$.extensions[{identifier!r}]",
            )
    try:
        validate(extension_bundle, load_schema("core", "extension-bundle.v1.schema.json"))
        observed_digest = extension_digest(extension_bundle)
    except ValidationFailure as exc:
        raise ExtensionFailure(exc.code, exc.message, exc.path) from exc
    except CanonicalizationFailure as exc:
        raise ExtensionFailure("extension-canonicalization-failed", str(exc)) from exc
    declared_digest = extension_bundle.get("extensions_digest")
    if declared_digest is not None and declared_digest != observed_digest:
        raise ExtensionFailure("extension-digest-invalid", "extension digest does not match its canonical declarations")


def _validated_supported_required(supported_required: Iterable[tuple[str, str]] | None) -> set[tuple[str, str]]:
    if supported_required is None:
        return set()
    if isinstance(supported_required, (str, bytes, dict)):
        raise ExtensionFailure("invalid-supported-required", "supported required extensions must be (identifier, version) pairs", "$.supported_required")
    try:
        entries = list(supported_required)
    except TypeError as exc:
        raise ExtensionFailure("invalid-supported-required", "supported required extensions must be iterable", "$.supported_required") from exc
    for index, entry in enumerate(entries):
        if not isinstance(entry, tuple) or len(entry) != 2 or not all(isinstance(part, str) for part in entry):
            raise ExtensionFailure(
                "invalid-supported-required",
                "supported required extensions must be valid (identifier, version) pairs",
                f"$.supported_required[{index}]",
            )
        identifier, version = entry
        support_probe = {
            "schema_id": "artifact-memory/extension-bundle/v1",
            "extensions": {identifier: {"version": version, "required": True, "value": {}}},
        }
        try:
            validate_extension_bundle(support_probe)
        except ExtensionFailure as exc:
            raise ExtensionFailure(
                "invalid-supported-required",
                "supported required extensions must be valid (identifier, version) pairs",
                f"$.supported_required[{index}]",
            ) from exc
    return set(entries)


def preserve_extensions(core_record: dict[str, Any], extension_bundle: dict[str, Any], supported_required: Iterable[tuple[str, str]] | None = None) -> dict[str, Any]:
    if not isinstance(core_record, dict) or not isinstance(core_record.get("extensions", {}), dict):
        raise ExtensionFailure("invalid-core-record", "core record and its extensions must be objects")
    supported = _validated_supported_required(supported_required)
    validate_extension_bundle(extension_bundle)
    extensions = extension_bundle["extensions"]
    result = deepcopy(core_record)
    result["extensions"] = deepcopy(core_record.get("extensions", {}))
    for identifier, extension in extensions.items():
        if not EXTENSION_ID.fullmatch(identifier):
            raise ExtensionFailure("invalid-extension-identifier", "extension identifier must be globally namespaced")
        if extension.get("required") and (identifier, extension["version"]) not in supported:
            raise ExtensionFailure("required-extension-unsupported", "required extension is unsupported")
        if identifier in result["extensions"]:
            try:
                declarations_match = canonical_bytes(result["extensions"][identifier]) == canonical_bytes(extension)
            except CanonicalizationFailure as exc:
                raise ExtensionFailure("extension-conflict", "extension declaration cannot be compared safely") from exc
            if not declarations_match:
                raise ExtensionFailure("extension-conflict", "extension declaration conflicts with an existing value")
        result["extensions"][identifier] = deepcopy(extension)
    return result


def extension_digest(extension_bundle: dict[str, Any]) -> str:
    return "sha-256:" + hashlib.sha256(_canonical(extension_bundle.get("extensions", {}))).hexdigest()
