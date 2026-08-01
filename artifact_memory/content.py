"""Exact-byte content objects and deterministic verification receipts."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .canonical import CHUNK_SIZE, receipt_with_digest
from .extensions import ExtensionFailure, preserve_extensions
from .schema_resources import load_schema
from .validator import ValidationFailure, validate


AUTHORITY_BOUNDARY = "content verification grants no execution, disclosure, mutation, or trust authority"
NAMED_DIGEST = re.compile(r"^([a-z0-9][a-z0-9._-]*):([0-9a-f]+)$")
SUPPORTED_ALGORITHMS = {"sha-256": hashlib.sha256, "sha-512": hashlib.sha512}
EXPECTED_HEX_LENGTHS = {"sha-256": 64, "sha-512": 128}


def _split_digest(value: str) -> tuple[str, str]:
    match = NAMED_DIGEST.fullmatch(value)
    if match is None:
        raise ValidationFailure("invalid-digest", "digest must use a named lowercase algorithm and lowercase hexadecimal value")
    return match.group(1), match.group(2)


def _validated_claims(content_object: dict[str, Any]) -> list[tuple[str, str]]:
    validate(content_object, load_schema("core", "content-object.v2.schema.json"))
    try:
        preserve_extensions({}, {
            "schema_id": "artifact-memory/extension-bundle/v1",
            "extensions": content_object.get("extensions", {}),
        })
    except ExtensionFailure as exc:
        raise ValidationFailure(exc.code, exc.message, "$.extensions") from exc
    claims = [_split_digest(content_object["digest"])]
    claims.extend(_split_digest(item) for item in content_object.get("secondary_digests", []))
    algorithms = [algorithm for algorithm, _ in claims]
    if len(set(algorithms)) != len(algorithms):
        raise ValidationFailure("duplicate-digest-algorithm", "each digest algorithm may be declared only once")
    for algorithm, hexadecimal in claims:
        expected_length = EXPECTED_HEX_LENGTHS.get(algorithm)
        if expected_length is not None and len(hexadecimal) != expected_length:
            raise ValidationFailure("invalid-digest", f"{algorithm} digest has the wrong length")
    primary_algorithm, primary_hex = claims[0]
    if primary_algorithm != "sha-256":
        raise ValidationFailure("unsupported-primary-digest", "the v0 primary identity digest must be SHA-256")
    if content_object["content_id"] != f"content://sha-256/{primary_hex}":
        raise ValidationFailure("content-identity-mismatch", "content_id must be derived from the primary SHA-256 digest")
    return claims


def _receipt(content_object: dict[str, Any], outcome: str, results: list[dict[str, str]], observed_size: int | None, diagnostics: list[str]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "outcome": outcome,
        "content_ref": content_object["content_id"],
        "expected_byte_size": content_object["byte_size"],
        "digest_results": results,
        "diagnostics": diagnostics,
        "authority_boundary": AUTHORITY_BOUNDARY,
    }
    if observed_size is not None:
        body["observed_byte_size"] = observed_size
    receipt = receipt_with_digest(
        "artifact-memory/content-verification-receipt/v1",
        "content-verification-receipt://",
        body,
    )
    validate(receipt, load_schema("core", "content-verification-receipt.v1.schema.json"))
    return receipt


def verify_content(path: Path, content_object: dict[str, Any]) -> dict[str, Any]:
    """Verify every declared digest and byte size without recording the local path."""
    claims = _validated_claims(content_object)
    unsupported = [algorithm for algorithm, _ in claims if algorithm not in SUPPORTED_ALGORITHMS]
    if unsupported:
        results = [
            {"algorithm": algorithm, "expected": f"{algorithm}:{expected}", "outcome": "unsupported" if algorithm in unsupported else "not-checked"}
            for algorithm, expected in claims
        ]
        return _receipt(content_object, "unsupported", results, None, ["digest-algorithm-unsupported"])

    hashers = {algorithm: SUPPORTED_ALGORITHMS[algorithm]() for algorithm, _ in claims}
    observed_size = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(CHUNK_SIZE):
                observed_size += len(chunk)
                for hasher in hashers.values():
                    hasher.update(chunk)
    except OSError:
        results = [
            {"algorithm": algorithm, "expected": f"{algorithm}:{expected}", "outcome": "not-checked"}
            for algorithm, expected in claims
        ]
        return _receipt(content_object, "unreadable", results, None, ["content-unreadable"])

    results: list[dict[str, str]] = []
    mismatch = observed_size != content_object["byte_size"]
    for algorithm, expected in claims:
        observed = hashers[algorithm].hexdigest()
        state = "verified" if observed == expected else "mismatch"
        mismatch = mismatch or state == "mismatch"
        results.append({
            "algorithm": algorithm,
            "expected": f"{algorithm}:{expected}",
            "observed": f"{algorithm}:{observed}",
            "outcome": state,
        })
    diagnostics = ["byte-size-mismatch"] if observed_size != content_object["byte_size"] else []
    if any(item["outcome"] == "mismatch" for item in results):
        diagnostics.append("digest-mismatch")
    return _receipt(content_object, "mismatch" if mismatch else "verified", results, observed_size, diagnostics)
