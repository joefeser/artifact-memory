import ast
import json
import hashlib
import threading
import unittest
from pathlib import Path

from artifact_memory.exchange import (
    AUTHORITY_BOUNDARY,
    admit,
    admit_v2 as _runtime_admit_v2,
    make_envelope,
    make_envelope_v2,
)
from artifact_memory.independent_reader import ReaderFailure, read_bundle
from artifact_memory.validator import ValidationFailure, validate


ROOT = Path(__file__).resolve().parents[1]


class SyntheticReplayLedger:
    """Explicit process-local ledger for synthetic tests; it makes no durability claim."""

    def __init__(self):
        self._lock = threading.Lock()
        self._seen: set[str] = set()

    def claim(self, envelope_ref):
        with self._lock:
            if envelope_ref in self._seen:
                return False
            self._seen.add(envelope_ref)
            return True


def admit_v2(envelope, replay_ledger=None, **kwargs):
    return _runtime_admit_v2(
        envelope,
        replay_ledger if replay_ledger is not None else SyntheticReplayLedger(),
        **kwargs,
    )


def canonical_record(**overrides):
    record = {
        "schema_id": "artifact-memory/knowledge-record/v1",
        "record_id": "record://synthetic/reader-0001",
        "record_type": "note",
        "lifecycle": "accepted",
        "meaning": {"summary": "Synthetic independent-reader record."},
        "artifact_refs": [],
        "provenance": [{"kind": "author", "source_ref": "actor://synthetic/reader"}],
        "extensions": {},
    }
    record.update(overrides)
    return record


def revision_ref(record):
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"record_id": record["record_id"], "revision_digest": "sha-256:" + hashlib.sha256(encoded).hexdigest()}


