#!/usr/bin/env python3
"""Verify reproduced/published release equality before keyless attestation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.release_attestation import (
    ReleaseAttestationFailure,
    render_report,
    verify_release_attestation_subjects,
    write_subject_checksums,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reproduced", required=True, type=Path)
    parser.add_argument("--published", required=True, type=Path)
    parser.add_argument("--verification-receipt", required=True, type=Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = verify_release_attestation_subjects(
            args.reproduced,
            args.published,
            args.verification_receipt,
            tag=args.tag,
        )
        write_subject_checksums(report, args.out)
    except ReleaseAttestationFailure as error:
        print(f"{error.code}: {error}", file=sys.stderr)
        return 2
    print(render_report(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
