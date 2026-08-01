#!/usr/bin/env bash
set -euo pipefail

python3 scripts/run_scan_projection_slice.py --check >/dev/null
python3 scripts/run_context_export_slice.py --check >/dev/null
python3 scripts/run_retention_lifecycle_slice.py --check >/dev/null
python3 scripts/run_authenticity_conformance.py --check >/dev/null
python3 scripts/run_codex_history_conformance.py --check >/dev/null
python3 -m unittest tests.test_wits_conformance >/dev/null
