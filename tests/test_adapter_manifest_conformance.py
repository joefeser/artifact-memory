import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from artifact_memory.adapter_manifest_conformance import render_adapter_manifest_conformance_receipt, run_adapter_manifest_conformance
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import ValidationFailure, validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/synthetic/adapters/v1"


class AdapterManifestConformanceTests(unittest.TestCase):
    def test_checked_machine_and_human_receipts_replay(self):
        receipt = run_adapter_manifest_conformance(FIXTURE)
        expected = json.loads((FIXTURE / "expected-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt, expected)
        self.assertEqual(render_adapter_manifest_conformance_receipt(receipt), (FIXTURE / "receipt.md").read_text(encoding="utf-8"))

    def test_extension_evidence_rejects_duplicate_reordered_and_cross_wired_cases(self):
        receipt = run_adapter_manifest_conformance(FIXTURE)
        schema = load_schema("adapters", "adapter-manifest-conformance-receipt.v2.schema.json")
        mutations = []
        duplicate = copy.deepcopy(receipt)
        duplicate["extension_cases"][1] = copy.deepcopy(duplicate["extension_cases"][0])
        mutations.append(duplicate)
        reordered = copy.deepcopy(receipt)
        reordered["extension_cases"][0], reordered["extension_cases"][1] = reordered["extension_cases"][1], reordered["extension_cases"][0]
        mutations.append(reordered)
        cross_wired = copy.deepcopy(receipt)
        cross_wired["extension_cases"][0]["preserved"] = False
        mutations.append(cross_wired)
        missing = copy.deepcopy(receipt)
        missing["extension_cases"].pop()
        mutations.append(missing)
        for malformed in mutations:
            with self.assertRaises(ValidationFailure):
                validate(malformed, schema)

    def test_swapped_fixture_roles_fail_closed(self):
        class SwappedFixture:
            def __truediv__(self, name):
                return FIXTURE / ("unauthorized-reference-manifest.json" if name == "independent-reference-manifest.json" else "independent-reference-manifest.json")

        with self.assertRaises(ValidationFailure):
            run_adapter_manifest_conformance(SwappedFixture())

    def test_tracemap_capability_escalation_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "fixture"
            shutil.copytree(FIXTURE, copied)
            manifest_path = copied / "tracemap-read-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["capabilities"]["network"] = "read"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "bounded local-read"):
                run_adapter_manifest_conformance(copied)

    def test_tracemap_extra_read_capability_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "fixture"
            shutil.copytree(FIXTURE, copied)
            manifest_path = copied / "tracemap-read-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["capabilities"]["read_capabilities"].append("synthetic-extra-read")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "bounded local-read"):
                run_adapter_manifest_conformance(copied)

    def test_denied_vector_may_differ_only_by_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "fixture"
            shutil.copytree(FIXTURE, copied)
            manifest_path = copied / "unauthorized-reference-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["capabilities"]["network"] = "read"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "differ from the reference only"):
                run_adapter_manifest_conformance(copied)


if __name__ == "__main__":
    unittest.main()
