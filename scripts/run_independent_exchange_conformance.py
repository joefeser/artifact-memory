#!/usr/bin/env python3
"""Run or check the issue #23 independent exchange fixture."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.conformance_cli import run_conformance_cli
from artifact_memory.independent_exchange_conformance import (
    render_independent_exchange_conformance,
    run_independent_exchange_conformance,
)


DEFAULT_FIXTURE = (
    ROOT / "fixtures" / "synthetic" / "exchange" / "independent-v1"
)


def main(argv: list[str] | None = None) -> int:
    return run_conformance_cli(
        argv,
        default_fixture=DEFAULT_FIXTURE,
        run_fixture=run_independent_exchange_conformance,
        expected_receipt=Path("expected-receipt.json"),
        mismatch_message="independent exchange receipt does not match checked evidence",
        render_receipt=render_independent_exchange_conformance,
        expected_markdown=Path("receipt.md"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
