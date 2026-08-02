#!/usr/bin/env python3
"""Run or check the issue #10 minimum extension conformance fixture."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.conformance_cli import run_conformance_cli
from artifact_memory.extension_conformance import render_extension_conformance_receipt, run_extension_conformance


DEFAULT_FIXTURE = ROOT / "fixtures" / "synthetic" / "extensions" / "v1"


def main(argv: list[str] | None = None) -> int:
    return run_conformance_cli(
        argv,
        default_fixture=DEFAULT_FIXTURE,
        run_fixture=run_extension_conformance,
        expected_receipt=Path("expected-receipt.json"),
        mismatch_message="minimum extension conformance receipt does not match checked evidence",
        render_receipt=render_extension_conformance_receipt,
        expected_markdown=Path("receipt.md"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
