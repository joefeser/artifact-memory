import json
import unittest
from copy import deepcopy
from pathlib import Path

from artifact_memory.codex_history import (
    import_selected_task,
    import_task_export,
    sanitize_private_import_receipt,
    sanitized_dogfood_receipt,
)
from artifact_memory.canonical import receipt_with_digest
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import ValidationFailure, validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "codex-history" / "v1"


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

    def test_v2_import_creates_valid_vendor_neutral_derivatives(self):
        task = json.loads((FIXTURE / "task-export.json").read_text(encoding="utf-8"))
        policy = json.loads((FIXTURE / "import-policy.json").read_text(encoding="utf-8"))
        result = import_task_export(task, policy)
        records = result["records"]
        labels = {record["meaning"]["labels"][1] for record in records}
        self.assertEqual(labels, {"decision", "research", "workstream", "question"})
        for record in records:
            validate(record, load_schema("core", "knowledge-record.v2.schema.json"))
            self.assertEqual(record["lifecycle"], "draft")
            self.assertEqual(record["derivative"]["source_task_ref"], "codex-task://synthetic/synthetic-task-0001")
            self.assertEqual(len(record["provenance"]), 2)
        receipt = result["declassification_receipt"]
        validate(receipt, load_schema("core", "declassification-receipt.v2.schema.json"))
        self.assertEqual(receipt["raw_source_expires_at"], "2026-11-01T00:00:00Z")
        self.assertFalse(receipt["raw_source_canonical"])
        self.assertEqual(receipt["deletion_route"], "artifact-memory/retention-deletion/v2")
        encoded = json.dumps(result)
        for marker in (
            "SYNTHETIC-ONLY-RAW-TRANSCRIPT",
            "SYNTHETIC-ONLY-ATTACHMENT",
            "SYNTHETIC-ONLY-NOT-A-CREDENTIAL",
            "SYNTHETIC-LOCAL-PATH",
            "SYNTHETIC-ONLY-BROWSER-STATE",
            "SYNTHETIC-EXCLUDED-CONTENT",
        ):
            self.assertNotIn(marker, encoded)

    def test_v2_import_fails_closed_on_selection_and_authority(self):
        task = json.loads((FIXTURE / "task-export.json").read_text(encoding="utf-8"))
        policy = json.loads((FIXTURE / "import-policy.json").read_text(encoding="utf-8"))
        for mutation in (
            lambda value: value.update(selected_task_id="synthetic-task-9999"),
            lambda value: value.update(authorization_state="withheld"),
        ):
            with self.subTest(mutation=mutation):
                changed = deepcopy(policy)
                mutation(changed)
                result = import_task_export(task, changed)
                self.assertEqual(result["records"], [])
                self.assertEqual(result["declassification_receipt"]["outcome"], "not-authorized")

    def test_v2_import_rejects_sensitive_or_unbounded_allowlisted_text(self):
        task = json.loads((FIXTURE / "task-export.json").read_text(encoding="utf-8"))
        policy = json.loads((FIXTURE / "import-policy.json").read_text(encoding="utf-8"))
        for summary in (
            "Read /local/private/value.txt next.",
            "Author" + "ization: Bearer synthetic-value-that-must-not-pass",
            "x" * 4_097,
        ):
            with self.subTest(summary=summary[:20]):
                changed = deepcopy(task)
                changed["summary"] = summary
                with self.assertRaises(ValidationFailure):
                    import_task_export(changed, policy)
        changed = deepcopy(task)
        changed["decisions"] = "not-an-array"
        with self.assertRaises(ValidationFailure):
            import_task_export(changed, policy)

    def test_local_policy_requires_private_owner_authority_and_future_expiry(self):
        task = json.loads((FIXTURE / "task-export.json").read_text(encoding="utf-8"))
        policy = json.loads((FIXTURE / "import-policy.json").read_text(encoding="utf-8"))
        local = deepcopy(policy)
        local.update(
            source_scope="local",
            authority_ref="authority://owner/codex-task-selection",
            record_sensitivity="private",
        )
        result = import_task_export(task, local)
        self.assertTrue(result["records"])
        self.assertTrue(all(record["sensitivity"] == "private" for record in result["records"]))
        for mutation in (
            lambda value: value.update(record_sensitivity="public"),
            lambda value: value.update(authority_ref="authority://adapter/self-asserted"),
            lambda value: value.update(raw_source_expires_at=value["authorized_at"]),
        ):
            with self.subTest(mutation=mutation):
                changed = deepcopy(local)
                mutation(changed)
                with self.assertRaises(ValidationFailure):
                    import_task_export(task, changed)

    def test_public_dogfood_receipt_discloses_only_counts_and_outcome(self):
        receipt = sanitized_dogfood_receipt(
            performed_at="2026-08-01T00:00:00Z",
            record_type_counts={"decision": 1, "research": 1, "workstream": 1, "question": 0},
        )
        validate(receipt, load_schema("core", "codex-history-dogfood-receipt.v1.schema.json"))
        encoded = json.dumps(receipt)
        self.assertNotIn("codex-task://", encoded)
        self.assertNotIn("source_task_ref", encoded)
        self.assertFalse(receipt["source_task_identity_disclosed"])
        self.assertEqual(receipt["owner_review_state"], "required")

    def test_only_an_admitted_local_receipt_can_be_sanitized(self):
        task = json.loads((FIXTURE / "task-export.json").read_text(encoding="utf-8"))
        policy = json.loads((FIXTURE / "import-policy.json").read_text(encoding="utf-8"))
        local = deepcopy(policy)
        local.update(
            source_scope="local",
            authority_ref="authority://owner/codex-task-selection",
            record_sensitivity="private",
        )
        private_receipt = import_task_export(task, local)["declassification_receipt"]
        public_receipt = sanitize_private_import_receipt(
            private_receipt,
            performed_at="2026-08-01T00:00:00Z",
        )
        self.assertEqual(public_receipt["records_validated"], 4)
        synthetic_receipt = import_task_export(task, policy)["declassification_receipt"]
        with self.assertRaisesRegex(ValidationFailure, "selected local task"):
            sanitize_private_import_receipt(
                synthetic_receipt,
                performed_at="2026-08-01T00:00:00Z",
            )
        mismatched = deepcopy(private_receipt)
        mismatched["record_type_counts"]["question"] = 0
        with self.assertRaisesRegex(ValidationFailure, "counts"):
            sanitize_private_import_receipt(
                mismatched,
                performed_at="2026-08-01T00:00:00Z",
            )

    def test_checked_operational_receipt_is_schema_valid_and_digest_identified(self):
        receipt_path = (
            ROOT / "evidence" / "sanitized" / "codex-history" / "v1" / "receipt.json"
        )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        validate(
            receipt,
            load_schema("core", "codex-history-dogfood-receipt.v1.schema.json"),
        )
        body = {
            key: value
            for key, value in receipt.items()
            if key not in {"schema_id", "receipt_id"}
        }
        self.assertEqual(
            receipt,
            receipt_with_digest(
                "artifact-memory/codex-history-dogfood-receipt/v1",
                "codex-history-dogfood-receipt://",
                body,
            ),
        )
        self.assertEqual(receipt["owner_review_state"], "required")


if __name__ == "__main__":
    unittest.main()
