#!/usr/bin/env python3
"""Run or check the issue #4/#5 canonical/content conformance fixture."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.canonical_content_conformance import render_receipt, run_conformance
from artifact_memory.conformance_cli import run_conformance_cli


DEFAULT_FIXTURE = ROOT / "fixtures" / "synthetic"


def main(argv: list[str] | None = None) -> int:
    return run_conformance_cli(
        argv,
        default_fixture=DEFAULT_FIXTURE,
        run_fixture=run_conformance,
        expected_receipt=Path("canonical-content/v1/expected-receipt.json"),
        mismatch_message="canonical/content conformance receipt does not match checked evidence",
        render_receipt=render_receipt,
        expected_markdown=Path("canonical-content/v1/receipt.md"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
