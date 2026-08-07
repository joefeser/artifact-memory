"""Materialize the checked synthetic TraceMap packet for conformance proofs."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

from .validator import load_json, load_json_bytes


SOURCE_REF = "artifact-version://synthetic/orders/1"
COMMIT = "1111111111111111111111111111111111111111"
TOOL_COMMIT = "2222222222222222222222222222222222222222"
CONFIG_DIGEST = "sha-256:" + "3" * 64
RULE_CATALOG_DIGEST = "sha-256:" + "4" * 64


def materialize_synthetic_packet(packet_fixture: Path, root: Path) -> Path:
    """Build generated SQLite/log views from checked provider-neutral packet bytes."""
    packet = root / "packet"
    shutil.copytree(packet_fixture, packet)
    (packet / "logs").mkdir(exist_ok=True)
    (packet / "logs" / "analyzer.log").write_text(
        "scanId=scan-synthetic-orders-v1\n"
        "repo=SyntheticOrders\n"
        f"commitSha={COMMIT}\n"
        "analysisLevel=Level1SemanticAnalysis\n"
        "buildStatus=Succeeded\n"
        "facts=2\n",
        encoding="utf-8",
    )
    connection = sqlite3.connect(packet / "index.sqlite")
    try:
        connection.executescript((packet / "index.sqlite.sql").read_text(encoding="utf-8"))
        manifest = load_json(packet / "scan-manifest.json")
        facts = [
            load_json_bytes(line.encode("utf-8"))
            for line in (packet / "facts.ndjson").read_text(encoding="utf-8").splitlines()
        ]
        connection.execute(
            "insert into scan_manifest values (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                manifest["scanId"], manifest["repoName"], manifest["commitSha"],
                manifest["scannerVersion"], manifest["scannedAt"], manifest["analysisLevel"],
                manifest["buildStatus"], canonical_json(manifest),
            ),
        )
        for fact in facts:
            evidence = fact["evidence"]
            connection.execute(
                "insert into facts values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fact["factId"], fact["scanId"], fact["repo"], fact["commitSha"],
                    fact.get("projectPath"), fact["factType"], fact["ruleId"], fact["evidenceTier"],
                    fact.get("sourceSymbol"), fact.get("targetSymbol"), fact.get("contractElement"),
                    evidence["filePath"], evidence["startLine"], evidence["endLine"],
                    evidence.get("snippetHash"), evidence["extractorId"], evidence["extractorVersion"],
                    canonical_json(fact["properties"]),
                ),
            )
        connection.commit()
    finally:
        connection.close()
    return packet


def canonical_json(value: object) -> str:
    """Match TraceMap's generated JSON columns without accepting ambiguous input."""
    return json.dumps(value, sort_keys=True)
