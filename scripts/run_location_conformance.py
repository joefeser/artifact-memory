#!/usr/bin/env python3
"""Run or check the issue #9 synthetic location conformance fixture."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.location_conformance import render_location_receipt, run_location_conformance
from artifact_memory.conformance_cli import run_conformance_cli


DEFAULT_FIXTURE = ROOT / "fixtures" / "synthetic" / "locations" / "v1"


def main(argv: list[str] | None = None) -> int:
    return run_conformance_cli(
        argv,
        default_fixture=DEFAULT_FIXTURE,
        run_fixture=lambda fixture: run_location_conformance(fixture / "vectors.json"),
        expected_receipt=Path("expected-receipt.json"),
        mismatch_message="location conformance receipt does not match checked-in evidence",
        render_receipt=render_location_receipt,
        expected_markdown=Path("receipt.md"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
