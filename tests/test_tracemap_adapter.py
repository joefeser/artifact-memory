import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from artifact_memory.tracemap_adapter import AdapterFailure, INTEGRITY_STATE, bind_trace_map_evidence


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "fixtures" / "synthetic" / "tracemap-evidence" / "v1"
SOURCE_REF = "artifact-version://synthetic/orders/1"
COMMIT = "1111111111111111111111111111111111111111"


def materialize_packet(root: Path) -> Path:
    packet = root / "packet"
    shutil.copytree(PACKET, packet)
    connection = sqlite3.connect(packet / "index.sqlite")
    connection.executescript((packet / "index.sqlite.sql").read_text(encoding="utf-8"))
    manifest = json.loads((packet / "scan-manifest.json").read_text(encoding="utf-8"))
    facts = [json.loads(line) for line in (packet / "facts.ndjson").read_text(encoding="utf-8").splitlines()]
    connection.execute("insert into scan_manifest values (?, ?, ?, ?, ?, ?, ?, ?)", (manifest["scanId"], manifest["repoName"], manifest["commitSha"], manifest["scannerVersion"], manifest["scannedAt"], manifest["analysisLevel"], manifest["buildStatus"], json.dumps(manifest, sort_keys=True)))
    for fact in facts:
        evidence = fact["evidence"]
        connection.execute("insert into facts values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (fact["factId"], fact["scanId"], fact["repo"], fact["commitSha"], fact.get("projectPath"), fact["factType"], fact["ruleId"], fact["evidenceTier"], fact.get("sourceSymbol"), fact.get("targetSymbol"), fact.get("contractElement"), evidence["filePath"], evidence["startLine"], evidence["endLine"], evidence.get("snippetHash"), evidence["extractorId"], evidence["extractorVersion"], json.dumps(fact["properties"], sort_keys=True)))
    connection.commit()
    connection.close()
    return packet


class TraceMapAdapterTests(unittest.TestCase):
    def test_binding_is_deterministic_and_preserves_boundary(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            left = bind_trace_map_evidence(SOURCE_REF, materialize_packet(Path(first)), "SyntheticOrders", COMMIT, ["fact-synthetic-status-declaration"])
            right = bind_trace_map_evidence(SOURCE_REF, materialize_packet(Path(second)), "SyntheticOrders", COMMIT, ["fact-synthetic-status-declaration"])
        self.assertEqual(left, right)
        self.assertEqual(left["integrity_state"], INTEGRITY_STATE)
        self.assertEqual(left["provider"]["id"], "tracemap")
        self.assertFalse(left["relations"][0]["supports_claim"])

    def test_missing_packet_artifact_is_typed(self):
        with tempfile.TemporaryDirectory() as temporary:
            packet = materialize_packet(Path(temporary))
            (packet / "report.md").unlink()
            with self.assertRaisesRegex(Exception, "required provider artifact"):
                bind_trace_map_evidence(SOURCE_REF, packet, "SyntheticOrders", COMMIT)

    def test_foreign_repo_fact_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            packet = materialize_packet(Path(temporary))
            facts_path = packet / "facts.ndjson"
            facts = [json.loads(line) for line in facts_path.read_text(encoding="utf-8").splitlines()]
            facts[0]["repo"] = "ForeignRepository"
            facts_path.write_text("\n".join(json.dumps(fact, sort_keys=True) for fact in facts) + "\n", encoding="utf-8")
            with self.assertRaises(AdapterFailure) as raised:
                bind_trace_map_evidence(SOURCE_REF, packet, "SyntheticOrders", COMMIT)
            self.assertEqual(raised.exception.outcome, "trace-output-invalid")

    def test_sqlite_repo_parity_is_verified(self):
        with tempfile.TemporaryDirectory() as temporary:
            packet = materialize_packet(Path(temporary))
            connection = sqlite3.connect(packet / "index.sqlite")
            connection.execute("update facts set repo = 'ForeignRepository' where fact_id = 'fact-synthetic-status-declaration'")
            connection.commit()
            connection.close()
            with self.assertRaises(AdapterFailure) as raised:
                bind_trace_map_evidence(SOURCE_REF, packet, "SyntheticOrders", COMMIT)
            self.assertEqual(raised.exception.outcome, "digest-mismatch")


if __name__ == "__main__":
    unittest.main()
