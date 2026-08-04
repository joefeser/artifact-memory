import ast
import hashlib
import json
import subprocess
import unittest
from copy import deepcopy
from pathlib import Path

from artifact_memory.independent_exchange_conformance import (
    render_independent_exchange_conformance,
    run_independent_exchange_conformance,
)
from artifact_memory.conformance_helpers import SyntheticReplayLedger
from artifact_memory.exchange import admit_v2, make_envelope_v2
from artifact_memory.independent_reader import admit_bundle_v2
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import ValidationFailure, validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "exchange" / "independent-v1"


class IndependentExchangeConformanceTests(unittest.TestCase):
    def test_checked_machine_and_human_receipts_replay(self):
        receipt = run_independent_exchange_conformance(FIXTURE)
        expected = json.loads(
            (FIXTURE / "expected-receipt.json").read_text(encoding="utf-8")
        )
        self.assertEqual(receipt, expected)
        self.assertEqual(
            render_independent_exchange_conformance(receipt),
            (FIXTURE / "receipt.md").read_text(encoding="utf-8"),
        )
        self.assertTrue(
            all(case["receipts_compatible"] for case in receipt["cases"].values())
        )

    def test_independent_receiver_has_no_reference_runtime_imports(self):
        source = (ROOT / "artifact_memory" / "independent_reader.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        relative_imports = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.level
        ]
        self.assertEqual(relative_imports, [])

    def test_receipt_schema_binds_compatibility_and_outcomes(self):
        receipt = run_independent_exchange_conformance(FIXTURE)
        schema = load_schema(
            "core", "independent-exchange-conformance-receipt.v1.schema.json"
        )
        incompatible = deepcopy(receipt)
        incompatible["cases"]["unknown_optional"]["receipts_compatible"] = False
        with self.assertRaises(ValidationFailure):
            validate(incompatible, schema)
        wrong_outcome = deepcopy(receipt)
        wrong_outcome["cases"]["unknown_required"]["observed_outcome"] = "admitted"
        with self.assertRaises(ValidationFailure):
            validate(wrong_outcome, schema)

    def test_independent_receiver_rejects_credential_shaped_values_without_echo(self):
        synthetic_value = "github" + "_pat_" + "A" * 24
        embedded_value = "synthetic log prefix " + synthetic_value + " suffix"
        envelope = make_envelope_v2(
            "system://synthetic-independent-receiver",
            "independent-protected-value",
            "2099-01-01T00:00:00Z",
            [],
            ["artifact://synthetic/independent-exchange-evidence"],
            extensions={
                "https://synthetic.example/extensions/protected": {
                    "version": "v1",
                    "required": False,
                    "value": {"opaque": embedded_value},
                }
            },
        )
        receipt = admit_bundle_v2(
            json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode(),
            expected_audience_ref="system://synthetic-independent-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(receipt["outcome"], "rejected")
        self.assertEqual(
            receipt["diagnostics"][0]["code"], "bearer-material-prohibited"
        )
        self.assertNotIn(synthetic_value, json.dumps(receipt))
        reference = admit_v2(
            envelope,
            SyntheticReplayLedger(),
            expected_audience_ref="system://synthetic-independent-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(receipt, reference)

    def test_reference_and_independent_receivers_reject_underscore_secret_values(self):
        for separator in ("_", "-"):
            synthetic_value = "sk" + separator + "live_" + "S" * 24
            embedded_value = "synthetic prefix " + synthetic_value + " suffix"
            extension = {
                "https://synthetic.example/extensions/protected-value": {
                    "version": "v1",
                    "required": False,
                    "value": {"opaque": embedded_value},
                }
            }
            envelope = make_envelope_v2(
                "system://synthetic-independent-receiver",
                "independent-protected-secret-value-" + ("underscore" if separator == "_" else "hyphen"),
                "2099-01-01T00:00:00Z",
                [],
                ["artifact://synthetic/independent-exchange-evidence"],
                extensions=extension,
            )
            reference = admit_v2(
                envelope,
                SyntheticReplayLedger(),
                expected_audience_ref="system://synthetic-independent-receiver",
                now="2026-08-03T00:00:00Z",
            )
            independent = admit_bundle_v2(
                json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode(),
                expected_audience_ref="system://synthetic-independent-receiver",
                now="2026-08-03T00:00:00Z",
            )
            self.assertEqual(independent, reference)
            self.assertEqual(independent["outcome"], "rejected")
            self.assertNotIn(synthetic_value, json.dumps(independent))

    def test_noncanonical_envelope_returns_fail_closed_receipt(self):
        envelope = make_envelope_v2(
            "system://synthetic-independent-receiver",
            "independent-noncanonical-envelope",
            "2099-01-01T00:00:00Z",
            [],
            ["artifact://synthetic/independent-exchange-evidence"],
        )
        envelope["extensions"] = {
            "https://synthetic.example/extensions/noncanonical": {
                "version": "v1",
                "required": False,
                "value": {"fractional": 1.5},
            }
        }
        receipt = admit_bundle_v2(
            json.dumps(envelope).encode(),
            expected_audience_ref="system://synthetic-independent-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(receipt["outcome"], "rejected")
        self.assertEqual(receipt["envelope_ref"], "exchange://" + "0" * 64)
        self.assertEqual(receipt["diagnostics"][0]["code"], "invalid-envelope")

    def test_malformed_unsupported_schema_is_rejected_as_invalid(self):
        envelope = make_envelope_v2(
            "system://synthetic-independent-receiver",
            "independent-malformed-unsupported",
            "2099-01-01T00:00:00Z",
            [],
            ["artifact://synthetic/independent-exchange-evidence"],
        )
        envelope["schema_id"] = "artifact-memory/exchange-envelope/future"
        envelope["handling"] = {"sensitivity": "public"}
        body = {key: value for key, value in envelope.items() if key != "envelope_id"}
        envelope["envelope_id"] = "exchange://" + hashlib.sha256(
            json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        reference = admit_v2(
            envelope,
            SyntheticReplayLedger(),
            expected_audience_ref="system://synthetic-independent-receiver",
            now="2026-08-03T00:00:00Z",
        )
        independent = admit_bundle_v2(
            json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode(),
            expected_audience_ref="system://synthetic-independent-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(independent, reference)
        self.assertEqual(independent["outcome"], "rejected")
        self.assertEqual(independent["diagnostics"][0]["code"], "invalid-envelope")

    def test_extensions_precede_expiry_and_remain_in_receipt(self):
        extension = {
            "https://synthetic.example/extensions/expired-optional": {
                "version": "v1",
                "required": False,
                "value": {"opaque": "preserved"},
            }
        }
        envelope = make_envelope_v2(
            "system://synthetic-independent-receiver",
            "independent-expired-extension",
            "2020-01-01T00:00:00Z",
            [],
            ["artifact://synthetic/independent-exchange-evidence"],
            extensions=extension,
        )
        reference = admit_v2(
            envelope,
            SyntheticReplayLedger(),
            expected_audience_ref="system://synthetic-independent-receiver",
            now="2026-08-03T00:00:00Z",
        )
        independent = admit_bundle_v2(
            json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode(),
            expected_audience_ref="system://synthetic-independent-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(independent, reference)
        self.assertEqual(independent["extensions"], extension)

    def test_required_record_extension_keeps_reference_diagnostic(self):
        vectors = json.loads((FIXTURE / "vectors.json").read_text(encoding="utf-8"))
        record = deepcopy(vectors["record"])
        record["extensions"] = {
            "https://synthetic.example/extensions/record-required": {
                "version": "v1",
                "required": True,
                "value": {"behavior": "unsupported"},
            }
        }
        revision = "sha-256:" + hashlib.sha256(
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        envelope = make_envelope_v2(
            vectors["audience_ref"],
            "independent-record-required",
            vectors["expires_at"],
            [{"record_id": record["record_id"], "revision_digest": revision}],
            [vectors["artifact_ref"]],
            record_bundle=[record],
        )
        reference = admit_v2(
            envelope,
            SyntheticReplayLedger(),
            expected_audience_ref=vectors["audience_ref"],
            now=vectors["evaluation_time"],
        )
        independent = admit_bundle_v2(
            json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode(),
            expected_audience_ref=vectors["audience_ref"],
            now=vectors["evaluation_time"],
        )
        self.assertEqual(independent, reference)
        self.assertIn("required-extension-unsupported", independent["diagnostics"][0]["message"])

    def test_incomplete_embedded_bundle_is_quarantined(self):
        vectors = json.loads((FIXTURE / "vectors.json").read_text(encoding="utf-8"))
        first = vectors["record"]
        second = deepcopy(first)
        second["record_id"] = "record://synthetic/independent-exchange-unresolved"

        def revision(record):
            return {
                "record_id": record["record_id"],
                "revision_digest": "sha-256:"
                + hashlib.sha256(
                    json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
            }

        envelope = make_envelope_v2(
            vectors["audience_ref"],
            "independent-incomplete-bundle",
            vectors["expires_at"],
            [revision(first), revision(second)],
            [vectors["artifact_ref"]],
            record_bundle=[first],
        )
        receipt = admit_bundle_v2(
            json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode(),
            expected_audience_ref=vectors["audience_ref"],
            now=vectors["evaluation_time"],
        )
        self.assertEqual(receipt["outcome"], "quarantined")
        self.assertEqual(receipt["accepted_record_ids"], [])
        self.assertEqual(receipt["diagnostics"][0]["code"], "incomplete-bundle")

    def test_independent_receiver_fails_closed_on_unhashable_metadata(self):
        malformed_handling = make_envelope_v2(
            "system://synthetic-independent-receiver",
            "independent-malformed-handling",
            "2099-01-01T00:00:00Z",
            [],
            ["artifact://synthetic/independent-exchange-evidence"],
            sensitivity=[],  # type: ignore[arg-type]
        )
        handling_receipt = admit_bundle_v2(
            json.dumps(malformed_handling, sort_keys=True, separators=(",", ":")).encode(),
            expected_audience_ref="system://synthetic-independent-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(handling_receipt["outcome"], "rejected")

        vectors = json.loads((FIXTURE / "vectors.json").read_text(encoding="utf-8"))
        malformed_record = deepcopy(vectors["record"])
        malformed_record["record_type"] = []
        revision = "sha-256:" + hashlib.sha256(
            json.dumps(
                malformed_record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        malformed_bundle = make_envelope_v2(
            vectors["audience_ref"],
            "independent-malformed-record",
            vectors["expires_at"],
            [{"record_id": malformed_record["record_id"], "revision_digest": revision}],
            [vectors["artifact_ref"]],
            record_bundle=[malformed_record],
        )
        record_receipt = admit_bundle_v2(
            json.dumps(malformed_bundle, sort_keys=True, separators=(",", ":")).encode(),
            expected_audience_ref=vectors["audience_ref"],
            now=vectors["evaluation_time"],
        )
        self.assertEqual(record_receipt["outcome"], "quarantined")

    def test_vector_schema_binds_optional_and_required_declarations(self):
        vectors = json.loads((FIXTURE / "vectors.json").read_text(encoding="utf-8"))
        schema = load_schema("core", "independent-exchange-vectors.v1.schema.json")
        invalid = deepcopy(vectors)
        invalid["optional_extension"]["declaration"]["required"] = True
        with self.assertRaises(ValidationFailure):
            validate(invalid, schema)
        invalid_record = deepcopy(vectors)
        invalid_record["record"]["unexpected"] = "schema must reject this"
        with self.assertRaises(ValidationFailure):
            validate(invalid_record, schema)

    def test_checked_cli(self):
        completed = subprocess.run(
            ["python3", "scripts/run_independent_exchange_conformance.py", "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
