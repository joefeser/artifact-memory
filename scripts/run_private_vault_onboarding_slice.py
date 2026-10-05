#!/usr/bin/env python3
"""Run or check the provider-free #129 private-vault onboarding slice."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.private_vault_onboarding_slice import (
    render_private_vault_onboarding_receipt,
    run_private_vault_onboarding_slice,
)


DEFAULT_FIXTURE = ROOT / "fixtures" / "synthetic" / "private-vault-onboarding" / "v1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--human", action="store_true")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="artifact-memory-private-vault-onboarding-") as temporary:
        receipt = run_private_vault_onboarding_slice(args.fixture, Path(temporary))
    if args.check:
        expected = json.loads((args.fixture / "expected-receipt.json").read_text(encoding="utf-8"))
        if receipt != expected:
            print("private-vault onboarding receipt does not match the checked-in evidence", file=sys.stderr)
            return 1
        expected_human = (args.fixture / "receipt.md").read_text(encoding="utf-8")
        if render_private_vault_onboarding_receipt(receipt) != expected_human:
            print("private-vault onboarding human receipt does not match the checked-in evidence", file=sys.stderr)
            return 1
    if args.human:
        print(render_private_vault_onboarding_receipt(receipt), end="")
    else:
        print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
