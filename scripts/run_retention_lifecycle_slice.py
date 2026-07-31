#!/usr/bin/env python3
"""Run or check the synthetic #36 retention lifecycle slice."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.retention_lifecycle_slice import run_retention_lifecycle_slice


DEFAULT_FIXTURE = ROOT / "fixtures" / "synthetic" / "retention-lifecycle" / "v1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    receipt = run_retention_lifecycle_slice(args.fixture)
    if args.check:
        expected = json.loads((args.fixture / "expected-receipt.json").read_text(encoding="utf-8"))
        if receipt != expected:
            print("retention lifecycle receipt does not match checked-in evidence", file=sys.stderr)
            return 1
    print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
