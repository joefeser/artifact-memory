import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from artifact_memory.codex_history import (
    import_selected_task,
    import_task_export,
    sanitize_private_import_receipt,
    sanitized_dogfood_receipt,
    write_import_bundle,
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

    def test_v2_record_identity_is_independent_of_source_task_identity(self):
        task = json.loads((FIXTURE / "task-export.json").read_text(encoding="utf-8"))
        policy = json.loads((FIXTURE / "import-policy.json").read_text(encoding="utf-8"))
        first = import_task_export(task, policy)
        rekeyed_task = deepcopy(task)
        rekeyed_task["task_id"] = "synthetic-task-rekeyed"
        rekeyed_policy = deepcopy(policy)
        rekeyed_policy["selected_task_id"] = rekeyed_task["task_id"]
        second = import_task_export(rekeyed_task, rekeyed_policy)
        self.assertEqual(
            sorted(record["record_id"] for record in first["records"]),
            sorted(record["record_id"] for record in second["records"]),
        )
        self.assertNotEqual(
            first["records"][0]["derivative"]["source_task_ref"],
            second["records"][0]["derivative"]["source_task_ref"],
        )

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
            "See /tmp for details.",
            "Config in /etc.",
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

    def test_v2_import_rejects_non_object_policy_with_typed_failure(self):
        task = json.loads((FIXTURE / "task-export.json").read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ValidationFailure, "one import policy object"):
            import_task_export(task, [])  # type: ignore[arg-type]

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
        self.assertEqual(
            receipt["authority_boundary"],
            "derivative knowledge only; no execution, mutation, spending, deployment, credential use, declassification, disclosure, routing, merge, or approval authority",
        )

    def test_public_dogfood_receipt_rejects_untyped_counts(self):
        valid = {"decision": 1, "research": 1, "workstream": 1, "question": 0}
        for invalid in (
            {**valid, "decision": "1"},
            {**valid, "question": False},
            {key: value for key, value in valid.items() if key != "question"},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValidationFailure, "four integer counters"):
                    sanitized_dogfood_receipt(
                        performed_at="2026-08-01T00:00:00Z",
                        record_type_counts=invalid,
                    )

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
        mismatched_body = {
            key: value
            for key, value in mismatched.items()
            if key not in {"schema_id", "receipt_id"}
        }
        mismatched = receipt_with_digest(
            "artifact-memory/declassification-receipt/v2",
            "declassification-receipt://",
            mismatched_body,
        )
        with self.assertRaisesRegex(ValidationFailure, "admitted record set"):
            sanitize_private_import_receipt(
                mismatched,
                performed_at="2026-08-01T00:00:00Z",
            )

        forged_id = deepcopy(private_receipt)
        forged_id["receipt_id"] = "declassification-receipt://" + "0" * 64
        with self.assertRaisesRegex(ValidationFailure, "canonical body"):
            sanitize_private_import_receipt(
                forged_id,
                performed_at="2026-08-01T00:00:00Z",
            )

        fabricated_types = deepcopy(private_receipt)
        fabricated_types["admitted_records"][-1]["record_type"] = "workstream"
        fabricated_body = {
            key: value
            for key, value in fabricated_types.items()
            if key not in {"schema_id", "receipt_id"}
        }
        fabricated_types = receipt_with_digest(
            "artifact-memory/declassification-receipt/v2",
            "declassification-receipt://",
            fabricated_body,
        )
        with self.assertRaisesRegex(ValidationFailure, "admitted record set"):
            sanitize_private_import_receipt(
                fabricated_types,
                performed_at="2026-08-01T00:00:00Z",
            )

        duplicate_ids = deepcopy(private_receipt)
        duplicate_id = duplicate_ids["admitted_record_ids"][0]
        duplicate_ids["admitted_record_ids"][-1] = duplicate_id
        duplicate_ids["admitted_records"][-1]["record_id"] = duplicate_id
        duplicate_body = {
            key: value
            for key, value in duplicate_ids.items()
            if key not in {"schema_id", "receipt_id"}
        }
        duplicate_ids = receipt_with_digest(
            "artifact-memory/declassification-receipt/v2",
            "declassification-receipt://",
            duplicate_body,
        )
        with self.assertRaisesRegex(ValidationFailure, "admitted record set"):
            sanitize_private_import_receipt(
                duplicate_ids,
                performed_at="2026-08-01T00:00:00Z",
            )

    def test_import_bundle_is_not_published_after_a_write_failure(self):
        task = json.loads((FIXTURE / "task-export.json").read_text(encoding="utf-8"))
        policy = json.loads((FIXTURE / "import-policy.json").read_text(encoding="utf-8"))
        result = import_task_export(task, policy)
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            output = parent / "bundle"
            with patch.object(
                Path,
                "write_text",
                side_effect=OSError("synthetic write failure"),
            ):
                with self.assertRaises(OSError):
                    write_import_bundle(result, output)
            self.assertFalse(output.exists())
            self.assertEqual(list(parent.glob(".bundle.pending-*")), [])

    def test_import_bundle_rejects_a_receipt_for_a_different_record_set(self):
        task = json.loads((FIXTURE / "task-export.json").read_text(encoding="utf-8"))
        policy = json.loads((FIXTURE / "import-policy.json").read_text(encoding="utf-8"))
        result = import_task_export(task, policy)
        mismatched = deepcopy(result)
        replacement_id = "record://codex-derivative/" + "0" * 64
        receipt = mismatched["declassification_receipt"]
        receipt["admitted_record_ids"][0] = replacement_id
        receipt["admitted_records"][0]["record_id"] = replacement_id
        receipt_body = {
            key: value
            for key, value in receipt.items()
            if key not in {"schema_id", "receipt_id"}
        }
        mismatched["declassification_receipt"] = receipt_with_digest(
            "artifact-memory/declassification-receipt/v2",
            "declassification-receipt://",
            receipt_body,
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "bundle"
            with self.assertRaisesRegex(ValidationFailure, "admitted record set"):
                write_import_bundle(mismatched, output)
            self.assertFalse(output.exists())

    def test_import_bundle_rejects_records_without_adapter_type_labels(self):
        task = json.loads((FIXTURE / "task-export.json").read_text(encoding="utf-8"))
        policy = json.loads((FIXTURE / "import-policy.json").read_text(encoding="utf-8"))
        result = import_task_export(task, policy)
        for labels in (None, ["codex-history-derivative"]):
            with self.subTest(labels=labels), tempfile.TemporaryDirectory() as temporary:
                changed = deepcopy(result)
                if labels is None:
                    changed["records"][0]["meaning"].pop("labels")
                else:
                    changed["records"][0]["meaning"]["labels"] = labels
                output = Path(temporary) / "bundle"
                with self.assertRaisesRegex(ValidationFailure, "record type label"):
                    write_import_bundle(changed, output)
                self.assertFalse(output.exists())

    def test_import_bundle_rejects_adapter_type_label_mismatch(self):
        task = json.loads((FIXTURE / "task-export.json").read_text(encoding="utf-8"))
        policy = json.loads((FIXTURE / "import-policy.json").read_text(encoding="utf-8"))
        result = import_task_export(task, policy)
        changed = deepcopy(result)
        changed["records"][0]["meaning"]["labels"][1] = "research"
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "bundle"
            with self.assertRaisesRegex(ValidationFailure, "canonical record type"):
                write_import_bundle(changed, output)
            self.assertFalse(output.exists())

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
