#!/usr/bin/env python3
"""Run or check the issue #7 synthetic scan conformance fixture."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.scan_conformance import render_scan_conformance_receipt, run_scan_conformance


DEFAULT_FIXTURE = ROOT / "fixtures" / "synthetic" / "scan" / "v2"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args(argv)
    receipt = run_scan_conformance(args.fixture / "vectors.json")
    if args.check:
        expected = json.loads((args.fixture / "expected-receipt.json").read_text(encoding="utf-8"))
        expected_markdown = (args.fixture / "receipt.md").read_text(encoding="utf-8")
        if receipt != expected or render_scan_conformance_receipt(receipt) != expected_markdown:
            print("scan conformance receipt does not match checked evidence", file=sys.stderr)
            return 1
    if args.format == "markdown":
        print(render_scan_conformance_receipt(receipt), end="")
    else:
        print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
