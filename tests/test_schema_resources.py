import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from artifact_memory.schema_resources import core_schemas, load_contract_text
from artifact_memory.validator import ValidationFailure


class SchemaResourceTests(unittest.TestCase):
    def test_packaged_sqlite_contract_is_available(self):
        contract = load_contract_text("core", "index-sqlite.v1.sql")
        self.assertIn("PRAGMA user_version = 1", contract)
        self.assertIn("CREATE TABLE provenance", contract)

    def test_malformed_packaged_core_schema_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            core = root / "core"
            core.mkdir()
            (core / "broken.schema.json").write_text(json.dumps({"type": "object"}), encoding="utf-8")
            with patch("artifact_memory.schema_resources.files", return_value=root):
                with self.assertRaisesRegex(ValidationFailure, "structurally invalid"):
                    core_schemas()


if __name__ == "__main__":
    unittest.main()
