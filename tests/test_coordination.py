import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from artifact_memory.canonical import canonical_bytes
from artifact_memory.coordination import (
    ACCESS_LABEL_SCHEMA_ID,
    FRESHNESS_EXTENSION_ID,
    TASK_PACKET_SCHEMA_ID,
    WORK_RECEIPT_SCHEMA_ID,
    revision_digest,
    validate_coordination_records,
)
from artifact_memory.schema_resources import core_schemas
from artifact_memory.validator import ValidationFailure, load_json, validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "coordination"


def fixture(name: str) -> dict:
    return load_json(FIXTURES / name)


def synthetic_work_receipt() -> dict:
    return {
        "schema_id": WORK_RECEIPT_SCHEMA_ID,
        "record_id": "record://coordination/33333333-3333-4333-8333-333333333333/receipt/rcpt-01J00000000000000000000001",
        "originId": "33333333-3333-4333-8333-333333333333",
        "receiptId": "rcpt-01J00000000000000000000001",
        "taskRef": {
            "record_id": "record://coordination/33333333-3333-4333-8333-333333333333/task/task_01J00000000000000000000000",
            "revision_digest": revision_digest(fixture("task-claimed.json")),
        },
        "writer": "agent-session-synthetic-1",
        "machine": "synthetic-client-a",
        "projectId": "11111111-1111-4111-8111-111111111111",
        "projectName": "sample-service",
        "headSha": "a" * 40,
        "accessLabelRef": {
            "record_id": "record://coordination/33333333-3333-4333-8333-333333333333/label/label-scoped-client",
            "revision_digest": revision_digest(fixture("access-label.json")),
        },
        "evidence": [
            {
                "command": "python3 -m unittest tests.test_synthetic_adapter",
                "exitCode": 0,
                "counts": {"passed": 1, "failed": 0, "skipped": 0},
                "artifacts": [
                    {
                        "artifactId": "artifact://synthetic/review-receipt",
                        "contentDigest": "sha-256:" + "0" * 64,
                        "location": {
                            "endpoint_ref": "endpoint://synthetic/review-store",
                            "relative_path": "reviews/42.json",
                        },
                        "mediaType": "application/json",
                        "semanticType": "code-review-receipt",
                    }
                ],
            }
        ],
        "consumedTokensNote": None,
        "recordedAt": "2026-09-25T19:20:00Z",
        "authority_boundary": "informational only; authority requires independently authenticated WITS enforcement",
    }


def valid_records() -> list[dict]:
    return [
        fixture("access-label.json"),
        fixture("task-open.json"),
        fixture("task-claimed.json"),
        fixture("same-human-id-other-origin.json"),
        synthetic_work_receipt(),
    ]


