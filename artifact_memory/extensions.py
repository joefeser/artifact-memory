"""Minimal namespaced extension preservation and fail-closed handling."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any


EXTENSION_ID = re.compile(r"^https://[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~/-]+)?$")


class ExtensionFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def preserve_extensions(core_record: dict[str, Any], extension_bundle: dict[str, Any], supported_required: set[str] | None = None) -> dict[str, Any]:
    supported_required = supported_required or set()
    extensions = extension_bundle.get("extensions")
    if not isinstance(extensions, dict):
        raise ExtensionFailure("invalid-extension-bundle", "extensions must be an object")
    result = deepcopy(core_record)
    result["extensions"] = deepcopy(core_record.get("extensions", {}))
    for identifier, extension in extensions.items():
        if not EXTENSION_ID.fullmatch(identifier):
            raise ExtensionFailure("invalid-extension-identifier", "extension identifier must be globally namespaced")
        if not isinstance(extension, dict) or not isinstance(extension.get("value"), dict):
            raise ExtensionFailure("invalid-extension", "extension declaration is invalid")
        if extension.get("required") and identifier not in supported_required:
            raise ExtensionFailure("required-extension-unsupported", "required extension is unsupported")
        result["extensions"][identifier] = deepcopy(extension)
    return result


def extension_digest(extension_bundle: dict[str, Any]) -> str:
    return "sha-256:" + hashlib.sha256(_canonical(extension_bundle.get("extensions", {}))).hexdigest()
