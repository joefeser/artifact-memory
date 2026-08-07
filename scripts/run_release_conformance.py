#!/usr/bin/env python3
"""Run or check the issue #33 unsigned release-preview fixture."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.conformance_cli import run_conformance_cli
from artifact_memory.release_conformance import render_release_conformance, run_release_conformance
from artifact_memory.validator import ValidationFailure


DEFAULT_FIXTURE = ROOT / "fixtures" / "synthetic" / "release"


def main(argv: list[str] | None = None) -> int:
    try:
        return run_conformance_cli(
            argv,
            default_fixture=DEFAULT_FIXTURE,
            run_fixture=run_release_conformance,
            expected_receipt=Path("v0-preview-expected-receipt.json"),
            mismatch_message="release preview conformance receipt does not match checked evidence",
            render_receipt=render_release_conformance,
            expected_markdown=Path("v0-preview-receipt.md"),
        )
    except ValidationFailure as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
