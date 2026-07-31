"""Command-line entrypoint for the provider-free v0 shell."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import CONTRACT_VERSION, __version__
from .context import ContextFailure, build_selection_policy, export_context
from .projection import project_records, records_with_provenance, related_records, search_records
from .scan import diff_manifests, scan_path, verify_path
from .schema_resources import core_schemas
from .validator import ValidationFailure, load_json, validate

EXIT_OK = 0
EXIT_INVALID = 2
EXIT_UNSUPPORTED = 3


def _schemas() -> dict[str, dict[str, object]]:
    return core_schemas()


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
    provenance = subparsers.add_parser("provenance")
    provenance.add_argument("index", type=Path)
    provenance.add_argument("source_ref")
    provenance.add_argument("--json", action="store_true", dest="as_json")
    context = subparsers.add_parser("context")
    context.add_argument("records", type=Path, nargs="+")
    context.add_argument("--evidence", type=Path)
    context.add_argument("--out", type=Path)
    context.add_argument("--allow-sensitivity", choices=["public", "private", "restricted"], default="public")
    context.add_argument("--max-bytes", type=int, default=32_768)
    context.add_argument("--selected-at", required=True, help="whole-second UTC selection time")
    context.add_argument("--freshness-basis", required=True, help="operator assertion or receipt reference")
    context.add_argument("--authorize-evidence", action="append", nargs=2, metavar=("PROVIDER_ID", "PROVIDER_RECORD_ID"), default=[], dest="authorized_evidence")
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
            if not isinstance(before, dict) or not isinstance(after, dict):
                raise ValidationFailure("invalid-input", "manifests must be JSON objects")
            result = diff_manifests(before, after)
        except ValidationFailure as exc:
            _receipt({"outcome": "rejected", "diagnostics": [{"code": exc.code, "path": exc.path, "message": exc.message}]}, args.as_json)
            return EXIT_INVALID
        _receipt(result, args.as_json)
        return EXIT_OK if result["outcome"] == "complete" else EXIT_INVALID
    if args.command == "project":
        try:
            result = project_records(args.records, args.out)
        except ValidationFailure as exc:
            _receipt({"outcome": "rejected", "diagnostics": [{"code": exc.code, "message": exc.message}]}, args.as_json)
            return EXIT_INVALID
        _receipt(result, args.as_json)
        return EXIT_OK
    if args.command == "search":
        try:
            record_ids = search_records(args.index, args.query)
        except ValidationFailure as exc:
            _receipt({"outcome": "rejected", "diagnostics": [{"code": exc.code, "message": exc.message}]}, args.as_json)
            return EXIT_INVALID
        _receipt({"outcome": "complete", "record_ids": record_ids}, args.as_json)
        return EXIT_OK
    if args.command == "related":
        try:
            relationships = related_records(args.index, args.record_id)
        except ValidationFailure as exc:
            _receipt({"outcome": "rejected", "diagnostics": [{"code": exc.code, "message": exc.message}]}, args.as_json)
            return EXIT_INVALID
        _receipt({"outcome": "complete", "record_id": args.record_id, "relationships": relationships}, args.as_json)
        return EXIT_OK
    if args.command == "provenance":
        try:
            records = records_with_provenance(args.index, args.source_ref)
        except ValidationFailure as exc:
            _receipt({"outcome": "rejected", "diagnostics": [{"code": exc.code, "message": exc.message}]}, args.as_json)
            return EXIT_INVALID
        _receipt({"outcome": "complete", "source_ref": args.source_ref, "records": records}, args.as_json)
        return EXIT_OK
    if args.command == "context":
        try:
            records = [load_json(path) for path in args.records]
            evidence = load_json(args.evidence) if args.evidence else []
            record_ids = [record.get("record_id") for record in records if isinstance(record, dict)]
            result = export_context(
                records,
                evidence,
                args.allow_sensitivity,
                args.max_bytes,
                **build_selection_policy(
                    record_ids,
                    selected_at=args.selected_at,
                    freshness_basis=args.freshness_basis,
                    authorized_evidence=[tuple(item) for item in args.authorized_evidence],
                ),
            )
        except (ValidationFailure, ContextFailure) as exc:
            _receipt({"outcome": "rejected", "diagnostics": [{"code": getattr(exc, "code", "invalid-input"), "message": getattr(exc, "message", str(exc))}]}, args.as_json)
            return EXIT_INVALID
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / "context-pack.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        exclusions = result["selection_receipt"]["exclusion_counts"]
        _receipt({"outcome": "complete", "pack_id": result["pack_id"], "selected_record_count": len(result["records"]), "excluded_record_count": sum(exclusions.values()), "authority_boundary": result["authority_boundary"]}, args.as_json)
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
    try:
        schema = load_json(args.schema) if args.schema else _schemas().get(schema_id)
    except ValidationFailure as exc:
        _receipt({"valid": False, "outcome": "rejected", "diagnostics": [{"code": exc.code, "path": exc.path, "message": exc.message}]}, args.as_json)
        return EXIT_INVALID
    if schema is None:
        _receipt({"valid": False, "outcome": "unsupported", "schema_id": schema_id, "diagnostics": [{"code": "schema-unsupported", "path": "$.schema_id", "message": "no supported v0 schema"}]}, args.as_json)
        return EXIT_UNSUPPORTED
    if args.command == "inspect":
        _receipt({"outcome": "inspected", "schema_id": schema_id, "field_names": sorted(record)}, args.as_json)
        return EXIT_OK
    try:
        if not isinstance(schema, dict):
            raise ValidationFailure("invalid-input", "schema must be a JSON object")
        validate(record, schema)
    except ValidationFailure as exc:
        result = {"valid": False, "outcome": "rejected", "diagnostics": [{"code": exc.code, "path": exc.path, "message": exc.message}]}
    else:
        result = {"valid": True, "outcome": "accepted", "diagnostics": []}
    result["schema_id"] = schema_id
    _receipt(result, args.as_json)
    return EXIT_OK if result["valid"] else EXIT_INVALID


if __name__ == "__main__":
    sys.exit(main())
