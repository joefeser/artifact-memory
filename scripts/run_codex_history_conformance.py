#!/usr/bin/env python3
"""Run or check the synthetic #37 Codex-history derivative slice."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.codex_history_conformance import run_codex_history_conformance
from artifact_memory.conformance_cli import run_conformance_cli


DEFAULT_FIXTURE = ROOT / "fixtures" / "synthetic" / "codex-history" / "v1"


def main(argv: list[str] | None = None) -> int:
    return run_conformance_cli(
        argv,
        default_fixture=DEFAULT_FIXTURE,
        run_fixture=run_codex_history_conformance,
        expected_receipt=Path("expected-receipt.json"),
        mismatch_message="Codex-history receipt does not match the checked-in evidence",
    )


if __name__ == "__main__":
    raise SystemExit(main())
