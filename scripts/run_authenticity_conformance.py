#!/usr/bin/env python3
"""Run or check the issue #35 synthetic authenticity conformance fixture."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.authenticity_conformance import render_authenticity_receipt, run_authenticity_conformance
from artifact_memory.conformance_cli import run_conformance_cli


DEFAULT_FIXTURE = ROOT / "fixtures" / "synthetic" / "security"


def main(argv: list[str] | None = None) -> int:
    return run_conformance_cli(
        argv,
        default_fixture=DEFAULT_FIXTURE,
        run_fixture=lambda fixture: run_authenticity_conformance(fixture / "authenticity-v0-v2.json"),
        expected_receipt=Path("authenticity-v0-v2-expected-receipt.json"),
        mismatch_message="authenticity conformance receipt does not match checked-in evidence",
        render_receipt=render_authenticity_receipt,
        expected_markdown=Path("authenticity-v0-v2-receipt.md"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
