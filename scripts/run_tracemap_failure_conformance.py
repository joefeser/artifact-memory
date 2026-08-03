#!/usr/bin/env python3
"""Run or check the issue #39 TraceMap failure-surface fixture."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.conformance_cli import run_conformance_cli
from artifact_memory.tracemap_failure_conformance import (
    render_tracemap_failure_conformance,
    run_tracemap_failure_conformance,
)


DEFAULT_FIXTURE = ROOT / "fixtures" / "synthetic" / "tracemap-evidence" / "v1"


def main(argv: list[str] | None = None) -> int:
    return run_conformance_cli(
        argv,
        default_fixture=DEFAULT_FIXTURE,
        run_fixture=run_tracemap_failure_conformance,
        expected_receipt=Path("expected-failure-receipt.json"),
        mismatch_message="TraceMap failure-surface receipt does not match checked evidence",
        render_receipt=render_tracemap_failure_conformance,
        expected_markdown=Path("failure-receipt.md"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
