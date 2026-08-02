"""Replay the language-neutral aggregate synthetic conformance fixture."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

from .canonical import canonical_bytes, receipt_with_digest, sha256_bytes, sha256_path
from .location_conformance import run_location_conformance
from .schema_resources import core_schemas, load_schema
from .validator import ValidationFailure, load_json, validate


MANIFEST_SCHEMA_ID = "artifact-memory/conformance-fixture-manifest/v1"
EXPECTED_RESULTS_SCHEMA_ID = "artifact-memory/conformance-expected-results/v1"
REQUIRED_CLASSES = {"valid", "invalid", "equivalent", "collision", "unsupported"}


def _safe_fixture_path(repository_root: Path, relative: Any) -> Path:
    if not isinstance(relative, str):
        raise ValidationFailure("invalid-fixture-reference", "fixture input path must be a string")
    logical = PurePosixPath(relative)
    if relative != logical.as_posix() or logical.is_absolute() or not logical.parts or logical.parts[:2] != ("fixtures", "synthetic") or any(part in {"", ".", ".."} for part in logical.parts):
        raise ValidationFailure("invalid-fixture-reference", "fixture input must be a normalized synthetic repository-relative path")
    root = repository_root.resolve()
    candidate = root.joinpath(*logical.parts)
    current = root
    for part in logical.parts:
        current = current / part
        if current.is_symlink():
            raise ValidationFailure("invalid-fixture-reference", "fixture input may not traverse a symbolic link")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ValidationFailure("fixture-unavailable", "fixture input is unavailable") from exc
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValidationFailure("invalid-fixture-reference", "fixture input must resolve to a regular repository file")
    return resolved


def _json_pointer(value: Any, pointer: Any) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValidationFailure("invalid-json-pointer", "fixture selector must be a non-root JSON Pointer")
    current = value
    for raw_token in pointer[1:].split("/"):
        if re.fullmatch(r"(?:[^~]|~[01])*", raw_token) is None:
            raise ValidationFailure("invalid-json-pointer", "fixture selector contains an invalid escape")
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise ValidationFailure("json-pointer-missing", "fixture selector does not identify a value")
    return current


def _load_inputs(case: dict[str, Any], repository_root: Path) -> list[tuple[Path, Any]]:
    loaded: list[tuple[Path, Any]] = []
    for source in case["inputs"]:
        path = _safe_fixture_path(repository_root, source["path"])
        if sha256_path(path) != source["sha256"]:
            raise ValidationFailure("fixture-digest-mismatch", "fixture input does not match its manifest digest")
        value = load_json(path)
        if "selector" in source:
            value = _json_pointer(value, source["selector"])
        loaded.append((path, value))
    return loaded


def _one_input(case: dict[str, Any], inputs: list[tuple[Path, Any]]) -> tuple[Path, Any]:
    if len(inputs) != 1:
        raise ValidationFailure("invalid-fixture-case", f"case {case['case_id']} requires exactly one input")
    return inputs[0]


def _run_exact_content(case: dict[str, Any], inputs: list[tuple[Path, Any]]) -> dict[str, Any]:
    _, vector = _one_input(case, inputs)
    required = {"vector_id", "algorithm", "relative_path", "content_utf8", "byte_size", "content_digest", "leaf_serialization", "tree_digest", "synthetic_only"}
    if not isinstance(vector, dict) or set(vector) != required or vector["algorithm"] != "sha-256" or vector["synthetic_only"] is not True:
        raise ValidationFailure("invalid-vector", "exact-content vector envelope is invalid")
    content = vector["content_utf8"]
    relative_path = vector["relative_path"]
    byte_size = vector["byte_size"]
    if not isinstance(content, str) or not isinstance(relative_path, str) or isinstance(byte_size, bool) or not isinstance(byte_size, int):
        raise ValidationFailure("invalid-vector", "exact-content vector fields are invalid")
    logical_path = PurePosixPath(relative_path)
    if relative_path != logical_path.as_posix() or logical_path.is_absolute() or any(part in {"", ".", ".."} for part in logical_path.parts):
        raise ValidationFailure("invalid-vector", "exact-content relative path is not normalized and portable")
    content_digest = sha256_bytes(content.encode("utf-8"))
    leaf = f"file\t{relative_path}\t{content_digest}\t{len(content.encode('utf-8'))}\n"
    tree_digest = sha256_bytes(leaf.encode("utf-8"))
    if byte_size != len(content.encode("utf-8")) or vector["content_digest"] != content_digest or vector["leaf_serialization"] != leaf or vector["tree_digest"] != tree_digest:
        raise ValidationFailure("vector-mismatch", "exact-content digest vector does not reproduce")
    return {"outcome": "accepted", "diagnostic_codes": [], "byte_size": byte_size, "content_digest": content_digest, "tree_digest": tree_digest}


def _run_schema_validation(case: dict[str, Any], inputs: list[tuple[Path, Any]]) -> dict[str, Any]:
    _, value = _one_input(case, inputs)
    schema_id = case.get("schema_id_under_test")
    if not isinstance(schema_id, str):
        raise ValidationFailure("invalid-fixture-case", "schema-validation case must name schema_id_under_test")
    schema = core_schemas().get(schema_id)
    if schema is None:
        raise ValidationFailure("unsupported-schema", "schema-validation case names an unsupported schema")
    try:
        validate(value, schema)
    except ValidationFailure as exc:
        return {"outcome": "rejected", "diagnostic_codes": [exc.code], "diagnostic_path": exc.path, "schema_id_under_test": schema_id}
    return {"outcome": "accepted", "diagnostic_codes": [], "diagnostic_path": "", "schema_id_under_test": schema_id}


def _run_location_equivalence(case: dict[str, Any], inputs: list[tuple[Path, Any]]) -> dict[str, Any]:
    path, _ = _one_input(case, inputs)
    receipt = run_location_conformance(path)
    platforms = receipt["platform_results"]
    resolved = [item["platform"] for item in platforms if item["resolution_outcome"] == "resolved"]
    outcome = "equivalent" if len(resolved) == len(platforms) and len(platforms) > 1 else "rejected"
    diagnostics = [] if outcome == "equivalent" else ["location-equivalence-failed"]
    return {
        "outcome": outcome,
        "diagnostic_codes": diagnostics,
        "endpoint_ref": receipt["endpoint_ref"],
        "platform_count": len(platforms),
        "resolved_platforms": resolved,
        "relative_path": receipt["relative_path"],
    }


def _run_declared_outcome(case: dict[str, Any], inputs: list[tuple[Path, Any]]) -> dict[str, Any]:
    _, declaration = _one_input(case, inputs)
    if not isinstance(declaration, dict):
        raise ValidationFailure("invalid-vector", "declared outcome must be an object")
    code = declaration.get("expected_code")
    source_outcome = declaration.get("expected_outcome")
    if code not in {"collision", "unsupported"} or source_outcome not in {"partial", "failed"} or code != case["class"]:
        raise ValidationFailure("invalid-vector", "declared outcome does not match its fixture class")
    details = {key: value for key, value in declaration.items() if key not in {"expected_code", "expected_outcome"}}
    return {"outcome": code, "diagnostic_codes": [code], "declared_outcome": source_outcome, "details": details}


def _execute(case: dict[str, Any], inputs: list[tuple[Path, Any]]) -> dict[str, Any]:
    operation = case["operation"]
    if operation != "schema-validation-v0" and "schema_id_under_test" in case:
        raise ValidationFailure("invalid-fixture-case", "schema_id_under_test is only valid for schema-validation-v0")
    runners = {
        "exact-content-digest-v0": _run_exact_content,
        "schema-validation-v0": _run_schema_validation,
        "logical-location-equivalence-v0": _run_location_equivalence,
        "declared-outcome-v0": _run_declared_outcome,
    }
    return runners[operation](case, inputs)


def _assert_expected(case: dict[str, Any], expected: dict[str, Any], actual: dict[str, Any]) -> None:
    if expected["case_id"] != case["case_id"] or expected["class"] != case["class"] or expected["result_id"] != case["expected_result_ref"]:
        raise ValidationFailure("expected-result-mismatch", "expected result identity does not match its fixture case")
    if actual["outcome"] != expected["outcome"] or actual["diagnostic_codes"] != expected["diagnostic_codes"]:
        raise ValidationFailure("expected-result-mismatch", f"fixture result does not match: {case['case_id']}")
    for assertion in expected["assertions"]:
        observed = _json_pointer(actual, assertion["pointer"])
        if canonical_bytes(observed) != canonical_bytes(assertion["value"]):
            raise ValidationFailure("expected-result-mismatch", f"fixture assertion does not match: {case['case_id']}")


def run_conformance_fixture(manifest_path: Path, expected_results_path: Path, repository_root: Path) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    expected_results = load_json(expected_results_path)
    validate(manifest, load_schema("core", "conformance-fixture-manifest.v1.schema.json"))
    validate(expected_results, load_schema("core", "conformance-expected-results.v1.schema.json"))
    if manifest.get("schema_id") != MANIFEST_SCHEMA_ID or expected_results.get("schema_id") != EXPECTED_RESULTS_SCHEMA_ID:
        raise ValidationFailure("unsupported-fixture-schema", "aggregate fixture schema is unsupported")
    if manifest["fixture_set_id"] != expected_results["fixture_set_id"]:
        raise ValidationFailure("fixture-set-mismatch", "manifest and expected results identify different fixture sets")

    cases = manifest["cases"]
    results = expected_results["results"]
    case_ids = [case["case_id"] for case in cases]
    result_ids = [result["result_id"] for result in results]
    if len(case_ids) != len(set(case_ids)) or len(result_ids) != len(set(result_ids)):
        raise ValidationFailure("duplicate-fixture-identity", "fixture case and result identities must be unique")
    if {case["class"] for case in cases} != REQUIRED_CLASSES:
        raise ValidationFailure("fixture-class-coverage", "fixture set must cover valid, invalid, equivalent, collision, and unsupported classes")
    expected_by_id = {result["result_id"]: result for result in results}
    if set(expected_by_id) != {case["expected_result_ref"] for case in cases} or len(results) != len(cases):
        raise ValidationFailure("expected-result-coverage", "every fixture case must have exactly one expected result")

    summaries: list[dict[str, Any]] = []
    for case in cases:
        inputs = _load_inputs(case, repository_root)
        actual = _execute(case, inputs)
        _assert_expected(case, expected_by_id[case["expected_result_ref"]], actual)
        summaries.append({
            "case_id": case["case_id"],
            "class": case["class"],
            "outcome": actual["outcome"],
            "input_digests": [source["sha256"] for source in case["inputs"]],
        })

    body = {
        "outcome": "complete",
        "synthetic": True,
        "fixture_set_id": manifest["fixture_set_id"],
        "manifest_digest": sha256_bytes(canonical_bytes(manifest)),
        "expected_results_digest": sha256_bytes(canonical_bytes(expected_results)),
        "case_count": len(summaries),
        "class_counts": {name: sum(item["class"] == name for item in summaries) for name in sorted(REQUIRED_CLASSES)},
        "cases": summaries,
        "claims": [
            "every referenced fixture input is bound by an exact SHA-256 digest",
            "valid, invalid, equivalent, collision, and unsupported outcomes are distinct runner-neutral classes",
            "expected outcomes and values are expressed without a language-specific test framework",
        ],
        "limitations": [
            "the aggregate fixture proves only its named v0 operations and representative synthetic cases",
            "synthetic equivalence does not establish physical-device or universal filesystem interoperability",
            "conformance evidence establishes neither authenticity nor access, disclosure, mutation, execution, or declassification authority",
        ],
    }
    receipt = receipt_with_digest("artifact-memory/conformance-fixture-receipt/v1", "conformance-fixture-receipt://", body)
    validate(receipt, load_schema("core", "conformance-fixture-receipt.v1.schema.json"))
    return receipt


def render_conformance_fixture_receipt(receipt: dict[str, Any]) -> str:
    counts = receipt["class_counts"]
    return (
        "# Aggregate synthetic conformance receipt\n\n"
        f"- Outcome: `{receipt['outcome']}`\n"
        f"- Fixture set: `{receipt['fixture_set_id']}`\n"
        f"- Cases: {receipt['case_count']}\n"
        f"- Classes: valid={counts['valid']}, invalid={counts['invalid']}, equivalent={counts['equivalent']}, collision={counts['collision']}, unsupported={counts['unsupported']}\n"
        f"- Manifest digest: `{receipt['manifest_digest']}`\n"
        f"- Expected-results digest: `{receipt['expected_results_digest']}`\n"
        f"- Receipt: `{receipt['receipt_id']}`\n\n"
        "All inputs are newly authored synthetic data and exact-digest bound. This receipt grants no authority and makes no production or universal cross-platform claim.\n"
    )
