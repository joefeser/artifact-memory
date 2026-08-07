#!/usr/bin/env python3
"""Validate and render the public custody attestation contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.sanitized_custody_attestation import (
    render_sanitized_custody_attestation,
    validate_sanitized_custody_attestation,
)
from artifact_memory.validator import load_json


ATTESTATION = ROOT / "evidence/sanitized/custody/v1/receipt.json"
MARKDOWN = ROOT / "evidence/sanitized/custody/v1/receipt.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args(argv)

    attestation = load_json(ATTESTATION)
    validate_sanitized_custody_attestation(attestation)
    rendered = render_sanitized_custody_attestation(attestation)
    if args.check and rendered != MARKDOWN.read_text(encoding="utf-8"):
        print("sanitized custody attestation projection does not match", file=sys.stderr)
        return 1
    if args.format == "markdown":
        print(rendered, end="")
    else:
        print(json.dumps(attestation, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
