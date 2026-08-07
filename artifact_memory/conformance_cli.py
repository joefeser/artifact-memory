"""Shared command-line wrapper for checked synthetic conformance receipts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from .validator import load_json


ReceiptRunner = Callable[[Path], dict[str, Any]]
ReceiptRenderer = Callable[[dict[str, Any]], str]


def run_conformance_cli(
    argv: list[str] | None,
    *,
    default_fixture: Path,
    run_fixture: ReceiptRunner,
    expected_receipt: Path,
    mismatch_message: str,
    render_receipt: ReceiptRenderer | None = None,
    expected_markdown: Path | None = None,
) -> int:
    if (render_receipt is None) != (expected_markdown is None):
        raise ValueError("render_receipt and expected_markdown must be configured together")
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=default_fixture)
    parser.add_argument("--check", action="store_true")
    if render_receipt is not None:
        parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args(argv)

    receipt = run_fixture(args.fixture)
    if args.check:
        expected = load_json(args.fixture / expected_receipt)
        markdown_matches = True
        if render_receipt is not None and expected_markdown is not None:
            try:
                markdown_matches = render_receipt(receipt) == (args.fixture / expected_markdown).read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                markdown_matches = False
        if receipt != expected or not markdown_matches:
            print(mismatch_message, file=sys.stderr)
            return 1
    if render_receipt is not None and args.format == "markdown":
        print(render_receipt(receipt), end="")
    else:
        print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0
