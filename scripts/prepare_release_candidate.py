#!/usr/bin/env python3
"""Prepare exact versioned release assets without invoking owner signing authority."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.release_preparation import (
    prepare_release_candidate,
    render_release_candidate_preparation_receipt,
)
from artifact_memory.validator import ValidationFailure


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--owner-fingerprint", required=True)
    parser.add_argument("--key-generation", required=True)
    parser.add_argument(
        "--plain-text",
        action="store_true",
        help="emit the canonical human-readable preparation receipt instead of JSON",
    )
    args = parser.parse_args()
    try:
        receipt = prepare_release_candidate(
            args.repo,
            args.candidate,
            args.out,
            owner_fingerprint=args.owner_fingerprint,
            key_generation=args.key_generation,
        )
    except (OSError, ValidationFailure) as exc:
        code = exc.code if isinstance(exc, ValidationFailure) else "release-preparation-io-failed"
        print(json.dumps({"outcome": "rejected", "diagnostics": [{"code": code}]}), file=sys.stderr)
        return 2
    if args.plain_text:
        print(render_release_candidate_preparation_receipt(receipt), end="")
    else:
        print(json.dumps(
            {
                "outcome": "pass",
                "receipt_id": receipt["receipt_id"],
                "source_commit": receipt["source_commit"],
                "release_manifest_digest": receipt["release_manifest_digest"],
                "tag_message_trailer": receipt["tag_message_trailer"],
                "signature_verification_state": receipt["signature_verification_state"],
                "publication_state": receipt["publication_state"],
            },
            sort_keys=True,
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
