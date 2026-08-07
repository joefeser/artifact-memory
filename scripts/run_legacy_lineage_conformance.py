#!/usr/bin/env python3
"""Run or check the issue #26 synthetic historical-lineage fixture."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.conformance_cli import run_conformance_cli
from artifact_memory.legacy_lineage_conformance import render_legacy_lineage_receipt, run_legacy_lineage_conformance


DEFAULT_FIXTURE = ROOT / "fixtures" / "synthetic" / "lineage" / "v1"


def main(argv: list[str] | None = None) -> int:
    return run_conformance_cli(
        argv,
        default_fixture=DEFAULT_FIXTURE,
        run_fixture=lambda fixture: run_legacy_lineage_conformance(fixture / "vectors.json"),
        expected_receipt=Path("expected-receipt.json"),
        mismatch_message="legacy lineage conformance receipt does not match checked evidence",
        render_receipt=render_legacy_lineage_receipt,
        expected_markdown=Path("receipt.md"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
