#!/usr/bin/env bash
set -euo pipefail

python3 scripts/run_scan_projection_slice.py --check >/dev/null
python3 scripts/run_context_export_slice.py --check >/dev/null
python3 scripts/run_retention_lifecycle_slice.py --check >/dev/null
python3 scripts/run_authenticity_conformance.py --check >/dev/null
python3 scripts/run_canonical_content_conformance.py --check >/dev/null
python3 scripts/run_location_conformance.py --check >/dev/null
python3 scripts/run_codex_history_conformance.py --check >/dev/null
python3 scripts/run_scan_conformance.py --check >/dev/null
python3 scripts/run_artifact_lineage_conformance.py --check >/dev/null
python3 scripts/run_legacy_lineage_conformance.py --check >/dev/null
python3 scripts/run_conformance_fixture.py --check >/dev/null
python3 scripts/run_manifest_conformance.py --check >/dev/null
python3 scripts/run_archive_conformance.py --check >/dev/null
python3 scripts/run_extension_conformance.py --check >/dev/null
python3 scripts/run_exchange_conformance.py --check >/dev/null
python3 scripts/run_independent_exchange_conformance.py --check >/dev/null
python3 scripts/run_adapter_manifest_conformance.py --check >/dev/null
python3 scripts/run_tracemap_failure_conformance.py --check >/dev/null
python3 scripts/run_vault_intake_conformance.py --check >/dev/null
python3 scripts/run_sanitized_custody_attestation.py --check >/dev/null
python3 scripts/run_release_conformance.py --check >/dev/null
python3 scripts/run_benchmark.py --check >/dev/null
python3 -m unittest tests.test_wits_conformance >/dev/null
