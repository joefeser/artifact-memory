import copy
import json
import unittest
from pathlib import Path

from artifact_memory.artifact_lineage import validate_artifact, validate_artifact_lineage, validate_artifact_version
from artifact_memory.artifact_lineage_conformance import render_artifact_lineage_receipt, run_artifact_lineage_conformance
from artifact_memory.validator import ValidationFailure


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "artifact-lineage" / "v1"


class ArtifactLineageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vectors = json.loads((FIXTURE / "vectors.json").read_text(encoding="utf-8"))

    def test_checked_multi_version_derivative_fixture(self):
        receipt = run_artifact_lineage_conformance(FIXTURE / "vectors.json")
        expected = json.loads((FIXTURE / "expected-receipt.json").read_text(encoding="utf-8"))
        markdown = (FIXTURE / "receipt.md").read_text(encoding="utf-8")
        self.assertEqual(receipt, expected)
        self.assertEqual(render_artifact_lineage_receipt(receipt), markdown)
        self.assertEqual(set(receipt["role_counts"]), {"original", "normalized", "redacted", "derived", "released"})
        self.assertTrue(receipt["retained_history"])

    def test_version_identity_binds_artifact_and_revision(self):
        version = copy.deepcopy(self.vectors["versions"][0])
        version["revision"] = 2
        with self.assertRaises(ValidationFailure) as failure:
            validate_artifact_version(version)
        self.assertEqual(failure.exception.code, "artifact-version-identity-invalid")

    def test_non_original_role_requires_typed_source_lineage(self):
        version = copy.deepcopy(self.vectors["versions"][2])
        version["relationships"] = []
        with self.assertRaises(ValidationFailure) as failure:
            validate_artifact_version(version)
        self.assertEqual(failure.exception.code, "artifact-version-source-required")

    def test_same_artifact_lineage_requires_retained_earlier_target(self):
        versions = copy.deepcopy(self.vectors["versions"])
        versions[2]["relationships"][0]["target_ref"] = "artifact-version://synthetic/design-note/99"
        with self.assertRaises(ValidationFailure) as failure:
            validate_artifact_lineage(self.vectors["artifact"], versions)
        self.assertEqual(failure.exception.code, "artifact-version-lineage-target-missing")

    def test_supersession_cannot_point_forward_or_replace_history(self):
        versions = copy.deepcopy(self.vectors["versions"])
        versions[1]["relationships"].append({"type": "supersedes", "target_ref": "artifact-version://synthetic/design-note/6"})
        with self.assertRaises(ValidationFailure) as failure:
            validate_artifact_lineage(self.vectors["artifact"], versions)
        self.assertEqual(failure.exception.code, "artifact-version-lineage-order-invalid")
        self.assertEqual(len(versions), 6)

        external = copy.deepcopy(self.vectors["versions"])
        external[-1]["relationships"][-1]["target_ref"] = "artifact-version://synthetic/other-artifact/1"
        with self.assertRaises(ValidationFailure) as external_failure:
            validate_artifact_lineage(self.vectors["artifact"], external)
        self.assertEqual(external_failure.exception.code, "artifact-version-supersession-target-invalid")

    def test_required_extensions_fail_closed(self):
        artifact = copy.deepcopy(self.vectors["artifact"])
        artifact["extensions"] = {
            "https://synthetic.example/artifact/v1": {"version": "v1", "required": True, "value": {"synthetic": True}}
        }
        with self.assertRaises(ValidationFailure) as failure:
            validate_artifact(artifact)
        self.assertEqual(failure.exception.code, "required-extension-unsupported")


if __name__ == "__main__":
    unittest.main()