class ExchangeTests(unittest.TestCase):
    def test_v2_binds_receiver_audience_and_fails_closed_on_record_sensitivity(self):
        private_record = canonical_record(
            record_id="record://synthetic/exchange-private",
            sensitivity="private",
        )
        public_handling = make_envelope_v2(
            "system://intended-receiver",
            "v2-audience-and-handling",
            "2099-01-01T00:00:00Z",
            [revision_ref(private_record)],
            [],
            sensitivity="public",
            record_bundle=[private_record],
        )
        wrong_audience = admit_v2(
            public_handling,
            expected_audience_ref="system://different-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(wrong_audience["outcome"], "rejected")
        self.assertEqual(wrong_audience["diagnostics"][0]["code"], "audience-mismatch")
        handling_mismatch = admit_v2(
            public_handling,
            expected_audience_ref="system://intended-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(handling_mismatch["outcome"], "quarantined")
        self.assertEqual(
            handling_mismatch["diagnostics"][0]["code"],
            "handling-sensitivity-mismatch",
        )
        private_handling = make_envelope_v2(
            "system://intended-receiver",
            "v2-private-handling",
            "2099-01-01T00:00:00Z",
            [revision_ref(private_record)],
            [],
            sensitivity="private",
            record_bundle=[private_record],
        )
        admitted = admit_v2(
            private_handling,
            expected_audience_ref="system://intended-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(admitted["outcome"], "admitted")

        legacy_unspecified = canonical_record(
            record_id="record://synthetic/exchange-unspecified-sensitivity"
        )
        legacy_envelope = make_envelope_v2(
            "system://intended-receiver",
            "v2-unspecified-sensitivity",
            "2099-01-01T00:00:00Z",
            [revision_ref(legacy_unspecified)],
            [],
            sensitivity="private",
            record_bundle=[legacy_unspecified],
        )
        fail_closed = admit_v2(
            legacy_envelope,
            expected_audience_ref="system://intended-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(fail_closed["outcome"], "quarantined")

    def test_v2_bundle_manifest_partial_resolution_and_replay_are_explicit(self):
        first = canonical_record(
            record_id="record://synthetic/exchange-first",
            sensitivity="public",
        )
        second = canonical_record(
            record_id="record://synthetic/exchange-second",
            sensitivity="public",
        )
        envelope = make_envelope_v2(
            "system://synthetic-receiver",
            "v2-partial",
            "2099-01-01T00:00:00Z",
            [revision_ref(first), revision_ref(second)],
            ["artifact://synthetic/exchange-payload"],
            record_bundle=[first],
        )
        envelope_schema = json.loads(
            (ROOT / "artifact_memory/schemas/core/exchange-envelope.v2.schema.json").read_text(
                encoding="utf-8"
            )
        )
        receipt_schema = json.loads(
            (ROOT / "artifact_memory/schemas/core/admission-receipt.v2.schema.json").read_text(
                encoding="utf-8"
            )
        )
        validate(envelope, envelope_schema)
        ledger = SyntheticReplayLedger()
        partial = admit_v2(
            envelope,
            ledger,
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
        )
        validate(partial, receipt_schema)
        self.assertEqual(partial["outcome"], "partially-resolved")
        self.assertEqual(partial["accepted_record_ids"], [first["record_id"]])
        self.assertEqual(partial["unresolved_record_ids"], [second["record_id"]])
        self.assertEqual(partial["artifact_retrieval"], "not-attempted/separately-authorized")
        replay = admit_v2(
            envelope,
            ledger,
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
        )
        repeated_replay = admit_v2(
            envelope,
            ledger,
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(replay, repeated_replay)
        self.assertEqual(replay["outcome"], "duplicate")

    def test_v2_identity_mismatch_cannot_poison_replay_ledger(self):
        envelope = make_envelope_v2(
            "system://synthetic-receiver",
            "v2-identity-mismatch",
            "2099-01-01T00:00:00Z",
            [],
            ["artifact://synthetic/reference"],
        )
        malformed = {**envelope, "envelope_id": "exchange://" + "f" * 64}
        ledger = SyntheticReplayLedger()
        rejected = admit_v2(
            malformed,
            ledger,
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
        )
        admitted = admit_v2(
            envelope,
            ledger,
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(rejected["diagnostics"][0]["code"], "envelope-id-mismatch")
        self.assertEqual(admitted["outcome"], "admitted")

    def test_v2_all_declared_admission_outcomes_are_reachable(self):
        record = canonical_record(
            record_id="record://synthetic/exchange-outcomes",
            sensitivity="public",
        )
        base = make_envelope_v2(
            "system://synthetic-receiver",
            "v2-outcomes",
            "2099-01-01T00:00:00Z",
            [revision_ref(record)],
            [],
            record_bundle=[record],
        )
        admitted = admit_v2(
            base,
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
        )
        expired = make_envelope_v2(
            "system://synthetic-receiver",
            "v2-expired",
            "2020-01-01T00:00:00Z",
            [],
            ["artifact://synthetic/reference"],
        )
        rejected = admit_v2(
            expired,
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
        )
        unresolved = make_envelope_v2(
            "system://synthetic-receiver",
            "v2-unresolved",
            "2099-01-01T00:00:00Z",
            [revision_ref(record)],
            [],
        )
        quarantined = admit_v2(
            unresolved,
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
        )
        unsupported = admit_v2(
            base,
            expected_audience_ref="system://synthetic-receiver",
            supported_schema=False,
        )
        ledger = SyntheticReplayLedger()
        self.assertTrue(ledger.claim(base["envelope_id"]))
        duplicate = admit_v2(
            base,
            ledger,
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
        )
        second = canonical_record(
            record_id="record://synthetic/exchange-unresolved",
            sensitivity="public",
        )
        partial_envelope = make_envelope_v2(
            "system://synthetic-receiver",
            "v2-partially-resolved",
            "2099-01-01T00:00:00Z",
            [revision_ref(record), revision_ref(second)],
            [],
            record_bundle=[record],
        )
        partial = admit_v2(
            partial_envelope,
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(
            {item["outcome"] for item in (admitted, rejected, quarantined, unsupported, duplicate, partial)},
            {"admitted", "rejected", "quarantined", "unsupported", "duplicate", "partially-resolved"},
        )

    def test_v2_rejects_contradictory_bundle_and_bearer_material(self):
        record = canonical_record(
            record_id="record://synthetic/exchange-contradiction",
            sensitivity="public",
        )
        reference = revision_ref(record)
        contradictory = make_envelope_v2(
            "system://synthetic-receiver",
            "v2-contradiction",
            "2099-01-01T00:00:00Z",
            [reference, {**reference, "revision_digest": "sha-256:" + "f" * 64}],
            [],
            record_bundle=[record],
        )
        receipt = admit_v2(
            contradictory,
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(receipt["outcome"], "quarantined")
        self.assertEqual(receipt["diagnostics"][0]["code"], "contradictory-bundle")
        protected = make_envelope_v2(
            "system://synthetic-receiver",
            "v2-protected",
            "2099-01-01T00:00:00Z",
            [],
            ["artifact://synthetic/reference"],
            extensions={"authorization": "Bearer synthetic-not-a-real-token"},
        )
        protected_ledger = SyntheticReplayLedger()
        rejected = admit_v2(
            protected,
            protected_ledger,
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(rejected["outcome"], "rejected")
        self.assertEqual(rejected["diagnostics"][0]["code"], "bearer-material-prohibited")
        self.assertNotIn("Bearer", json.dumps(rejected))
        replay = admit_v2(
            protected,
            protected_ledger,
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(replay["outcome"], "duplicate")
        self.assertNotIn("Bearer", json.dumps(replay))

    def test_v2_required_extensions_fail_closed_until_support_is_declared(self):
        identifier = "https://synthetic.example/required-exchange"
        record = canonical_record(
            record_id="record://synthetic/exchange-required-extension",
            sensitivity="public",
            extensions={identifier: {"version": "v1", "required": True, "value": {}}},
        )
        envelope = make_envelope_v2(
            "system://synthetic-receiver",
            "v2-required-extension",
            "2099-01-01T00:00:00Z",
            [revision_ref(record)],
            [],
            record_bundle=[record],
        )
        unsupported = admit_v2(
            envelope,
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(unsupported["outcome"], "quarantined")
        supported = admit_v2(
            envelope,
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
            supported_required_extensions={(identifier, "v1")},
        )
        self.assertEqual(supported["outcome"], "admitted")

    def test_v2_preserves_optional_envelope_extensions_unchanged(self):
        identifier = "https://synthetic.example/optional-exchange"
        declaration = {"version": "v1", "required": False, "value": {"opaque": True}}
        envelope = make_envelope_v2(
            "system://synthetic-receiver",
            "v2-optional-envelope-extension",
            "2099-01-01T00:00:00Z",
            [],
            ["artifact://synthetic/reference"],
            extensions={identifier: declaration},
        )
        receipt = admit_v2(
            envelope,
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(receipt["outcome"], "admitted")
        self.assertEqual(receipt["extensions"], {identifier: declaration})

        expired = make_envelope_v2(
            "system://synthetic-receiver",
            "v2-expired-optional-envelope-extension",
            "2020-01-01T00:00:00Z",
            [],
            ["artifact://synthetic/reference"],
            extensions={identifier: declaration},
        )
        expired_receipt = admit_v2(
            expired,
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(expired_receipt["outcome"], "rejected")
        self.assertEqual(expired_receipt["extensions"], {identifier: declaration})

        prose_declaration = {
            "version": "v1",
            "required": False,
            "value": {"note": "Bearer instruments are transferable"},
        }
        prose_envelope = make_envelope_v2(
            "system://synthetic-receiver",
            "v2-bearer-prose-extension",
            "2099-01-01T00:00:00Z",
            [],
            ["artifact://synthetic/reference"],
            extensions={identifier: prose_declaration},
        )
        prose_receipt = admit_v2(
            prose_envelope,
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(prose_receipt["outcome"], "admitted")
        self.assertEqual(prose_receipt["extensions"], {identifier: prose_declaration})

    def test_v2_does_not_interpret_opaque_optional_extension_keys(self):
        for key in ("api-key", "private_key", "cookie"):
            envelope = make_envelope_v2(
                "system://synthetic-receiver",
                f"v2-protected-{key.replace('_', '-').replace(' ', '-')}",
                "2099-01-01T00:00:00Z",
                [],
                ["artifact://synthetic/reference"],
                extensions={
                    "https://synthetic.example/protected": {
                        "version": "v1",
                        "required": False,
                        "value": {key: "synthetic-placeholder"},
                    }
                },
            )
            receipt = admit_v2(
                envelope,
                expected_audience_ref="system://synthetic-receiver",
                now="2026-08-03T00:00:00Z",
            )
            self.assertEqual(receipt["outcome"], "admitted")

    def test_v2_rejects_credential_shaped_values_without_echo(self):
        synthetic_value = "github" + "_pat_" + "A" * 24
        values = (
            "-----BEGIN RSA " + "PRIVATE" + " KEY-----\nsynthetic\n-----END RSA " + "PRIVATE" + " KEY-----",
            synthetic_value,
            "Author" + "ization: Bearer " + synthetic_value,
        )
        for index, value in enumerate(values):
            envelope = make_envelope_v2(
                "system://synthetic-receiver",
                f"v2-protected-value-{index}",
                "2099-01-01T00:00:00Z",
                [],
                ["artifact://synthetic/reference"],
                extensions={
                    "https://synthetic.example/protected": {
                        "version": "v1",
                        "required": False,
                        "value": {"payload": value},
                    }
                },
            )
            receipt = admit_v2(
                envelope,
                expected_audience_ref="system://synthetic-receiver",
                now="2026-08-03T00:00:00Z",
            )
            self.assertEqual(receipt["outcome"], "rejected")
            self.assertNotIn(value, json.dumps(receipt))

    def test_v2_requires_explicit_replay_ledger(self):
        envelope = make_envelope_v2(
            "system://synthetic-receiver",
            "v2-replay-ledger-required",
            "2099-01-01T00:00:00Z",
            [],
            ["artifact://synthetic/reference"],
        )
        unavailable = _runtime_admit_v2(
            envelope,
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(unavailable["outcome"], "quarantined")
        self.assertEqual(unavailable["diagnostics"][0]["code"], "replay-ledger-unavailable")

        admitted = _runtime_admit_v2(
            envelope,
            SyntheticReplayLedger(),
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(admitted["outcome"], "admitted")

    def test_v2_deduplicates_identical_revision_declarations(self):
        record = canonical_record(
            record_id="record://synthetic/exchange-identical-duplicate",
            sensitivity="public",
        )
        reference = revision_ref(record)
        envelope = make_envelope_v2(
            "system://synthetic-receiver",
            "v2-identical-duplicate",
            "2099-01-01T00:00:00Z",
            [reference, reference],
            [],
            record_bundle=[record],
        )
        receipt = admit_v2(
            envelope,
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(receipt["outcome"], "admitted")
        self.assertEqual(receipt["accepted_record_ids"], [record["record_id"]])

    def test_v2_quarantine_preserves_known_invalid_bundled_record_identity(self):
        malformed_record = canonical_record(
            record_id="record://synthetic/exchange-malformed-bundle",
            sensitivity="public",
        )
        malformed_record["meaning"] = []
        envelope = make_envelope_v2(
            "system://synthetic-receiver",
            "v2-malformed-known-record",
            "2099-01-01T00:00:00Z",
            [],
            [],
            record_bundle=[malformed_record],
        )
        receipt = admit_v2(
            envelope,
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(receipt["outcome"], "quarantined")
        self.assertEqual(receipt["unresolved_record_ids"], [malformed_record["record_id"]])
        self.assertEqual(receipt["diagnostics"][0]["code"], "bundled-record-invalid")

    def test_v2_quarantine_preserves_undeclared_bundled_record_identity(self):
        declared = canonical_record(
            record_id="record://synthetic/exchange-declared-bundle",
            sensitivity="public",
        )
        extra = canonical_record(
            record_id="record://synthetic/exchange-undeclared-bundle",
            sensitivity="public",
        )
        envelope = make_envelope_v2(
            "system://synthetic-receiver",
            "v2-undeclared-bundled-record",
            "2099-01-01T00:00:00Z",
            [revision_ref(declared)],
            [],
            record_bundle=[declared, extra],
        )
        receipt = admit_v2(
            envelope,
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(receipt["outcome"], "quarantined")
        self.assertEqual(
            receipt["unresolved_record_ids"],
            sorted([declared["record_id"], extra["record_id"]]),
        )
        self.assertEqual(receipt["diagnostics"][0]["code"], "contradictory-bundle")

    def test_v2_malformed_availability_metadata_is_typed_quarantine(self):
        record = canonical_record(
            record_id="record://synthetic/exchange-availability",
            sensitivity="public",
        )
        envelope = make_envelope_v2(
            "system://synthetic-receiver",
            "v2-malformed-availability",
            "2099-01-01T00:00:00Z",
            [revision_ref(record)],
            [],
        )
        reference = revision_ref(record)
        availability_key = (reference["record_id"], reference["revision_digest"])
        cases = (
            {"available_record_revisions": []},
            {"available_record_revisions": {("bad", "revision")}},
            {"available_record_sensitivities": []},
            {"available_record_sensitivities": {reference["record_id"]: "public"}},
            {"available_record_sensitivities": {availability_key: []}},
            {"available_record_sensitivities": {availability_key: {}}},
        )
        for options in cases:
            with self.subTest(options=options):
                receipt = admit_v2(
                    envelope,
                    expected_audience_ref="system://synthetic-receiver",
                    now="2026-08-03T00:00:00Z",
                    **options,  # type: ignore[arg-type]
                )
                self.assertEqual(receipt["outcome"], "quarantined")
                self.assertEqual(receipt["diagnostics"][0]["code"], "availability-metadata-invalid")

    def test_v2_noncanonical_envelope_and_invalid_time_fail_closed(self):
        record = canonical_record(
            record_id="record://synthetic/exchange-surrogate",
            sensitivity="public",
            meaning={"summary": "synthetic-\ud800"},
        )
        malformed = {
            "schema_id": "artifact-memory/exchange-envelope/v2",
            "envelope_id": "exchange://" + "0" * 64,
            "audience_ref": "system://synthetic-receiver",
            "correlation_id": "v2-surrogate",
            "expires_at": "2099-01-01T00:00:00Z",
            "bundle_manifest": {
                "bundle_id": "exchange-bundle://" + "a" * 64,
                "records": [{"record_id": record["record_id"], "revision_digest": "sha-256:" + "a" * 64}],
                "artifact_refs": [],
            },
            "record_bundle": [record],
            "handling": {
                "sensitivity": "public",
                "disclosure": "informational-only",
                "artifact_retrieval": "separately-authorized",
            },
            "authority_boundary": AUTHORITY_BOUNDARY,
        }
        receipt = admit_v2(
            malformed,
            expected_audience_ref="system://synthetic-receiver",
            now="2026-08-03T00:00:00Z",
        )
        self.assertEqual(receipt["outcome"], "rejected")

        valid = make_envelope_v2(
            "system://synthetic-receiver",
            "v2-invalid-now",
            "2099-01-01T00:00:00Z",
            [],
            ["artifact://synthetic/reference"],
        )
        invalid_now = admit_v2(
            valid,
            expected_audience_ref="system://synthetic-receiver",
            now=object(),  # type: ignore[arg-type]
        )
        self.assertEqual(invalid_now["outcome"], "rejected")
        self.assertEqual(invalid_now["diagnostics"][0]["code"], "invalid-expiry")

    def test_v2_ledger_claim_is_atomic_for_concurrent_replay(self):
        envelope = make_envelope_v2(
            "system://synthetic-receiver",
            "v2-concurrent-replay",
            "2099-01-01T00:00:00Z",
            [],
            ["artifact://synthetic/reference"],
        )
        ledger = SyntheticReplayLedger()
        barrier = threading.Barrier(2)
        outcomes: list[str] = []

        def admit_once() -> None:
            barrier.wait()
            outcomes.append(
                admit_v2(
                    envelope,
                    ledger,
                    expected_audience_ref="system://synthetic-receiver",
                    now="2026-08-03T00:00:00Z",
                )["outcome"]
            )

        workers = [threading.Thread(target=admit_once) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertCountEqual(outcomes, ["admitted", "duplicate"])

    def test_independent_reader_has_no_reference_runtime_imports(self):
        source = (ROOT / "artifact_memory/independent_reader.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        relative_imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level]
        self.assertEqual(relative_imports, [])

    def test_independent_reader_preserves_optional_and_rejects_required_extensions(self):
        record = canonical_record(extensions={"https://synthetic.example/optional": {"version": "v1", "required": False, "value": {"opaque": True}}})
        envelope = make_envelope("system://independent-reader", "synthetic-exchange-reader", "2099-01-01T00:00:00Z", [revision_ref(record)], ["artifact://synthetic/order"], record_bundle=[record])
        result = read_bundle(json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode())
        self.assertEqual(result["outcome"], "accepted")
        self.assertEqual(result["artifact_retrieval"], "separately-authorized")
        required = dict(record)
        required["extensions"] = {"https://synthetic.example/required": {"version": "v1", "required": True, "value": {}}}
        required_envelope = make_envelope("system://independent-reader", "synthetic-exchange-required", "2099-01-01T00:00:00Z", [revision_ref(required)], [], record_bundle=[required])
        with self.assertRaisesRegex(ReaderFailure, "required extension"):
            read_bundle(json.dumps(required_envelope).encode())
        supported = read_bundle(
            json.dumps(required_envelope).encode(),
            supported_required_extensions=[("https://synthetic.example/required", "v1")],
        )
        self.assertEqual(supported["preserved_extensions"], [required["extensions"]])
        with self.assertRaisesRegex(ReaderFailure, "required extension"):
            read_bundle(
                json.dumps(required_envelope).encode(),
                supported_required_extensions={("https://synthetic.example/required", "v2")},
            )

    def test_independent_reader_preserves_legacy_v1_opaque_extensions(self):
        extensions = {
            "legacy-name": ["schema-valid", 1, True],
            "https://synthetic.example/opaque": {"required": True, "legacy": "not a v0 declaration"},
        }
        record = canonical_record(extensions=extensions)
        envelope = make_envelope("system://independent-reader", "legacy-opaque", "2099-01-01T00:00:00Z", [revision_ref(record)], [], record_bundle=[record])
        result = read_bundle(json.dumps(envelope).encode())
        self.assertEqual(result["preserved_extensions"], [extensions])

    def test_independent_reader_rejects_malformed_support_configuration(self):
        record = canonical_record()
        envelope = make_envelope("system://independent-reader", "bad-support", "2099-01-01T00:00:00Z", [revision_ref(record)], [], record_bundle=[record])
        with self.assertRaisesRegex(ReaderFailure, "supported required"):
            read_bundle(json.dumps(envelope).encode(), supported_required_extensions={"legacy-string-form"})

    def test_independent_reader_binds_bundle_ids_and_revision_digests(self):
        record = canonical_record()
        envelope = make_envelope("system://independent-reader", "synthetic-exchange-binding", "2099-01-01T00:00:00Z", [revision_ref(record)], [], record_bundle=[record])

        substituted = {**envelope, "record_bundle": [canonical_record(meaning={"summary": "Substituted record."})]}
        with self.assertRaisesRegex(ReaderFailure, "revision digest"):
            read_bundle(json.dumps(substituted).encode())

        wrong_id = {**envelope, "record_refs": [{**revision_ref(record), "record_id": "record://synthetic/other"}]}
        with self.assertRaisesRegex(ReaderFailure, "does not match"):
            read_bundle(json.dumps(wrong_id).encode())

        extra_ref = revision_ref(canonical_record(record_id="record://synthetic/extra"))
        missing_bundle_entry = {**envelope, "record_refs": [revision_ref(record), extra_ref]}
        with self.assertRaisesRegex(ReaderFailure, "does not match"):
            read_bundle(json.dumps(missing_bundle_entry).encode())

        empty_bundle = {**envelope, "record_bundle": []}
        with self.assertRaisesRegex(ReaderFailure, "does not match"):
            read_bundle(json.dumps(empty_bundle).encode())

    def test_independent_reader_accepts_schema_valid_redacted_derivative(self):
        record = canonical_record(
            schema_id="artifact-memory/knowledge-record/v2",
            record_id="record://synthetic/redacted-reader",
            relationships=[{"type": "redacted-from", "target_ref": "record://synthetic/source-reader"}],
        )
        envelope = make_envelope(
            "system://independent-reader",
            "synthetic-redacted-reader",
            "2099-01-01T00:00:00Z",
            [revision_ref(record)],
            [],
            record_bundle=[record],
        )
        self.assertEqual(read_bundle(json.dumps(envelope).encode())["outcome"], "accepted")
        legacy = {**record, "schema_id": "artifact-memory/knowledge-record/v1"}
        legacy_envelope = make_envelope(
            "system://independent-reader",
            "synthetic-redacted-reader-v1-rejected",
            "2099-01-01T00:00:00Z",
            [revision_ref(legacy)],
            [],
            record_bundle=[legacy],
        )
        with self.assertRaisesRegex(ReaderFailure, "relationship"):
            read_bundle(json.dumps(legacy_envelope).encode())

    def test_admission_and_replay_are_explicit(self):
        envelope = make_envelope("system://synthetic-reader", "synthetic-exchange-0001", "2099-01-01T00:00:00Z", [{"record_id": "record://synthetic/record-0001", "revision_digest": "sha-256:" + "a" * 64}], ["artifact://synthetic/order-sample"])
        schema = json.loads((ROOT / "artifact_memory/schemas/core/exchange-envelope.v1.schema.json").read_text(encoding="utf-8"))
        validate(envelope, schema)
        receipt = admit(envelope, now="2026-07-30T00:00:00Z")
        receipt_schema = json.loads((ROOT / "artifact_memory/schemas/core/admission-receipt.v1.schema.json").read_text(encoding="utf-8"))
        validate(receipt, receipt_schema)
        self.assertEqual(receipt["outcome"], "admitted")
        self.assertEqual(receipt["authority_boundary"], AUTHORITY_BOUNDARY)
        replay = admit(envelope, {envelope["envelope_id"]}, now="2026-07-30T00:00:00Z")
        self.assertEqual(replay["outcome"], "duplicate")
        self.assertEqual(admit(envelope)["outcome"], "admitted")

    def test_expired_input_rejects_without_authority(self):
        envelope = make_envelope("system://synthetic-reader", "synthetic-exchange-0002", "2020-01-01T00:00:00Z", [{"record_id": "record://synthetic/record-0001", "revision_digest": "sha-256:" + "a" * 64}], [])
        receipt = admit(envelope, now="2026-07-30T00:00:00Z")
        self.assertEqual(receipt["outcome"], "rejected")
        self.assertEqual(receipt["diagnostics"][0]["code"], "expired")

    def test_admission_rejects_schema_invalid_envelopes_with_valid_receipts(self):
        receipt_schema = json.loads((ROOT / "artifact_memory/schemas/core/admission-receipt.v1.schema.json").read_text(encoding="utf-8"))
        malformed = {
            "schema_id": "artifact-memory/exchange-envelope/v1",
            "envelope_id": "not-an-envelope-id",
            "record_refs": [{"revision_digest": "sha-256:" + "a" * 64}],
        }
        receipt = admit(malformed)
        validate(receipt, receipt_schema)
        self.assertEqual(receipt["outcome"], "rejected")
        self.assertEqual(receipt["diagnostics"][0]["code"], "invalid-envelope")
        self.assertTrue(receipt["envelope_ref"].startswith("exchange://"))

    def test_admission_rejection_receipt_normalizes_uppercase_claimed_id(self):
        envelope = make_envelope("system://synthetic-reader", "uppercase-id", "2099-01-01T00:00:00Z", [], ["artifact://synthetic/item"])
        uppercase_id = "exchange://" + envelope["envelope_id"].removeprefix("exchange://").upper()
        receipt = admit({**envelope, "envelope_id": uppercase_id})
        receipt_schema = json.loads((ROOT / "artifact_memory/schemas/core/admission-receipt.v1.schema.json").read_text(encoding="utf-8"))
        validate(receipt, receipt_schema)
        self.assertEqual(receipt["outcome"], "rejected")
        self.assertEqual(receipt["envelope_ref"], envelope["envelope_id"])

    def test_admission_rejects_content_identity_mismatch_before_replay(self):
        envelope = make_envelope("system://synthetic-reader", "content-bound", "2099-01-01T00:00:00Z", [], ["artifact://synthetic/item"])
        tampered = {**envelope, "correlation_id": "different-valid-body"}
        receipt = admit(tampered, {envelope["envelope_id"]})
        receipt_schema = json.loads((ROOT / "artifact_memory/schemas/core/admission-receipt.v1.schema.json").read_text(encoding="utf-8"))
        validate(receipt, receipt_schema)
        self.assertEqual(receipt["outcome"], "rejected")
        self.assertEqual(receipt["diagnostics"][0]["code"], "envelope-id-mismatch")
        self.assertNotEqual(receipt["envelope_ref"], envelope["envelope_id"])

    def test_timezone_naive_expiry_is_rejected(self):
        envelope = make_envelope("system://synthetic-reader", "synthetic-exchange-naive", "2099-01-01T00:00:00", [], [])
        schema = json.loads((ROOT / "artifact_memory/schemas/core/exchange-envelope.v1.schema.json").read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ValidationFailure, "timezone offset"):
            validate(envelope, schema)
        self.assertEqual(admit(envelope)["outcome"], "rejected")

    def test_all_date_time_contract_fields_require_offsets(self):
        cases = [
            (
                "retention-policy.v2.schema.json",
                {
                    "schema_id": "artifact-memory/retention-policy/v2",
                    "policy_id": "retention-policy://synthetic/standard",
                    "retention_class": "standard",
                    "owner_ref": "actor://synthetic/owner",
                    "owner_hold": False,
                    "legal_hold": False,
                    "expires_at": "2099-01-01T00:00:00Z",
                    "backup_expiry_behavior": "managed-expiry",
                    "unknown_replica_behavior": "report-scope-unknown",
                    "git_history_behavior": "separate-rewrite-authorization-required",
                    "deletion_authority": "separate-owner-or-legal-authorization-required",
                },
                "expires_at",
            ),
            (
                "location-observation.v1.schema.json",
                {
                    "schema_id": "artifact-memory/location-observation/v1",
                    "observation_id": "location-observation://synthetic/record",
                    "content_ref": "content://synthetic/object",
                    "endpoint_ref": "endpoint://synthetic/store",
                    "relative_path": "records/object.json",
                    "presence": "present",
                    "observed_at": "2099-01-01T00:00:00Z",
                },
                "observed_at",
            ),
        ]
        for schema_name, record, field in cases:
            schema = json.loads((ROOT / "artifact_memory/schemas/core" / schema_name).read_text(encoding="utf-8"))
            validate(record, schema)
            naive = {**record, field: "2099-01-01T00:00:00"}
            with self.assertRaisesRegex(ValidationFailure, "timezone offset"):
                validate(naive, schema)

    def test_independent_reader_rejects_malformed_shapes_at_its_boundary(self):
        for value in ([], 1, "scalar"):
            with self.assertRaises(ReaderFailure):
                read_bundle(json.dumps(value).encode())
        malformed_record = canonical_record(extensions=[])
        malformed = make_envelope("system://independent-reader", "malformed-extensions", "2099-01-01T00:00:00Z", [revision_ref(malformed_record)], [], record_bundle=[malformed_record])
        with self.assertRaisesRegex(ReaderFailure, "extensions"):
            read_bundle(json.dumps(malformed).encode())
        legacy_record = canonical_record(extensions={"https://synthetic.example/extension": []})
        malformed = make_envelope("system://independent-reader", "legacy-extension", "2099-01-01T00:00:00Z", [revision_ref(legacy_record)], [], record_bundle=[legacy_record])
        self.assertEqual(read_bundle(json.dumps(malformed).encode())["preserved_extensions"], [legacy_record["extensions"]])
        malformed["record_bundle"][0] = {"schema_id": "artifact-memory/knowledge-record/v1", "record_id": "record://synthetic/incomplete"}
        with self.assertRaisesRegex(ReaderFailure, "fields"):
            read_bundle(json.dumps(malformed).encode())


if __name__ == "__main__":
    unittest.main()
