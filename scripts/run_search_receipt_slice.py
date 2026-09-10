#!/usr/bin/env python3
"""Run or check the provider-free #106 synthetic search-receipt slice."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.search_receipt_slice import run_search_receipt_slice


DEFAULT_FIXTURE = ROOT / "fixtures" / "synthetic" / "search-receipt" / "v1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="artifact-memory-search-receipt-") as temporary:
        receipt = run_search_receipt_slice(args.fixture, Path(temporary))
    if args.check:
        expected = json.loads((args.fixture / "expected-receipt.json").read_text(encoding="utf-8"))
        if receipt != expected:
            print("search-receipt slice receipt does not match the checked-in evidence", file=sys.stderr)
            return 1
    print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
