#!/usr/bin/env python3
"""Run or check the issue #4/#5 canonical/content conformance fixture."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.canonical_content_conformance import render_receipt, run_conformance


DEFAULT_FIXTURE = ROOT / "fixtures" / "synthetic"
EXPECTED_JSON = DEFAULT_FIXTURE / "canonical-content" / "v1" / "expected-receipt.json"
EXPECTED_MARKDOWN = DEFAULT_FIXTURE / "canonical-content" / "v1" / "receipt.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args(argv)
    receipt = run_conformance(args.fixture)
    if args.check:
        expected = json.loads(EXPECTED_JSON.read_text(encoding="utf-8"))
        expected_markdown = EXPECTED_MARKDOWN.read_text(encoding="utf-8")
        if receipt != expected or render_receipt(receipt) != expected_markdown:
            print("canonical/content conformance receipt does not match checked evidence", file=sys.stderr)
            return 1
    if args.format == "markdown":
        print(render_receipt(receipt), end="")
    else:
        print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
