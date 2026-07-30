import json
import tempfile
import unittest
from pathlib import Path

from artifact_memory.context import AUTHORITY_BOUNDARY, ContextFailure, export_context
from artifact_memory.validator import validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "contracts" / "v0-valid-record.json"


class ContextTests(unittest.TestCase):
    def test_pack_is_bounded_reference_only_and_schema_valid(self):
        public = json.loads(FIXTURE.read_text(encoding="utf-8"))
        private = dict(public)
        private["record_id"] = "record://synthetic/private-0001"
        private["sensitivity"] = "private"
        evidence = [{"provider_id": "tracemap", "provider_schema_id": "https://tracemap.tools/contracts/code-fact.v1.schema.json", "provider_record_id": "fact-synthetic-status-access", "evidence_packet_ref": "artifact-version://tracemap/evidence/" + "a" * 64 + "/1", "adapter_receipt_digest": "sha-256:" + "b" * 64, "integrity_state": "integrity-verified / issuer-unverified", "coverage": "one synthetic property access", "limitations": ["static evidence only"]}]
        pack = export_context([private, public], evidence)
        schema = json.loads((ROOT / "schemas/core/context-pack.v1.schema.json").read_text(encoding="utf-8"))
        validate(pack, schema)
        self.assertEqual(pack["authority_boundary"], AUTHORITY_BOUNDARY)
        self.assertEqual(pack["selection_receipt"]["redacted_record_ids"], ["record://synthetic/private-0001"])
        self.assertEqual(pack["external_evidence"][0]["provider_id"], "tracemap")
        self.assertNotIn("facts", json.dumps(pack))

    def test_size_bound_is_explicit(self):
        record = json.loads(FIXTURE.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ContextFailure, "exceeds"):
            export_context([record], max_bytes=32)


if __name__ == "__main__":
    unittest.main()
