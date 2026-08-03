#!/usr/bin/env python3
"""Run or check the issue #11 adapter-manifest conformance fixture."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.adapter_manifest_conformance import render_adapter_manifest_conformance_receipt, run_adapter_manifest_conformance
from artifact_memory.conformance_cli import run_conformance_cli


DEFAULT_FIXTURE = ROOT / "fixtures" / "synthetic" / "adapters" / "v1"


def main(argv: list[str] | None = None) -> int:
    return run_conformance_cli(
        argv,
        default_fixture=DEFAULT_FIXTURE,
        run_fixture=run_adapter_manifest_conformance,
        expected_receipt=Path("expected-receipt.json"),
        mismatch_message="adapter manifest conformance receipt does not match checked evidence",
        render_receipt=render_adapter_manifest_conformance_receipt,
        expected_markdown=Path("receipt.md"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
