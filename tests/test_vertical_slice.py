import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from artifact_memory.tracemap_adapter import INTEGRITY_STATE
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import ValidationFailure, validate
from artifact_memory.vertical_slice import CLAIM_RECORD_ID, run_vertical_slice
from tests.test_tracemap_adapter import (
    COMMIT,
    CONFIG_DIGEST,
    RULE_CATALOG_DIGEST,
    TOOL_COMMIT,
    materialize_packet,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "fixtures" / "synthetic" / "vertical-slice" / "v1" / "source"


class TraceMapVerticalSliceTests(unittest.TestCase):
    def test_captured_exact_anchor_receipt_is_schema_valid(self):
        receipt = json.loads(
            (
                ROOT
                / "fixtures"
                / "synthetic"
                / "vertical-slice"
                / "v1"
                / "expected-receipt.json"
            ).read_text(encoding="utf-8")
        )
        validate(
            receipt,
            load_schema("adapters", "tracemap-vertical-slice-receipt.v1.schema.json"),
        )
        self.assertEqual(receipt["provider_contract_anchor"], receipt["provider_tool_source_commit"])
        receipt["authority_boundary"] = "execution approved"
        with self.assertRaises(ValidationFailure):
            validate(
                receipt,
                load_schema("adapters", "tracemap-vertical-slice-receipt.v1.schema.json"),
            )

    def test_validate_to_isolated_restore_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = run_vertical_slice(
                SOURCE,
                materialize_packet(root),
                root / "proof",
                expected_repo="SyntheticOrders",
                expected_commit=COMMIT,
                tool_source_commit=TOOL_COMMIT,
                configuration_digest=CONFIG_DIGEST,
                rule_catalog_digest=RULE_CATALOG_DIGEST,
                selected_declaration_fact_id="fact-synthetic-status-declaration",
                selected_access_fact_id="fact-synthetic-status-access",
                passphrase="synthetic-test-passphrase",
            )
            self.assertEqual(receipt["outcome"], "complete")
            self.assertEqual(receipt["integrity_state"], INTEGRITY_STATE)
            self.assertEqual(receipt["claim_record_id"], CLAIM_RECORD_ID)
            self.assertEqual(receipt["backup_outcome"], "created")
            self.assertEqual(receipt["restore_outcome"], "restored")
            self.assertTrue((root / "proof" / "isolated-restore").is_dir())

    def test_output_must_not_overlap_source(self):
        with self.assertRaisesRegex(ValueError, "does not overlap"):
            run_vertical_slice(
                SOURCE,
                SOURCE,
                SOURCE / "proof",
                expected_repo="SyntheticOrders",
                expected_commit=COMMIT,
                tool_source_commit=TOOL_COMMIT,
                configuration_digest=CONFIG_DIGEST,
                rule_catalog_digest=RULE_CATALOG_DIGEST,
                selected_declaration_fact_id="declaration",
                selected_access_fact_id="access",
                passphrase="synthetic-test-passphrase",
            )

    def test_failed_source_registration_stops_the_proof(self):
        failed = {"outcome": "failed", "diagnostics": ["object-write-failed"]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("artifact_memory.vertical_slice.register_bytes", return_value=failed):
                with self.assertRaisesRegex(RuntimeError, "content registration failed"):
                    run_vertical_slice(
                        SOURCE,
                        materialize_packet(root),
                        root / "proof",
                        expected_repo="SyntheticOrders",
                        expected_commit=COMMIT,
                        tool_source_commit=TOOL_COMMIT,
                        configuration_digest=CONFIG_DIGEST,
                        rule_catalog_digest=RULE_CATALOG_DIGEST,
                        selected_declaration_fact_id="fact-synthetic-status-declaration",
                        selected_access_fact_id="fact-synthetic-status-access",
                        passphrase="synthetic-test-passphrase",
                    )


if __name__ == "__main__":
    unittest.main()
