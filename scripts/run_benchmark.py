#!/usr/bin/env python3
"""Run or check the issue #28 descriptive synthetic baseline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.benchmark import (
    invariant_projection,
    render_baseline,
    run_baseline,
    validate_benchmark_receipt,
    validate_profile,
)
from artifact_memory.canonical import canonical_bytes, sha256_bytes
from artifact_memory.validator import ValidationFailure, load_json


DEFAULT_FIXTURE = ROOT / "fixtures" / "synthetic" / "benchmarks" / "v1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args(argv)
    try:
        profile = validate_profile(load_json(args.fixture / "profile.json"))
        observed = run_baseline(profile)
        if args.write:
            (args.fixture / "expected-receipt.json").write_text(
                json.dumps(observed, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            (args.fixture / "receipt.md").write_text(
                render_baseline(observed), encoding="utf-8"
            )
        if args.check:
            committed = load_json(args.fixture / "expected-receipt.json")
            validate_benchmark_receipt(committed)
            if committed["profile_digest"] != sha256_bytes(canonical_bytes(profile)):
                raise ValidationFailure(
                    "benchmark-profile-mismatch",
                    "checked receipt does not bind the current profile",
                )
            if invariant_projection(observed) != invariant_projection(committed):
                raise ValidationFailure(
                    "benchmark-invariant-mismatch",
                    "live benchmark outcomes or deterministic corpus identities changed",
                )
            expected_markdown = (args.fixture / "receipt.md").read_text(encoding="utf-8")
            if render_baseline(committed) != expected_markdown:
                raise ValidationFailure(
                    "benchmark-readback-mismatch",
                    "human-readable benchmark receipt does not match checked evidence",
                )
        rendered = render_baseline(observed) if args.format == "markdown" else json.dumps(observed, sort_keys=True, indent=2) + "\n"
        print(rendered, end="")
        return 0
    except (OSError, UnicodeError, ValidationFailure) as exc:
        code = getattr(exc, "code", "benchmark-io-failed")
        message = getattr(exc, "message", str(exc))
        print(f"{code}: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
