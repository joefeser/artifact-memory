#!/usr/bin/env python3
"""Run or check the synthetic WITS boundary proof and checked receipts."""

from __future__ import annotations

import hashlib
import tempfile
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.canonical import canonical_bytes
from artifact_memory.conformance_cli import run_conformance_cli
from artifact_memory.synthetic_tracemap_fixture import (
    COMMIT,
    CONFIG_DIGEST,
    RULE_CATALOG_DIGEST,
    TOOL_COMMIT,
    materialize_synthetic_packet,
)
from artifact_memory.validator import load_json
from artifact_memory.vertical_slice import run_vertical_slice
from artifact_memory.wits_conformance import render_wits_conformance_receipt, run_wits_conformance


DEFAULT_FIXTURE = ROOT / "fixtures" / "synthetic" / "wits" / "v1"
PACKET_FIXTURE = ROOT / "fixtures" / "synthetic" / "tracemap-evidence" / "v1"
SOURCE = ROOT / "fixtures" / "synthetic" / "vertical-slice" / "v1" / "source"


def run_fixture(fixture: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        base = root / "base"
        packet = materialize_synthetic_packet(PACKET_FIXTURE, root)
        run_vertical_slice(
            SOURCE,
            packet,
            base,
            expected_repo="SyntheticOrders",
            expected_commit=COMMIT,
            tool_source_commit=TOOL_COMMIT,
            configuration_digest=CONFIG_DIGEST,
            rule_catalog_digest=RULE_CATALOG_DIGEST,
            selected_declaration_fact_id="fact-synthetic-status-declaration",
            selected_access_fact_id="fact-synthetic-status-access",
            passphrase="synthetic-base-passphrase",
        )
        response_template = load_json(fixture / "projection-response-v2.json")

        def synthetic_provider(request: dict[str, Any]) -> dict[str, Any]:
            return {
                **response_template,
                "request_digest": "sha-256:" + hashlib.sha256(canonical_bytes(request)).hexdigest(),
            }

        return run_wits_conformance(
            base,
            root / "wits",
            "synthetic-wits-passphrase",
            synthetic_provider,
        )


def main(argv: list[str] | None = None) -> int:
    return run_conformance_cli(
        argv,
        default_fixture=DEFAULT_FIXTURE,
        run_fixture=run_fixture,
        expected_receipt=Path("expected-receipt.json"),
        mismatch_message="WITS conformance receipt does not match checked evidence",
        render_receipt=render_wits_conformance_receipt,
        expected_markdown=Path("receipt.md"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
