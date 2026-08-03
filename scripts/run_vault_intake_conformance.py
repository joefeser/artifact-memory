#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.conformance_cli import run_conformance_cli
from artifact_memory.vault_intake_conformance import render_vault_intake_receipt, run_vault_intake_conformance


def main(argv: list[str] | None = None) -> int:
    return run_conformance_cli(
        argv,
        default_fixture=ROOT / "fixtures/synthetic/vault-intake/v1",
        run_fixture=run_vault_intake_conformance,
        expected_receipt=Path("expected-receipt.json"),
        mismatch_message="vault intake receipt does not match checked evidence",
        render_receipt=render_vault_intake_receipt,
        expected_markdown=Path("receipt.md"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
