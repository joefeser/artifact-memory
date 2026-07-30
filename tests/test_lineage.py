import json
import unittest
from pathlib import Path

from artifact_memory.lineage import observe_legacy_file
from artifact_memory.validator import validate


class LineageTests(unittest.TestCase):
    def test_none_hash_is_observed_without_identity_upgrade(self):
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root / "schemas/core/legacy-observation.v1.schema.json").read_text(encoding="utf-8"))
        observation = observe_legacy_file({"path": "synthetic/legacy/file.bin", "size": 1024, "created": "2010", "modified": "2010", "sha1": "NONE"}, "https://github.com/joefeser/WhereAreMyFiles")
        validate(observation, schema)
        self.assertEqual(observation["historical_fields"]["legacy_hash"]["state"], "none-recorded")
        self.assertEqual(observation["historical_fields"]["legacy_hash"]["value"], "NONE")
        self.assertEqual(observation["artifact_identity"], "not-established")


if __name__ == "__main__":
    unittest.main()
