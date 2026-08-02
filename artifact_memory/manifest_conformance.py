"""Replay the language-neutral v0 portable manifest vectors."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from .canonical import canonical_bytes, receipt_with_digest, sha256_bytes
from .scan import _is_normalized_relative_path, _tree_digest
from .schema_resources import load_schema
from .validator import ValidationFailure, load_json, validate


PLATFORMS = ("linux", "macos", "windows")
UNSUPPORTED_KINDS = {"alternate-data-stream", "hardlink", "sparse-file", "symlink", "extended-attributes"}


def _portable_path(value: Any) -> str:
    if not isinstance(value, str) or not _is_normalized_relative_path(value):
        raise ValidationFailure("invalid-vector", "manifest vector path is not normalized portable UTF-8")
    return value


def _materialize_entries(raw_entries: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValidationFailure("invalid-vector", "manifest layout entries must be a nonempty array")
    entries: list[dict[str, Any]] = []
    for raw in raw_entries:
        if not isinstance(raw, dict) or not isinstance(raw.get("kind"), str):
            raise ValidationFailure("invalid-vector", "manifest layout entry is malformed")
        path = _portable_path(raw.get("path"))
        if raw["kind"] == "directory" and set(raw) == {"path", "kind"}:
            entries.append({"path": path, "kind": "directory"})
        elif raw["kind"] == "file" and set(raw) == {"path", "kind", "content_utf8"} and isinstance(raw["content_utf8"], str):
            try:
                content = raw["content_utf8"].encode("utf-8")
            except UnicodeError as exc:
                raise ValidationFailure("invalid-vector", "manifest vector content is not valid UTF-8") from exc
            entries.append({
                "path": path,
                "kind": "file",
                "byte_size": len(content),
                "content_digest": sha256_bytes(content),
            })
        else:
            raise ValidationFailure("invalid-vector", "positive manifest entries support only ordinary files and directories")
    entries.sort(key=lambda entry: entry["path"])
    paths = [entry["path"] for entry in entries]
    if len(paths) != len(set(paths)):
        raise ValidationFailure("invalid-vector", "manifest layout contains duplicate paths")
    if len({path.casefold() for path in paths}) != len(paths):
        raise ValidationFailure("invalid-vector", "positive manifest layout contains a case-folded collision")
    directories = {entry["path"] for entry in entries if entry["kind"] == "directory"}
    for entry in entries:
        parent = PurePosixPath(entry["path"]).parent
        while parent != PurePosixPath("."):
            if parent.as_posix() not in directories:
                raise ValidationFailure("invalid-vector", "manifest layout omits a parent directory")
            parent = parent.parent
    return entries


def _classify_negative(case: dict[str, Any]) -> tuple[str, str, str]:
    observations = case.get("observations")
    if not isinstance(observations, list) or not observations:
        raise ValidationFailure("invalid-vector", "negative manifest case has no observations")
    paths: list[str] = []
    kinds: list[str] = []
    for observation in observations:
        if not isinstance(observation, dict) or set(observation) != {"path", "kind"} or not isinstance(observation["kind"], str):
            raise ValidationFailure("invalid-vector", "negative manifest observation is malformed")
        paths.append(_portable_path(observation["path"]))
        kinds.append(observation["kind"])
    if len(paths) != len(set(paths)):
        raise ValidationFailure("invalid-vector", "negative manifest case contains an exact duplicate path")
    collision = len({path.casefold() for path in paths}) != len(paths)
    unsupported = any(kind in UNSUPPORTED_KINDS for kind in kinds)
    unreadable = "unreadable" in kinds
    if sum((collision, unsupported, unreadable)) > 1:
        raise ValidationFailure("invalid-vector", "negative manifest case mixes distinct failure classes")
    if collision:
        return "collision", "partial", "collision"
    if unsupported:
        return "unsupported", "partial", "unsupported"
    if unreadable:
        return "partial", "partial", "unreadable"
    raise ValidationFailure("invalid-vector", "negative manifest case does not exercise a bounded v0 outcome")


def render_manifest_conformance_receipt(receipt: dict[str, Any]) -> str:
    outcomes = receipt["outcomes"]
    return (
        "# Portable manifest conformance receipt\n\n"
        f"- Outcome: `{receipt['outcome']}`\n"
        f"- Positive equivalent-tree cases: {receipt['positive_case_count']}\n"
        f"- Layouts per positive case: {len(receipt['platforms'])} ({', '.join(receipt['platforms'])})\n"
        f"- Negative outcomes: collision={outcomes['collision']}, unsupported={outcomes['unsupported']}, partial={outcomes['partial']}\n"
        f"- Container/tree identities distinct: `{str(receipt['container_tree_distinct']).lower()}`\n"
        f"- Vector-set digest: `{receipt['vector_set_digest']}`\n"
        f"- Receipt: `{receipt['receipt_id']}`\n\n"
        "All vectors are newly authored synthetic data. Mount roots are test inputs, never durable identity. CI replays this same receipt on macOS, Ubuntu, and Windows; deferred host semantics remain tracked by #24 and archive semantics by #25.\n"
    )


def run_manifest_conformance(vector_path: Path) -> dict[str, Any]:
    vectors = load_json(vector_path)
    validate(vectors, load_schema("core", "manifest-conformance-vectors.v1.schema.json"))
    if vectors.get("schema_id") != "artifact-memory/manifest-conformance-vectors/v1" or vectors.get("synthetic") is not True:
        raise ValidationFailure("unsupported-vector-schema", "manifest conformance vector schema is unsupported")
    profile = vectors.get("profile")
    if profile != {
        "comparison": "case-sensitive-unicode-codepoint",
        "digest_algorithm": "sha-256",
        "encoding": "UTF-8",
        "line_terminator": "LF",
        "path_separator": "/",
        "directory_leaf": "directory<TAB>{path}<LF>",
        "file_leaf": "file<TAB>{path}<TAB>{content_digest}<TAB>{byte_size}<LF>",
    }:
        raise ValidationFailure("invalid-vector", "manifest digest profile is not the normative v0 profile")

    positive_cases = vectors["positive_cases"]
    negative_cases = vectors["negative_cases"]
    case_ids = [case["case_id"] for case in [*positive_cases, *negative_cases]]
    if len(case_ids) != len(set(case_ids)):
        raise ValidationFailure("duplicate-vector-identity", "manifest conformance case IDs must be unique")
    positive_summaries: list[dict[str, Any]] = []
    platform_digests: dict[str, list[str]] = {platform: [] for platform in PLATFORMS}
    for case in positive_cases:
        layouts = case["layouts"]
        if sorted(layout["platform"] for layout in layouts) != list(PLATFORMS):
            raise ValidationFailure("invalid-vector", "positive manifest case must include exactly one Linux, macOS, and Windows layout")
        if len({layout["mount_root"] for layout in layouts}) != len(PLATFORMS):
            raise ValidationFailure("invalid-vector", "positive manifest layouts must use distinct synthetic mount roots")
        observed_entries: list[list[dict[str, Any]]] = []
        observed_digests: list[str] = []
        for layout in layouts:
            if not isinstance(layout.get("mount_root"), str) or not layout["mount_root"]:
                raise ValidationFailure("invalid-vector", "manifest layout mount root is malformed")
            entries = _materialize_entries(layout["entries"])
            digest = _tree_digest(entries)
            observed_entries.append(entries)
            observed_digests.append(digest)
            platform_digests[layout["platform"]].append(digest)
        if any(entries != observed_entries[0] for entries in observed_entries[1:]) or len(set(observed_digests)) != 1:
            raise ValidationFailure("vector-mismatch", f"logical layouts are not equivalent: {case['case_id']}")
        if observed_digests[0] != case["expected_tree_digest"]:
            raise ValidationFailure("vector-mismatch", f"tree digest does not match: {case['case_id']}")
        positive_summaries.append({
            "case_id": case["case_id"],
            "outcome": "equivalent",
            "entry_count": len(observed_entries[0]),
            "tree_digest": observed_digests[0],
        })

    negative_summaries: list[dict[str, str]] = []
    for case in negative_cases:
        outcome, completeness, code = _classify_negative(case)
        if (outcome, completeness, code) != (case["expected_outcome"], case["expected_completeness"], case["expected_code"]):
            raise ValidationFailure("vector-mismatch", f"negative outcome does not match: {case['case_id']}")
        negative_summaries.append({"case_id": case["case_id"], "outcome": outcome, "manifest_completeness": completeness, "diagnostic_code": code})

    container = vectors["container_boundary"]
    container_digest = sha256_bytes(container["container_utf8"].encode("utf-8"))
    extracted_digest = next((case["tree_digest"] for case in positive_summaries if case["case_id"] == container["extracted_tree_case_ref"]), None)
    if container_digest != container["expected_container_digest"] or extracted_digest != container["expected_extracted_tree_digest"] or container_digest == extracted_digest:
        raise ValidationFailure("vector-mismatch", "container and extracted-tree identity boundary does not reproduce")

    outcomes = {name: sum(case["outcome"] == name for case in negative_summaries) for name in ("collision", "unsupported", "partial")}
    if any(count < 1 for count in outcomes.values()):
        raise ValidationFailure("vector-mismatch", "negative manifest outcome coverage is incomplete")
    body = {
        "outcome": "complete",
        "synthetic": True,
        "vector_set_digest": sha256_bytes(canonical_bytes(vectors)),
        "positive_case_count": len(positive_summaries),
        "platforms": list(PLATFORMS),
        "platform_tree_digests": platform_digests,
        "positive_cases": positive_summaries,
        "outcomes": outcomes,
        "negative_cases": negative_summaries,
        "container_digest": container_digest,
        "extracted_tree_digest": extracted_digest,
        "container_tree_distinct": True,
        "claims": [
            "mount roots and observation order do not affect normalized tree identity",
            "ordinary files and directories produce deterministic UTF-8 leaf serialization and SHA-256 tree digests",
            "case collisions, unsupported entry kinds, and unreadable entries remain distinct bounded outcomes",
        ],
        "limitations": [
            "synthetic logical layouts do not prove every host filesystem behavior; actual platform replay is recorded by CI and broader semantics remain in issue #24",
            "archive extraction safety and container relationships beyond the identity distinction remain in issue #25",
        ],
    }
    receipt = receipt_with_digest("artifact-memory/manifest-conformance-receipt/v1", "manifest-conformance-receipt://", body)
    validate(receipt, load_schema("core", "manifest-conformance-receipt.v1.schema.json"))
    return receipt
