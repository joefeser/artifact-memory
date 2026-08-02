#!/usr/bin/env python3
"""Run or check the issue #12 aggregate synthetic conformance fixture."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.conformance_fixture import render_conformance_fixture_receipt, run_conformance_fixture


DEFAULT_FIXTURE = ROOT / "fixtures" / "synthetic" / "conformance" / "v1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args(argv)
    receipt = run_conformance_fixture(args.fixture / "manifest.json", args.fixture / "expected-results.json", ROOT)
    if args.check:
        expected = json.loads((args.fixture / "expected-receipt.json").read_text(encoding="utf-8"))
        expected_markdown = (args.fixture / "receipt.md").read_text(encoding="utf-8")
        if receipt != expected or render_conformance_fixture_receipt(receipt) != expected_markdown:
            print("aggregate conformance receipt does not match checked evidence", file=sys.stderr)
            return 1
    if args.format == "markdown":
        print(render_conformance_fixture_receipt(receipt), end="")
    else:
        print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
