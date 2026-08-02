import json
import tempfile
import unittest
from pathlib import Path

from artifact_memory.location import (
    AUTHORITY_BOUNDARY,
    validate_discovery_evidence,
    validate_endpoint,
    validate_location_observation,
    validate_logical_references,
)
from artifact_memory.location_conformance import run_location_conformance
from artifact_memory.validator import ValidationFailure


ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "fixtures" / "synthetic" / "locations" / "v1" / "vectors.json"
CONTENT_REF = "content://sha-256/" + "a" * 64


class LocationContractTests(unittest.TestCase):
    def test_three_platform_fixture_resolves_one_logical_location(self):
        receipt = run_location_conformance(VECTORS)
        self.assertEqual(receipt["outcome"], "complete")
        self.assertEqual([item["platform"] for item in receipt["platform_results"]], ["macos", "windows", "linux"])
        self.assertEqual({item["resolution_outcome"] for item in receipt["platform_results"]}, {"resolved"})
        serialized = json.dumps(receipt)
        for forbidden in ("root_token", "hostname", "provider_url", "credential", "resolved_path_digest"):
            self.assertNotIn(forbidden, serialized)

    def test_logical_references_reject_local_and_bearer_forms(self):
        valid = ("artifact://synthetic/order-sample", CONTENT_REF, "endpoint://synthetic/portable-vault", "objects/order.json")
        validate_logical_references(*valid)
        invalid_paths = ("/Volumes/private/order.json", "C:\\vault\\order.json", "../order.json", "https://example.test/order?token=secret")
        for relative_path in invalid_paths:
            with self.subTest(relative_path=relative_path), self.assertRaises(ValidationFailure):
                validate_logical_references(valid[0], valid[1], valid[2], relative_path)
        with self.assertRaises(ValidationFailure):
            validate_logical_references(valid[0], valid[1], "endpoint://user:secret@example.test/vault", valid[3])

    def test_endpoint_capability_and_discovery_evidence_are_distinct(self):
        endpoint = {
            "schema_id": "artifact-memory/storage-endpoint/v1",
            "endpoint_ref": "endpoint://synthetic/portable-vault",
            "storage_class": "virtual",
            "capabilities": {"read": True, "write": False, "list": True, "verify": True, "delete": False},
            "portability_boundary": "logical identity only; discovery and machine-local resolution are separate",
        }
        evidence = {
            "schema_id": "artifact-memory/endpoint-discovery-evidence/v1",
            "evidence_id": "endpoint-discovery-evidence://synthetic/configured",
            "endpoint_ref": endpoint["endpoint_ref"],
            "observed_at": "2026-08-01T00:00:00Z",
            "evidence_kind": "configured-binding",
            "match_state": "matched",
            "evidence_digest": "sha-256:" + "b" * 64,
            "limitations": ["configuration evidence does not establish endpoint identity"],
        }
        validate_endpoint(endpoint)
        validate_discovery_evidence(evidence)
        self.assertNotEqual(endpoint["schema_id"], evidence["schema_id"])

    def test_location_state_consistency_fails_closed(self):
        observation = {
            "schema_id": "artifact-memory/location-observation/v2",
            "observation_id": "location-observation://synthetic/one",
            "artifact_ref": "artifact://synthetic/order-sample",
            "content_ref": CONTENT_REF,
            "endpoint_ref": "endpoint://synthetic/portable-vault",
            "relative_path": "objects/order.json",
            "presence_state": "absent",
            "verification_state": "content-verified",
            "observed_at": "2026-08-01T00:00:00Z",
            "discovery_evidence_ref": "endpoint-discovery-evidence://synthetic/configured",
            "authority_boundary": AUTHORITY_BOUNDARY,
        }
        with self.assertRaisesRegex(ValidationFailure, "content verification"):
            validate_location_observation(observation)

    def test_unknown_vector_schema_fails_closed(self):
        vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
        vectors["schema_id"] = "artifact-memory/location-conformance-vectors/v2"
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory) / "invalid-vectors.json"
            temporary.write_text(json.dumps(vectors), encoding="utf-8")
            with self.assertRaises(ValidationFailure):
                run_location_conformance(temporary)


if __name__ == "__main__":
    unittest.main()
