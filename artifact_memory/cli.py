"""Command-line entrypoint for the provider-free v0 shell."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import CONTRACT_VERSION, __version__
from .context import ContextFailure, export_context
from .projection import project_records, related_records, search_records
from .scan import diff_manifests, scan_path, verify_path
from .validator import ValidationFailure, load_json, validate_file

EXIT_OK = 0
EXIT_INVALID = 2
EXIT_UNSUPPORTED = 3


def _schemas() -> dict[str, Path]:
    root = Path(__file__).resolve().parents[1] / "schemas" / "core"
    result: dict[str, Path] = {}
    for schema_path in sorted(root.glob("*.schema.json")):
        schema = load_json(schema_path)
        if isinstance(schema, dict) and isinstance(schema.get("properties"), dict):
            schema_id = schema["properties"].get("schema_id", {}).get("const")
            if isinstance(schema_id, str):
                result[schema_id] = schema_path
    return result


def _receipt(payload: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="artifact-memory")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "inspect"):
        command = subparsers.add_parser(name)
        command.add_argument("record", type=Path)
        command.add_argument("--schema", type=Path)
        command.add_argument("--json", action="store_true", dest="as_json")
    scan = subparsers.add_parser("scan")
    scan.add_argument("root", type=Path)
    scan.add_argument("--out", type=Path)
    scan.add_argument("--json", action="store_true", dest="as_json")
    verify = subparsers.add_parser("verify")
    verify.add_argument("root", type=Path)
    verify.add_argument("manifest", type=Path)
    verify.add_argument("--json", action="store_true", dest="as_json")
    diff = subparsers.add_parser("diff")
    diff.add_argument("before", type=Path)
    diff.add_argument("after", type=Path)
    diff.add_argument("--json", action="store_true", dest="as_json")
    project = subparsers.add_parser("project")
    project.add_argument("records", type=Path, nargs="+")
    project.add_argument("--out", required=True, type=Path)
    project.add_argument("--json", action="store_true", dest="as_json")
    search = subparsers.add_parser("search")
    search.add_argument("index", type=Path)
    search.add_argument("query")
    search.add_argument("--json", action="store_true", dest="as_json")
    related = subparsers.add_parser("related")
    related.add_argument("index", type=Path)
    related.add_argument("record_id")
    related.add_argument("--json", action="store_true", dest="as_json")
    context = subparsers.add_parser("context")
    context.add_argument("records", type=Path, nargs="+")
    context.add_argument("--evidence", type=Path)
    context.add_argument("--out", type=Path)
    context.add_argument("--allow-sensitivity", choices=["public", "private", "restricted"], default="public")
    context.add_argument("--max-bytes", type=int, default=32_768)
    context.add_argument("--json", action="store_true", dest="as_json")
    version = subparsers.add_parser("version")
    version.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    if args.command == "version":
        _receipt({"implementation": "artifact-memory-python", "version": __version__, "contract_version": CONTRACT_VERSION}, args.as_json)
        return EXIT_OK
    if args.command == "scan":
        manifest, receipt = scan_path(args.root)
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            (args.out / "scan-receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        _receipt({"outcome": receipt["outcome"], "manifest_ref": manifest["manifest_id"], "tree_digest": manifest["tree_digest"], "accounted_entry_count": receipt["accounted_entry_count"], "diagnostic_count": len(receipt["diagnostics"])}, args.as_json)
        return EXIT_OK if receipt["outcome"] == "complete" else EXIT_INVALID
    if args.command == "verify":
        try:
            manifest = load_json(args.manifest)
        except ValidationFailure as exc:
            _receipt({"outcome": "rejected", "diagnostics": [{"code": exc.code, "message": exc.message}]}, args.as_json)
            return EXIT_INVALID
        result = verify_path(args.root, manifest)
        _receipt(result, args.as_json)
        return EXIT_OK if result["outcome"] == "verified" else EXIT_INVALID
    if args.command == "diff":
        try:
            before = load_json(args.before)
            after = load_json(args.after)
        except ValidationFailure as exc:
            _receipt({"outcome": "rejected", "diagnostics": [{"code": exc.code, "message": exc.message}]}, args.as_json)
            return EXIT_INVALID
        result = diff_manifests(before, after)
        _receipt(result, args.as_json)
        return EXIT_OK
    if args.command == "project":
        try:
            result = project_records(args.records, args.out)
        except ValidationFailure as exc:
            _receipt({"outcome": "rejected", "diagnostics": [{"code": exc.code, "message": exc.message}]}, args.as_json)
            return EXIT_INVALID
        _receipt(result, args.as_json)
        return EXIT_OK
    if args.command == "search":
        _receipt({"outcome": "complete", "record_ids": search_records(args.index, args.query)}, args.as_json)
        return EXIT_OK
    if args.command == "related":
        _receipt({"outcome": "complete", "record_id": args.record_id, "relationships": related_records(args.index, args.record_id)}, args.as_json)
        return EXIT_OK
    if args.command == "context":
        try:
            records = [load_json(path) for path in args.records]
            evidence = load_json(args.evidence) if args.evidence else []
            result = export_context(records, evidence, args.allow_sensitivity, args.max_bytes)
        except (ValidationFailure, ContextFailure) as exc:
            _receipt({"outcome": "rejected", "diagnostics": [{"code": getattr(exc, "code", "invalid-input"), "message": getattr(exc, "message", str(exc))}]}, args.as_json)
            return EXIT_INVALID
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / "context-pack.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        _receipt({"outcome": "complete", "pack_id": result["pack_id"], "selected_record_count": len(result["records"]), "redacted_record_count": len(result["selection_receipt"]["redacted_record_ids"]), "authority_boundary": result["authority_boundary"]}, args.as_json)
        return EXIT_OK
    try:
        record = load_json(args.record)
    except ValidationFailure as exc:
        _receipt({"valid": False, "outcome": "rejected", "diagnostics": [{"code": exc.code, "path": exc.path, "message": exc.message}]}, args.as_json)
        return EXIT_INVALID
    if not isinstance(record, dict):
        _receipt({"valid": False, "outcome": "rejected", "diagnostics": [{"code": "invalid-input", "path": "$", "message": "record must be a JSON object"}]}, args.as_json)
        return EXIT_INVALID
    schema_id = record.get("schema_id")
    schema_path = args.schema or _schemas().get(schema_id)
    if schema_path is None:
        _receipt({"valid": False, "outcome": "unsupported", "schema_id": schema_id, "diagnostics": [{"code": "schema-unsupported", "path": "$.schema_id", "message": "no supported v0 schema"}]}, args.as_json)
        return EXIT_UNSUPPORTED
    if args.command == "inspect":
        _receipt({"outcome": "inspected", "schema_id": schema_id, "field_names": sorted(record)}, args.as_json)
        return EXIT_OK
    result = validate_file(args.record, schema_path)
    result["schema_id"] = schema_id
    _receipt(result, args.as_json)
    return EXIT_OK if result["valid"] else EXIT_INVALID


if __name__ == "__main__":
    sys.exit(main())
