#!/usr/bin/env python3
"""Prepare an unsigned release preview for one exact candidate commit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.release_preparation import prepare_unsigned_release_preview
from artifact_memory.validator import ValidationFailure


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = prepare_unsigned_release_preview(args.repo, args.candidate, args.out)
    except (OSError, ValidationFailure) as exc:
        code = exc.code if isinstance(exc, ValidationFailure) else "release-preparation-io-failed"
        print(json.dumps({"outcome": "rejected", "diagnostics": [{"code": code}]}), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "outcome": "pass",
                "receipt_id": receipt["receipt_id"],
                "source_commit": receipt["source_commit"],
                "signature_state": receipt["signature_state"],
                "publication_state": receipt["publication_state"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
