#!/usr/bin/env python3
"""Run or check the issue #35 synthetic authenticity conformance fixture."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.authenticity_conformance import render_authenticity_receipt, run_authenticity_conformance


DEFAULT_FIXTURE = ROOT / "fixtures" / "synthetic" / "security"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args(argv)
    receipt = run_authenticity_conformance(args.fixture / "authenticity-v0-v2.json")
    if args.check:
        expected = json.loads((args.fixture / "authenticity-v0-v2-expected-receipt.json").read_text(encoding="utf-8"))
        expected_markdown = (args.fixture / "authenticity-v0-v2-receipt.md").read_text(encoding="utf-8")
        if receipt != expected or render_authenticity_receipt(receipt) != expected_markdown:
            print("authenticity conformance receipt does not match checked-in evidence", file=sys.stderr)
            return 1
    if args.format == "markdown":
        print(render_authenticity_receipt(receipt), end="")
    else:
        print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
