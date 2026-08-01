import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from artifact_memory.canonical import canonical_bytes
from artifact_memory.vertical_slice import run_vertical_slice
from artifact_memory.wits_conformance import run_wits_conformance
from tests.test_tracemap_adapter import (
    COMMIT, CONFIG_DIGEST, RULE_CATALOG_DIGEST, TOOL_COMMIT, materialize_packet,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "fixtures/synthetic/vertical-slice/v1/source"


class WitsConformanceTests(unittest.TestCase):
    def test_trace_context_rebuild_and_restore_stops_before_hacp(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base"
            run_vertical_slice(
                SOURCE, materialize_packet(root), base,
                expected_repo="SyntheticOrders", expected_commit=COMMIT,
                tool_source_commit=TOOL_COMMIT, configuration_digest=CONFIG_DIGEST,
                rule_catalog_digest=RULE_CATALOG_DIGEST,
                selected_declaration_fact_id="fact-synthetic-status-declaration",
                selected_access_fact_id="fact-synthetic-status-access",
                passphrase="synthetic-base-passphrase",
            )
            response_template = json.loads((ROOT / "fixtures/synthetic/wits/v1/projection-response-v2.json").read_text())

            def synthetic_provider(request):
                return {
                    **response_template,
                    "request_digest": "sha-256:" + hashlib.sha256(canonical_bytes(request)).hexdigest(),
                }

            receipt = run_wits_conformance(base, root / "wits", "synthetic-wits-passphrase", synthetic_provider)
            self.assertEqual(receipt["outcome"], "complete")
            self.assertEqual(receipt["fixture_end"], "before_hacp_task_creation_or_execution")
            self.assertEqual(receipt["wits_projection_ref"], response_template["projection_ref"])
            self.assertEqual(receipt["wits_artifact_version_ref"], "artifact-version://synthetic/wits-projection/1")
            self.assertNotIn("destination", str(receipt))


if __name__ == "__main__":
    unittest.main()
