#!/usr/bin/env python3
"""Run the synthetic AM-3 coordination sync acceptance proof."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.coordination_sync_conformance import run


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = run(ROOT / "fixtures")
    print(json.dumps(result, sort_keys=True, indent=None if args.check else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
