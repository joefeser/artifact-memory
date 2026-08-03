import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from artifact_memory.tracemap_adapter import AdapterFailure, INTEGRITY_STATE, _is_link_or_reparse_point, bind_trace_map_evidence, bind_trace_map_evidence_receipted
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import validate


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "fixtures" / "synthetic" / "tracemap-evidence" / "v1"
SOURCE_REF = "artifact-version://synthetic/orders/1"
COMMIT = "1111111111111111111111111111111111111111"
TOOL_COMMIT = "2222222222222222222222222222222222222222"
CONFIG_DIGEST = "sha-256:" + "3" * 64
RULE_CATALOG_DIGEST = "sha-256:" + "4" * 64


def bind(packet: Path, selected_fact_ids: list[str] | None = None) -> dict:
    return bind_trace_map_evidence(
        SOURCE_REF,
        packet,
        "SyntheticOrders",
        COMMIT,
        selected_fact_ids,
        tool_source_commit=TOOL_COMMIT,
        configuration_digest=CONFIG_DIGEST,
        rule_catalog_digest=RULE_CATALOG_DIGEST,
    )


def materialize_packet(root: Path) -> Path:
    packet = root / "packet"
    shutil.copytree(PACKET, packet)
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
    def test_malformed_selected_fact_ids_are_typed_in_both_apis(self):
        malformed = ["fact-synthetic-status-declaration", 7]
        with tempfile.TemporaryDirectory() as temporary:
            packet = materialize_packet(Path(temporary))
            with self.assertRaises(AdapterFailure) as raised:
                bind(packet, malformed)  # type: ignore[list-item]
            self.assertEqual(raised.exception.outcome, "trace-output-invalid")
            binding, receipt = bind_trace_map_evidence_receipted(
                SOURCE_REF,
                packet,
                "SyntheticOrders",
                COMMIT,
                malformed,  # type: ignore[arg-type]
                tool_source_commit=TOOL_COMMIT,
                configuration_digest=CONFIG_DIGEST,
                rule_catalog_digest=RULE_CATALOG_DIGEST,
            )
        self.assertIsNone(binding)
        self.assertEqual(receipt["outcome"], "trace-output-invalid")

    def test_legacy_identity_failures_remain_trace_output_invalid(self):
        with tempfile.TemporaryDirectory() as temporary:
            packet = materialize_packet(Path(temporary))
            with self.assertRaises(AdapterFailure) as configuration:
                bind_trace_map_evidence(
                    SOURCE_REF,
                    packet,
                    "SyntheticOrders",
                    COMMIT,
                    tool_source_commit=TOOL_COMMIT,
                    configuration_digest="invalid",
                    rule_catalog_digest=RULE_CATALOG_DIGEST,
                )
            self.assertEqual(configuration.exception.outcome, "trace-output-invalid")
            with self.assertRaises(AdapterFailure) as catalog:
                bind_trace_map_evidence(
                    SOURCE_REF,
                    packet,
                    "SyntheticOrders",
                    COMMIT,
                    tool_source_commit=TOOL_COMMIT,
                    configuration_digest=CONFIG_DIGEST,
                    rule_catalog_digest="invalid",
                )
            self.assertEqual(catalog.exception.outcome, "trace-output-invalid")

    def test_binding_is_deterministic_and_preserves_boundary(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            left = bind(materialize_packet(Path(first)), ["fact-synthetic-status-declaration"])
            right = bind(materialize_packet(Path(second)), ["fact-synthetic-status-declaration"])
        self.assertEqual(left, right)
        self.assertEqual(left["integrity_state"], INTEGRITY_STATE)
        self.assertEqual(left["provider"]["id"], "tracemap")
        self.assertEqual(left["provider"]["tool_source_commit"], TOOL_COMMIT)
        self.assertEqual(left["selected_provider_records"][0]["rule_id"], "csharp.semantic.declaration.v1")
        self.assertFalse(left["relations"][0]["supports_claim"])

    def test_missing_packet_artifact_is_typed(self):
        with tempfile.TemporaryDirectory() as temporary:
            packet = materialize_packet(Path(temporary))
            (packet / "report.md").unlink()
            with self.assertRaisesRegex(Exception, "required provider artifact"):
                bind(packet)

    def test_foreign_repo_fact_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            packet = materialize_packet(Path(temporary))
            facts_path = packet / "facts.ndjson"
            facts = [json.loads(line) for line in facts_path.read_text(encoding="utf-8").splitlines()]
            facts[0]["repo"] = "ForeignRepository"
            facts_path.write_text("\n".join(json.dumps(fact, sort_keys=True) for fact in facts) + "\n", encoding="utf-8")
            with self.assertRaises(AdapterFailure) as raised:
                bind(packet)
            self.assertEqual(raised.exception.outcome, "trace-output-invalid")

    def test_sqlite_repo_parity_is_verified(self):
        with tempfile.TemporaryDirectory() as temporary:
            packet = materialize_packet(Path(temporary))
            connection = sqlite3.connect(packet / "index.sqlite")
            connection.execute("update facts set repo = 'ForeignRepository' where fact_id = 'fact-synthetic-status-declaration'")
            connection.commit()
            connection.close()
            with self.assertRaises(AdapterFailure) as raised:
                bind(packet)
            self.assertEqual(raised.exception.outcome, "digest-mismatch")

    def test_non_array_known_gaps_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            packet = materialize_packet(Path(temporary))
            manifest_path = packet / "scan-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["knownGaps"] = "none"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(AdapterFailure) as raised:
                bind(packet)
            self.assertEqual(raised.exception.outcome, "trace-output-invalid")

    def test_log_is_bound_as_opaque_bytes_without_new_encoding_requirement(self):
        with tempfile.TemporaryDirectory() as temporary:
            packet = materialize_packet(Path(temporary))
            (packet / "logs" / "analyzer.log").write_bytes(b"\xff")
            binding = bind(packet)
            log = next(item for item in binding["content_objects"] if item["name"] == "logs/analyzer.log")
            self.assertEqual(log["digest"], "sha-256:" + hashlib.sha256(b"\xff").hexdigest())

    def test_legacy_v1_binding_shape_remains_schema_valid(self):
        with tempfile.TemporaryDirectory() as temporary:
            binding = bind(materialize_packet(Path(temporary)))
        binding.pop("selected_provider_records")
        binding["provider"].pop("tool_source_commit")
        binding["provider"].pop("configuration_digest")
        binding["provider"].pop("rule_catalog_digest")
        validate(binding, load_schema("adapters", "tracemap-evidence-binding.v1.schema.json"))

    def test_known_gaps_produce_partial_evidence_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            binding = bind(materialize_packet(Path(temporary)))
        self.assertEqual(binding["receipt"]["outcome"], "partial-evidence-admitted")

    def test_sqlite_non_identity_fact_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            packet = materialize_packet(Path(temporary))
            connection = sqlite3.connect(packet / "index.sqlite")
            connection.execute(
                "update facts set evidence_tier = 'Tier4Unknown' where fact_id = 'fact-synthetic-status-declaration'"
            )
            connection.commit()
            connection.close()
            with self.assertRaises(AdapterFailure) as raised:
                bind(packet)
            self.assertEqual(raised.exception.outcome, "digest-mismatch")

    @unittest.skipIf(os.name == "nt", "symlink creation is not portable on Windows CI")
    def test_required_packet_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            packet = materialize_packet(Path(temporary))
            report = packet / "report.md"
            target = packet / "external-report.md"
            report.rename(target)
            report.symlink_to(target)
            with self.assertRaises(AdapterFailure) as raised:
                bind(packet)
            self.assertEqual(raised.exception.outcome, "unsafe-provenance-rejected")

    @unittest.skipIf(os.name == "nt", "symlink creation is not portable on Windows CI")
    def test_required_packet_parent_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            packet = materialize_packet(Path(temporary))
            logs = packet / "logs"
            external_logs = packet / "external-logs"
            logs.rename(external_logs)
            logs.symlink_to(external_logs, target_is_directory=True)
            with self.assertRaises(AdapterFailure) as raised:
                bind(packet)
            self.assertEqual(raised.exception.outcome, "unsafe-provenance-rejected")

    def test_malformed_manifest_scalar_is_typed(self):
        with tempfile.TemporaryDirectory() as temporary:
            packet = materialize_packet(Path(temporary))
            manifest_path = packet / "scan-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["scannedAt"] = 7
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(AdapterFailure) as raised:
                bind(packet)
            self.assertEqual(raised.exception.outcome, "trace-output-invalid")

    def test_malformed_index_scalar_is_typed(self):
        with tempfile.TemporaryDirectory() as temporary:
            packet = materialize_packet(Path(temporary))
            connection = sqlite3.connect(packet / "index.sqlite")
            connection.execute("update scan_manifest set scanned_at = 'not-a-date'")
            connection.commit()
            connection.close()
            with self.assertRaises(AdapterFailure) as raised:
                bind(packet)
            self.assertEqual(raised.exception.outcome, "trace-output-invalid")

    def test_uncheckpointed_sqlite_sidecar_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            packet = materialize_packet(Path(temporary))
            (packet / "index.sqlite-wal").write_bytes(b"synthetic-wal")
            with self.assertRaises(AdapterFailure) as raised:
                bind(packet)
            self.assertEqual(raised.exception.outcome, "trace-output-invalid")

    def test_windows_reparse_attribute_is_detected_portably(self):
        fake_metadata = SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400)
        with patch("artifact_memory.tracemap_adapter.os.lstat", return_value=fake_metadata):
            self.assertTrue(_is_link_or_reparse_point(Path("synthetic")))


if __name__ == "__main__":
    unittest.main()
