"""Command-line entrypoint for the provider-free v0 shell."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import CONTRACT_VERSION, __version__
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
    version = subparsers.add_parser("version")
    version.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    if args.command == "version":
        _receipt({"implementation": "artifact-memory-python", "version": __version__, "contract_version": CONTRACT_VERSION}, args.as_json)
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
