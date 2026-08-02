#!/usr/bin/env python3
"""Run or check the issue #12 aggregate synthetic conformance fixture."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.conformance_fixture import render_conformance_fixture_receipt, run_conformance_fixture
from artifact_memory.conformance_cli import run_conformance_cli


DEFAULT_FIXTURE = ROOT / "fixtures" / "synthetic" / "conformance" / "v1"


def main(argv: list[str] | None = None) -> int:
    return run_conformance_cli(
        argv,
        default_fixture=DEFAULT_FIXTURE,
        run_fixture=lambda fixture: run_conformance_fixture(fixture / "manifest.json", fixture / "expected-results.json", ROOT),
        expected_receipt=Path("expected-receipt.json"),
        mismatch_message="aggregate conformance receipt does not match checked evidence",
        render_receipt=render_conformance_fixture_receipt,
        expected_markdown=Path("receipt.md"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
