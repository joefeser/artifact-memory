import json
import unittest
from pathlib import Path

from artifact_memory.codex_history import import_selected_task
from artifact_memory.validator import validate


ROOT = Path(__file__).resolve().parents[1]


class CodexHistoryTests(unittest.TestCase):
    def test_authorized_allowlisted_derivative_excludes_raw_material(self):
        task = json.loads((ROOT / "fixtures/synthetic/codex-history/v1/task-export.json").read_text(encoding="utf-8"))
        result = import_selected_task(task, authorized=True, selected_task_id="synthetic-task-0001")
        record = result["records"][0]
        record_schema = json.loads((ROOT / "artifact_memory/schemas/core/knowledge-record.v1.schema.json").read_text(encoding="utf-8"))
        receipt_schema = json.loads((ROOT / "artifact_memory/schemas/core/declassification-receipt.v1.schema.json").read_text(encoding="utf-8"))
        validate(record, record_schema)
        validate(result["declassification_receipt"], receipt_schema)
        encoded = json.dumps(result)
        self.assertNotIn("credential_material", encoded)
        self.assertNotIn("raw_transcript", encoded)
        self.assertEqual(result["declassification_receipt"]["outcome"], "admitted")
        self.assertEqual(record["derivative"]["source_task_ref"], "codex-task://synthetic/synthetic-task-0001")

    def test_unselected_task_is_not_admitted(self):
        task = json.loads((ROOT / "fixtures/synthetic/codex-history/v1/task-export.json").read_text(encoding="utf-8"))
        result = import_selected_task(task, authorized=True, selected_task_id="synthetic-task-9999")
        self.assertEqual(result["records"], [])
        self.assertEqual(result["declassification_receipt"]["outcome"], "not-authorized")


if __name__ == "__main__":
    unittest.main()
