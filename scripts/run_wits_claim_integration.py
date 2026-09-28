#!/usr/bin/env python3
"""Run pickup against the exact WITS claim-policy repair and an owned fixture."""
import sys
import subprocess
from run_wits_http_integration import run_proof

WITS_REF = "5a04c0d7d6d834f1708eda85b286ef576fa8d0af"

if __name__ == '__main__':
    try:
        run_proof(WITS_REF, 'tests.test_coordination_claim_wits', 'am156')
    except (KeyError, OSError, RuntimeError, subprocess.SubprocessError):
        print('WITS pickup proof failed; no acceptance claim', file=sys.stderr)
        sys.exit(1)
