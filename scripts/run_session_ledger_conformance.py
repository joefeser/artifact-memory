#!/usr/bin/env python3
"""Run the synthetic AM-1 session-ledger import proof."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.conformance_cli import run_conformance_cli
from artifact_memory.session_ledger import (
    exercise_session_ledger_fixture,
    render_session_ledger_conformance_receipt,
)


DEFAULT_FIXTURE = ROOT / "fixtures" / "session-ledger" / "v0"


def main(argv: list[str] | None = None) -> int:
    return run_conformance_cli(
        argv,
        default_fixture=DEFAULT_FIXTURE,
        run_fixture=exercise_session_ledger_fixture,
        expected_receipt=Path("expected-receipt.json"),
        mismatch_message="session-ledger conformance receipt does not match checked evidence",
        render_receipt=render_session_ledger_conformance_receipt,
        expected_markdown=Path("receipt.md"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
