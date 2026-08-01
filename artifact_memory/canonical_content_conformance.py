"""Replay the language-neutral issue #4/#5 canonical and content vectors."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from .canonical import CanonicalizationFailure, canonical_bytes, receipt_with_digest, sha256_bytes
from .content import verify_content
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, validate


def _invalid_outcome(path: Path) -> str:
    try:
        value = load_json(path)
        canonical_bytes(value)
    except ValidationFailure as error:
        return error.code
    except CanonicalizationFailure as error:
        message = str(error)
        if "number" in message or "integer" in message:
            return "unsupported-number"
        if "surrogate" in message:
            return "unsupported-unicode"
        return "unsupported-value"
    return "accepted-unexpectedly"


def _recipe_bytes(recipe: dict[str, Any]) -> bytes:
    if recipe.get("kind") != "repeat-byte":
        raise ValidationFailure("invalid-vector", "content recipe kind is unsupported")
    try:
        byte = bytes.fromhex(recipe["byte_hex"])
        count = recipe["count"]
    except (KeyError, TypeError, ValueError) as error:
        raise ValidationFailure("invalid-vector", "content recipe is malformed") from error
    if len(byte) != 1 or isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValidationFailure("invalid-vector", "content recipe requires one byte and a non-negative count")
    return byte * count


def render_receipt(receipt: dict[str, Any]) -> str:
    outcomes = receipt["verification_outcomes"]
    return (
        "# Canonical record and content conformance receipt\n\n"
        f"- Outcome: `{receipt['outcome']}`\n"
        f"- Canonical vectors: {receipt['canonical_vector_count']}\n"
        f"- Invalid vectors rejected: {receipt['invalid_vector_count']}\n"
        f"- Revision examples: {receipt['revision_example_count']}\n"
        f"- Zero-byte content: `{receipt['zero_byte_outcome']}`\n"
        f"- Large content: `{receipt['large_object_outcome']}` ({receipt['large_object_byte_size']} bytes)\n"
        f"- Verification outcomes: verified={outcomes['verified']}, mismatch={outcomes['mismatch']}, unreadable={outcomes['unreadable']}, unsupported={outcomes['unsupported']}\n"
        f"- Vector-set digest: `{receipt['vector_set_digest']}`\n\n"
        "The fixture is newly authored synthetic data. It proves deterministic v0 canonical bytes, revision digests, and exact-content verification without using Git, paths, timestamps, or storage locations as identity.\n"
    )


def run_conformance(fixture_root: Path) -> dict[str, Any]:
    canonical_vectors = load_json(fixture_root / "canonical" / "v1" / "vectors.json")
    revisions = load_json(fixture_root / "canonical" / "v1" / "revisions.json")
    content_vectors = load_json(fixture_root / "content" / "v1" / "vectors.json")
    if not all(isinstance(value, dict) and value.get("synthetic") is True for value in (canonical_vectors, revisions, content_vectors)):
        raise ValidationFailure("invalid-vector", "all conformance inputs must declare synthetic provenance")

    for vector in canonical_vectors["vectors"]:
        encoded = canonical_bytes(vector["input"])
        if encoded.decode("utf-8") != vector["canonical_utf8"] or sha256_bytes(encoded) != vector["digest"]:
            raise ValidationFailure("vector-mismatch", f"canonical vector does not match: {vector['id']}")
    invalid_root = fixture_root / "canonical" / "v1"
    for vector in canonical_vectors["invalid"]:
        if _invalid_outcome(invalid_root / vector["path"]) != vector["outcome"]:
            raise ValidationFailure("vector-mismatch", f"invalid vector does not match: {vector['id']}")

    knowledge_schema = load_schema("core", "knowledge-record.v1.schema.json")
    revision_items = [*revisions["revisions"], revisions["replacement"]]
    for item in revision_items:
        validate(item["record"], knowledge_schema)
        if sha256_bytes(canonical_bytes(item["record"])) != item["revision_digest"]:
            raise ValidationFailure("vector-mismatch", "revision digest does not match canonical record")
    if revisions.get("git_identity_role") != "not-protocol-identity":
        raise ValidationFailure("invalid-vector", "Git identity boundary is missing")

    receipts: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for vector in content_vectors["recipes"]:
            data = _recipe_bytes(vector["recipe"])
            path = root / vector["id"]
            path.write_bytes(data)
            receipt = verify_content(path, vector["content_object"])
            if receipt["outcome"] != vector["expected_outcome"]:
                raise ValidationFailure("vector-mismatch", f"content vector does not match: {vector['id']}")
            receipts.append(receipt)

        zero_object = content_vectors["recipes"][0]["content_object"]
        mismatch_path = root / "mismatch"
        mismatch_path.write_bytes(b"synthetic mismatch\n")
        receipts.append(verify_content(mismatch_path, zero_object))
        receipts.append(verify_content(root / "not-created", zero_object))
        unsupported = {
            "schema_id": "artifact-memory/content-object/v2",
            "content_id": "content://blake3/abcd",
            "digest": "blake3:abcd",
            "byte_size": 0,
            "media_type": "application/octet-stream",
        }
        receipts.append(verify_content(root / "not-needed", unsupported))

    outcomes = {name: sum(item["outcome"] == name for item in receipts) for name in ("verified", "mismatch", "unreadable", "unsupported")}
    if any(outcomes[name] < 1 for name in outcomes):
        raise ValidationFailure("vector-mismatch", "verification outcome coverage is incomplete")
    vector_set_digest = sha256_bytes(canonical_bytes({
        "canonical": canonical_vectors,
        "revisions": revisions,
        "content": content_vectors,
    }))
    body = {
        "outcome": "complete",
        "synthetic": True,
        "canonical_vector_count": len(canonical_vectors["vectors"]),
        "invalid_vector_count": len(canonical_vectors["invalid"]),
        "revision_example_count": len(revision_items),
        "zero_byte_outcome": receipts[0]["outcome"],
        "large_object_outcome": receipts[1]["outcome"],
        "large_object_byte_size": content_vectors["recipes"][1]["content_object"]["byte_size"],
        "verification_outcomes": outcomes,
        "vector_set_digest": vector_set_digest,
        "identity_boundaries": ["record-id-is-logical", "revision-digest-is-canonical-bytes", "content-id-is-location-neutral", "git-id-is-not-protocol-identity"],
        "limitations": ["v0 canonical digest inputs exclude fractional numbers", "fixture recipes contain synthetic bytes only"],
    }
    receipt = receipt_with_digest("artifact-memory/canonical-content-conformance-receipt/v1", "canonical-content-receipt://", body)
    validate(receipt, load_schema("core", "canonical-content-conformance-receipt.v1.schema.json"))
    return receipt