class CoordinationRecordTests(unittest.TestCase):
    def assert_rejected(self, records: list[dict], code: str) -> ValidationFailure:
        with self.assertRaises(ValidationFailure) as raised:
            validate_coordination_records(records)
        self.assertEqual(raised.exception.code, code)
        return raised.exception

    def test_public_fixture_set_validates_and_reports_no_hub_admission(self):
        result = validate_coordination_records(valid_records())
        self.assertTrue(result["valid"])
        self.assertEqual(result["record_count"], 5)
        self.assertFalse(result["hub_admission_verified"])
        self.assertEqual(
            result["type_counts"],
            {
                ACCESS_LABEL_SCHEMA_ID: 1,
                TASK_PACKET_SCHEMA_ID: 3,
                WORK_RECEIPT_SCHEMA_ID: 1,
            },
        )

    def test_cli_acceptance_command_validates_globbed_fixture_set(self):
        paths = sorted(FIXTURES.glob("*.json"))
        completed = subprocess.run(
            [sys.executable, "-m", "artifact_memory", "records", "validate", *map(str, paths), "--json"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        result = json.loads(completed.stdout)
        self.assertEqual(result["outcome"], "accepted")
        self.assertEqual(result["record_count"], len(paths))
        self.assertTrue(result["extensions_preserved_canonically"])

    def test_cli_validates_ephemeral_vault_only_work_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            receipt_path = Path(temporary) / "work-receipt.json"
            receipt_path.write_text(json.dumps(synthetic_work_receipt()), encoding="utf-8")
            paths = sorted(FIXTURES.glob("*.json")) + [receipt_path]
            completed = subprocess.run(
                [sys.executable, "-m", "artifact_memory", "records", "validate", *map(str, paths), "--json"],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        result = json.loads(completed.stdout)
        self.assertEqual(result["type_counts"][WORK_RECEIPT_SCHEMA_ID], 1)

    def test_every_required_field_omission_is_rejected_typed(self):
        schemas = core_schemas()
        examples = {
            ACCESS_LABEL_SCHEMA_ID: fixture("access-label.json"),
            TASK_PACKET_SCHEMA_ID: fixture("task-open.json"),
            WORK_RECEIPT_SCHEMA_ID: synthetic_work_receipt(),
        }
        for schema_id, record in examples.items():
            for field in schemas[schema_id]["required"]:
                with self.subTest(schema_id=schema_id, field=field):
                    missing = copy.deepcopy(record)
                    del missing[field]
                    with self.assertRaises(ValidationFailure) as raised:
                        validate(missing, schemas[schema_id])
                    self.assertIn(
                        raised.exception.code,
                        {"required-field-missing", "constraint-failed", "type-mismatch"},
                    )

    def test_empty_work_evidence_is_rejected_typed(self):
        records = valid_records()
        records[-1]["evidence"] = []
        self.assert_rejected(records, "constraint-failed")

    def test_same_human_task_id_from_distinct_origins_does_not_collide(self):
        records = valid_records()
        tasks = [record for record in records if record["schema_id"] == TASK_PACKET_SCHEMA_ID]
        matching = [record for record in tasks if record["taskId"] == tasks[0]["taskId"]]
        self.assertGreaterEqual(len(matching), 2)
        self.assertEqual(len({record["originId"] for record in matching}), 2)
        self.assertEqual(len({record["record_id"] for record in matching}), 2)
        validate_coordination_records(records)

    def test_record_id_must_match_origin_and_human_identifier(self):
        records = valid_records()
        records[1]["originId"] = "55555555-5555-4555-8555-555555555555"
        self.assert_rejected(records, "coordination-record-id-mismatch")

    def test_stale_and_forked_task_references_are_rejected(self):
        stale = valid_records()
        stale[-1]["taskRef"]["revision_digest"] = revision_digest(stale[1])
        self.assert_rejected(stale, "work-receipt-task-ref-stale")

        forked = valid_records()
        sibling = copy.deepcopy(forked[2])
        sibling["claims"][0]["claimId"] = "claim_01J00000000000000000000003"
        sibling["claims"][0]["claimedAt"] = "2026-09-25T19:06:00Z"
        forked.insert(3, sibling)
        self.assert_rejected(forked, "coordination-chain-forked")

    def test_raw_provider_or_absolute_artifact_locations_are_rejected(self):
        for bad_path in (
            "https://storage.invalid/private/result.json",
            "/private/result.json",
            "C:\\private\\result.json",
            "../private/result.json",
            "reviews/result.json?mode=synthetic",
            "reviews/result.json#fragment",
        ):
            with self.subTest(path=bad_path):
                records = valid_records()
                records[-1]["evidence"][0]["artifacts"][0]["location"]["relative_path"] = bad_path
                self.assert_rejected(records, "artifact-location-nonportable")

    def test_artifact_evidence_uses_canonical_logical_reference_grammars(self):
        accepted = (
            ("artifactId", "artifact://synthetic/review-receipt"),
            ("endpoint_ref", "endpoint://synthetic"),
            ("endpoint_ref", "endpoint://synthetic/review-store"),
        )
        for field, value in accepted:
            with self.subTest(outcome="accepted", field=field, value=value):
                records = valid_records()
                artifact = records[-1]["evidence"][0]["artifacts"][0]
                if field == "artifactId":
                    artifact[field] = value
                else:
                    artifact["location"][field] = value
                validate_coordination_records(records)

        rejected = (
            ("artifactId", "artifact://../machine/path"),
            ("artifactId", "artifact://synthetic//receipt"),
            ("artifactId", "artifact://synthetic"),
            ("endpoint_ref", "endpoint://synthetic//store"),
            ("endpoint_ref", "endpoint://synthetic/store/extra"),
        )
        for field, value in rejected:
            with self.subTest(outcome="rejected", field=field, value=value):
                records = valid_records()
                artifact = records[-1]["evidence"][0]["artifacts"][0]
                if field == "artifactId":
                    artifact[field] = value
                else:
                    artifact["location"][field] = value
                self.assert_rejected(records, "constraint-failed")

    def test_unknown_top_level_and_malformed_typed_entries_are_rejected(self):
        records = valid_records()
        records[-1]["narrativeEvidence"] = "looks good"
        self.assert_rejected(records, "unknown-field")

        records = valid_records()
        records[2]["claims"][0]["authority"] = "execute"
        self.assert_rejected(records, "unknown-field")

        records = valid_records()
        records[-1]["evidence"][0]["artifacts"][0]["providerUrl"] = "https://storage.invalid/result.json"
        self.assert_rejected(records, "unknown-field")

    def test_claimed_successor_must_bind_its_exact_open_predecessor(self):
        records = valid_records()
        records[2]["claims"][0]["taskRef"]["revision_digest"] = "sha-256:" + "f" * 64
        self.assert_rejected(records, "claim-task-ref-mismatch")

        records = valid_records()
        records[2]["title"] = "Changed while claiming"
        self.assert_rejected(records, "coordination-transition-fields-changed")

        records = valid_records()
        records[2]["claims"][0]["principalId"] = "agent-session-synthetic-other"
        self.assert_rejected(records, "claim-principal-mismatch")

    def test_access_label_duplicate_and_overlapping_read_sets_are_rejected(self):
        duplicate = load_json(FIXTURES / "invalid" / "access-label-duplicate-read.json")
        overlap = load_json(FIXTURES / "invalid" / "access-label-overlap.json")
        self.assert_rejected([duplicate], "constraint-failed")
        self.assert_rejected([overlap], "access-label-read-overlap")

    def test_negative_claim_fixtures_reject_unknown_shape_and_wrong_binding(self):
        malformed = valid_records()
        malformed[2] = load_json(FIXTURES / "invalid" / "malformed-claim.json")
        self.assert_rejected(malformed, "unknown-field")

        mismatched = valid_records()
        mismatched[2] = load_json(FIXTURES / "invalid" / "predecessor-mismatch.json")
        self.assert_rejected(mismatched, "claim-task-ref-mismatch")

    def test_work_receipt_exact_task_label_project_and_writer_bindings(self):
        mutations = (
            ("projectId", "22222222-2222-4222-8222-222222222222", "work-receipt-project-mismatch"),
            ("writer", "agent-session-synthetic-other", "work-receipt-writer-mismatch"),
        )
        for field, value, code in mutations:
            with self.subTest(field=field):
                records = valid_records()
                records[-1][field] = value
                self.assert_rejected(records, code)

        records = valid_records()
        records[-1]["accessLabelRef"]["revision_digest"] = "sha-256:" + "f" * 64
        self.assert_rejected(records, "work-receipt-label-mismatch")

    def test_project_display_names_are_provenance_not_join_keys(self):
        records = valid_records()
        records[1]["projectName"] = "renamed-task-display"
        records[2]["projectName"] = "renamed-task-display"
        open_ref = {
            "record_id": records[1]["record_id"],
            "revision_digest": revision_digest(records[1]),
        }
        records[2]["predecessor"] = copy.deepcopy(open_ref)
        records[2]["claims"][0]["taskRef"] = copy.deepcopy(open_ref)
        records[-1]["taskRef"]["revision_digest"] = revision_digest(records[2])
        records[-1]["projectName"] = "historical-receipt-display"
        validate_coordination_records(records)

    def test_canonicalization_failure_is_typed_through_cli(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = synthetic_work_receipt()
            receipt["evidence"][0]["counts"]["passed"] = 9_007_199_254_740_992
            receipt_path = root / "work-receipt.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            paths = sorted(FIXTURES.glob("*.json")) + [receipt_path]
            completed = subprocess.run(
                [sys.executable, "-m", "artifact_memory", "records", "validate", *map(str, paths), "--json"],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(json.loads(completed.stdout)["diagnostics"][0]["code"], "canonicalization-failed")
        self.assertNotIn("Traceback", completed.stderr)

    def test_claim_ids_are_unique_within_an_origin(self):
        records = valid_records()
        open_task = copy.deepcopy(records[1])
        claimed_task = copy.deepcopy(records[2])
        replacement_task_id = "task_01J00000000000000000000004"
        replacement_record_id = (
            "record://coordination/33333333-3333-4333-8333-333333333333/task/"
            + replacement_task_id
        )
        for task in (open_task, claimed_task):
            task["taskId"] = replacement_task_id
            task["record_id"] = replacement_record_id
            task["title"] = "Synthetic second claim chain"
        open_ref = {
            "record_id": replacement_record_id,
            "revision_digest": revision_digest(open_task),
        }
        claimed_task["predecessor"] = copy.deepcopy(open_ref)
        claimed_task["claims"][0]["taskRef"] = copy.deepcopy(open_ref)
        records.extend((open_task, claimed_task))
        self.assert_rejected(records, "coordination-claim-id-duplicate")

    def test_ulid_leading_character_range_is_enforced(self):
        schemas = core_schemas()
        cases = []
        task = fixture("task-open.json")
        task["taskId"] = "task_Z1J00000000000000000000000"
        task["record_id"] = (
            "record://coordination/33333333-3333-4333-8333-333333333333/task/"
            + task["taskId"]
        )
        cases.append((task, schemas[TASK_PACKET_SCHEMA_ID]))
        claim = fixture("task-claimed.json")
        claim["claims"][0]["claimId"] = "claim_Z1J00000000000000000000000"
        cases.append((claim, schemas[TASK_PACKET_SCHEMA_ID]))
        receipt = synthetic_work_receipt()
        receipt["receiptId"] = "rcpt-Z1J00000000000000000000000"
        receipt["record_id"] = (
            "record://coordination/33333333-3333-4333-8333-333333333333/receipt/"
            + receipt["receiptId"]
        )
        cases.append((receipt, schemas[WORK_RECEIPT_SCHEMA_ID]))
        for record, schema in cases:
            with self.subTest(schema_id=record["schema_id"]):
                with self.assertRaises(ValidationFailure):
                    validate(record, schema)

    def test_freshness_and_unknown_optional_extensions_round_trip_canonically(self):
        records = valid_records()
        before = canonical_bytes(records[1]["extensions"])
        result = validate_coordination_records(records)
        self.assertTrue(result["extensions_preserved_canonically"])
        self.assertEqual(canonical_bytes(records[1]["extensions"]), before)
        self.assertEqual(
            records[1]["extensions"][FRESHNESS_EXTENSION_ID]["value"]["trueAsOfCommit"],
            "a" * 40,
        )

        records = valid_records()
        opaque = {
            "version": "v1",
            "required": False,
            "value": {"opaque": ["synthetic", 1, True]},
        }
        records[1]["extensions"]["https://synthetic.example/extensions/opaque"] = opaque
        records[2]["extensions"]["https://synthetic.example/extensions/opaque"] = copy.deepcopy(opaque)
        open_ref = {
            "record_id": records[1]["record_id"],
            "revision_digest": revision_digest(records[1]),
        }
        records[2]["predecessor"] = copy.deepcopy(open_ref)
        records[2]["claims"][0]["taskRef"] = copy.deepcopy(open_ref)
        records[-1]["taskRef"]["revision_digest"] = revision_digest(records[2])
        validate_coordination_records(records)

    def test_required_or_malformed_freshness_extensions_fail_closed(self):
        records = valid_records()
        records[1]["extensions"]["https://synthetic.example/extensions/required"] = {
            "version": "v1",
            "required": True,
            "value": {},
        }
        self.assert_rejected(records, "required-extension-unsupported")

        records = valid_records()
        records[1]["extensions"][FRESHNESS_EXTENSION_ID]["value"]["extra"] = True
        self.assert_rejected(records, "freshness-extension-invalid")

    def test_cli_rejection_is_typed_and_does_not_claim_admission(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.json"
            record = fixture("access-label.json")
            record["mayNot"]["readProjects"] = [record["may"]["readProjects"][0]]
            path.write_text(json.dumps(record), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, "-m", "artifact_memory", "records", "validate", str(path), "--json"],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
        self.assertEqual(completed.returncode, 2)
        result = json.loads(completed.stdout)
        self.assertEqual(result["outcome"], "rejected")
        self.assertEqual(result["diagnostics"][0]["code"], "access-label-read-overlap")
        self.assertNotIn("hub_admission_verified", result)


if __name__ == "__main__":
    unittest.main()
