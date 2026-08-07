#!/usr/bin/env python3
"""Validate and render the public custody attestation contract."""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.sanitized_custody_attestation import (
    render_sanitized_custody_attestation,
    validate_historical_sanitized_custody_attestation,
    validate_historical_sanitized_custody_markdown,
    validate_sanitized_custody_attestation,
)
from artifact_memory.validator import ValidationFailure, load_json


ATTESTATION = ROOT / "evidence/sanitized/custody/v1/receipt.json"
MARKDOWN = ROOT / "evidence/sanitized/custody/v1/receipt.md"
COMPATIBILITY = (
    ROOT / "evidence/sanitized/custody/v1/compatibility/pre-provenance-v1.json",
    ROOT / "evidence/sanitized/custody/v1/compatibility/provenance-v1.json",
)
MARKDOWN_COMPATIBILITY = (
    ROOT / "evidence/sanitized/custody/v1/compatibility/markdown-pre-contract-v0.md",
    ROOT
    / "evidence/sanitized/custody/v1/compatibility/markdown-network-clarified-v0.md",
    ROOT
    / "evidence/sanitized/custody/v1/compatibility/markdown-generated-pre-provenance-v1.md",
)


def _check_markdown_compatibility(current_rendering: str) -> None:
    historical_renderings = tuple(
        path.read_text(encoding="utf-8") for path in MARKDOWN_COMPATIBILITY
    )
    for rendering in (current_rendering, *historical_renderings):
        validate_historical_sanitized_custody_markdown(
            rendering,
            current_rendering,
        )
        validate_historical_sanitized_custody_markdown(
            rendering.replace("\n", "\r\n"),
            current_rendering,
        )
    historical = historical_renderings[0]
    mutations = (
        historical.replace(
            "one non-empty snapshot completed",
            "snapshot failed",
        ),
        historical + "\nUnexpected custody assertion.\n",
    )
    for mutation in mutations:
        try:
            validate_historical_sanitized_custody_markdown(
                mutation,
                current_rendering,
            )
        except ValidationFailure as failure:
            if failure.code != "unsupported-contract-shape":
                raise
        else:
            raise ValidationFailure(
                "conformance-failed",
                "mutated custody Markdown rendering was accepted",
            )


def _check_cli_output_modes(attestation: dict[str, object]) -> None:
    commands = (
        (
            ("--format", "json"),
            (json.dumps(attestation, sort_keys=True, indent=2) + "\n").encode("utf-8"),
        ),
        (("--format", "markdown"), MARKDOWN.read_bytes()),
    )
    for arguments, expected in commands:
        actual = subprocess.check_output(
            [sys.executable, str(Path(__file__).resolve()), *arguments],
            cwd=ROOT,
        )
        if actual != expected:
            raise ValidationFailure(
                "conformance-failed",
                f"custody CLI {' '.join(arguments)} output does not match",
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args(argv)

    attestation = load_json(ATTESTATION)
    validate_sanitized_custody_attestation(attestation)
    for historical_path in COMPATIBILITY:
        historical = load_json(historical_path)
        validate_historical_sanitized_custody_attestation(historical)
        mutated = copy.deepcopy(historical)
        mutated["observed"] = "2026-08-07"
        try:
            validate_historical_sanitized_custody_attestation(mutated)
        except ValidationFailure:
            pass
        else:
            raise ValidationFailure(
                "conformance-failed",
                "mutated custody JSON compatibility record was accepted",
            )
    rendered = render_sanitized_custody_attestation(attestation)
    _check_markdown_compatibility(rendered)
    if args.check and rendered != MARKDOWN.read_text(encoding="utf-8"):
        print("sanitized custody attestation projection does not match", file=sys.stderr)
        return 1
    if args.check:
        _check_cli_output_modes(attestation)
    if args.format == "markdown":
        print(rendered, end="")
    else:
        print(json.dumps(attestation, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
