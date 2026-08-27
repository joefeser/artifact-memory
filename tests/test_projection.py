import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from artifact_memory import projection
from artifact_memory.canonical import sha256_bytes
from artifact_memory.projection import (
    _read_index,
    canonical_records,
    logical_projection_snapshot,
    project_records,
    projection_metadata,
    records_with_provenance,
    related_records,
    search_receipt,
    search_records,
)
from artifact_memory.validator import ValidationFailure


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic" / "contracts" / "v0-valid-record.json"


class ProjectionTests(unittest.TestCase):
    def test_v1_legacy_record_preserves_non_namespaced_extension_identifier(self):
        """The legacy knowledge-record/v1 contract preserves an opaque value under a
        non-namespaced identifier unchanged; this exception does not extend to v2/v3."""
        with tempfile.TemporaryDirectory() as temporary:
            record = json.loads(FIXTURE.read_text(encoding="utf-8"))
            record["extensions"] = {"local-name": "opaque"}
            path = Path(temporary) / "record.json"
            path.write_text(json.dumps(record), encoding="utf-8")
            records = canonical_records([path])
            self.assertEqual(records[0]["extensions"], {"local-name": "opaque"})

    def test_v2_record_rejects_non_namespaced_extension_identifier(self):
        """A non-legacy record must fail closed on a non-namespaced extension
        identifier instead of silently letting it reach generated views."""
        with tempfile.TemporaryDirectory() as temporary:
            record = json.loads(FIXTURE.read_text(encoding="utf-8"))
            record["schema_id"] = "artifact-memory/knowledge-record/v2"
            record["extensions"] = {"local-name": "opaque"}
            path = Path(temporary) / "record.json"
            path.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaises(ValidationFailure) as raised:
                canonical_records([path])
            self.assertEqual(raised.exception.code, "invalid-extension-identifier")

    def test_projection_is_rebuildable_and_queryable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_record = json.loads(FIXTURE.read_text(encoding="utf-8"))
            first_record["relationships"] = [{"type": "related-to", "target_ref": "record://synthetic/record-0002"}]
            second_record = {
                "schema_id": "artifact-memory/knowledge-record/v1",
                "record_id": "record://synthetic/record-0002",
                "record_type": "decision",
                "lifecycle": "accepted",
                "meaning": {"summary": "Synthetic projection decision"},
                "artifact_refs": [],
                "provenance": [{"kind": "author", "source_ref": "fixture://synthetic/contracts/v0"}],
                "sensitivity": "public",
            }
            one = root / "one.json"
            two = root / "two.json"
            one.write_text(json.dumps(first_record), encoding="utf-8")
            two.write_text(json.dumps(second_record), encoding="utf-8")
            first_out = root / "first"
            second_out = root / "second"
            first_receipt = project_records([two, one], first_out)
            second_receipt = project_records([one, two], second_out)
            self.assertEqual(first_receipt["source_record_set_digest"], second_receipt["source_record_set_digest"])
            self.assertEqual((first_out / "records.ndjson").read_bytes(), (second_out / "records.ndjson").read_bytes())
            self.assertEqual(search_records(first_out / "records.sqlite", "projection"), ["record://synthetic/record-0002"])
            self.assertEqual(related_records(first_out / "records.sqlite", "record://synthetic/record-0001"), [{"type": "related-to", "target_ref": "record://synthetic/record-0002"}])
            self.assertEqual(
                records_with_provenance(first_out / "records.sqlite", "fixture://synthetic/contracts/v0"),
                [
                    {
                        "record_id": "record://synthetic/record-0001",
                        "kind": "author",
                        "source_ref": "fixture://synthetic/contracts/v0",
                    },
                    {
                        "record_id": "record://synthetic/record-0002",
                        "kind": "author",
                        "source_ref": "fixture://synthetic/contracts/v0",
                    },
                ],
            )
            metadata = projection_metadata(first_out / "records.sqlite")
            self.assertEqual(metadata["projection_schema_id"], "artifact-memory/sqlite-projection/v1")
            self.assertEqual(metadata["user_version"], 1)
            self.assertEqual(metadata["source_record_set_digest"], first_receipt["source_record_set_digest"])
            self.assertEqual(metadata["record_count"], 2)
            self.assertNotIn(str(root).encode("utf-8"), (first_out / "records.sqlite").read_bytes())
            with self.assertRaises(ValidationFailure) as raised:
                search_records(first_out / "records.sqlite", '"')
            self.assertEqual(raised.exception.code, "query-invalid")
            first_snapshot = logical_projection_snapshot(first_out / "records.sqlite")
            for name in ("records.ndjson", "records.sqlite", "projection-receipt.json"):
                (first_out / name).unlink()
            rebuilt_receipt = project_records([one, two], first_out)
            self.assertEqual(rebuilt_receipt, first_receipt)
            self.assertEqual(logical_projection_snapshot(first_out / "records.sqlite"), first_snapshot)
            self.assertEqual(search_records(first_out / "records.sqlite", "projection"), ["record://synthetic/record-0002"])

    def test_projection_rejects_invalid_canonical_record_before_writing_views(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            invalid = root / "invalid.json"
            invalid.write_text('{"schema_id":"artifact-memory/knowledge-record/v1"}', encoding="utf-8")
            output = root / "generated"
            with self.assertRaises(ValidationFailure) as raised:
                project_records([invalid], output)
            self.assertEqual(raised.exception.code, "record-rejected")
            self.assertFalse(output.exists())

    def test_projection_rejects_unknown_required_extensions_before_writing_views(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record = json.loads(FIXTURE.read_text(encoding="utf-8"))
            record["extensions"] = {
                "https://synthetic.example/required": {
                    "version": "v1",
                    "required": True,
                    "value": {"synthetic": True},
                }
            }
            record_path = root / "required.json"
            record_path.write_text(json.dumps(record), encoding="utf-8")
            output = root / "generated"

            with self.assertRaises(ValidationFailure) as raised:
                project_records([record_path], output)

            self.assertEqual(raised.exception.code, "required-extension-unsupported")
            self.assertFalse(output.exists())

    def test_projection_preserves_opaque_non_declaration_extensions(self):
        """Unknown optional/opaque extension values must be preserved, not interpreted or rejected."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record = json.loads(FIXTURE.read_text(encoding="utf-8"))
            record["extensions"] = {"https://synthetic.example/opaque": "not-a-declaration-object"}
            record_path = root / "opaque.json"
            record_path.write_text(json.dumps(record), encoding="utf-8")
            output = root / "generated"

            receipt = project_records([record_path], output)
            ndjson_record = json.loads((output / "records.ndjson").read_text(encoding="utf-8"))
            self.assertEqual(receipt["outcome"], "complete")
            self.assertEqual(ndjson_record["extensions"]["https://synthetic.example/opaque"], "not-a-declaration-object")

    def test_projection_preserves_incomplete_required_true_dict(self):
        """An object like {"required": true} missing version/value is legacy opaque data, not a declaration."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record = json.loads(FIXTURE.read_text(encoding="utf-8"))
            record["extensions"] = {"https://synthetic.example/incomplete": {"required": True}}
            record_path = root / "incomplete.json"
            record_path.write_text(json.dumps(record), encoding="utf-8")
            output = root / "generated"

            receipt = project_records([record_path], output)
            self.assertEqual(receipt["outcome"], "complete")
            ndjson_record = json.loads((output / "records.ndjson").read_text(encoding="utf-8"))
            connection = sqlite3.connect(output / "records.sqlite")
            try:
                sqlite_record = json.loads(connection.execute("SELECT record_json FROM records").fetchone()[0])
            finally:
                connection.close()
            self.assertEqual(ndjson_record, sqlite_record)
            self.assertEqual(
                ndjson_record["extensions"]["https://synthetic.example/incomplete"],
                {"required": True},
            )

    def test_projection_preserves_unknown_optional_extensions_in_generated_views(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record = json.loads(FIXTURE.read_text(encoding="utf-8"))
            declaration = {
                "version": "v1",
                "required": False,
                "value": {"synthetic": True},
            }
            record["extensions"] = {"https://synthetic.example/optional": declaration}
            record_path = root / "optional.json"
            record_path.write_text(json.dumps(record), encoding="utf-8")
            output = root / "generated"

            receipt = project_records([record_path], output)
            ndjson_record = json.loads((output / "records.ndjson").read_text(encoding="utf-8"))
            connection = sqlite3.connect(output / "records.sqlite")
            try:
                sqlite_record = json.loads(
                    connection.execute("SELECT record_json FROM records").fetchone()[0]
                )
            finally:
                connection.close()

            self.assertEqual(receipt["outcome"], "complete")
            self.assertEqual(ndjson_record, sqlite_record)
            self.assertEqual(
                ndjson_record["extensions"]["https://synthetic.example/optional"],
                declaration,
            )

    def test_querying_missing_projection_is_read_only_and_typed(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing.sqlite"
            with self.assertRaises(ValidationFailure) as raised:
                search_records(missing, "synthetic")
            self.assertEqual(raised.exception.code, "projection-unavailable")
            self.assertFalse(missing.exists())

    def test_projection_queries_reject_wrong_version_and_malformed_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrong_version_output = root / "wrong-version"
            project_records([FIXTURE], wrong_version_output)
            wrong_version = wrong_version_output / "records.sqlite"
            connection = sqlite3.connect(wrong_version)
            connection.execute("PRAGMA user_version = 999")
            connection.commit()
            connection.close()
            with self.assertRaises(ValidationFailure) as raised:
                search_records(wrong_version, "synthetic")
            self.assertEqual(raised.exception.code, "projection-schema-mismatch")

            malformed = root / "malformed.sqlite"
            connection = sqlite3.connect(malformed)
            connection.execute("PRAGMA user_version = 1")
            connection.execute("CREATE VIRTUAL TABLE records_fts USING fts5(record_id, summary, labels)")
            connection.commit()
            connection.close()
            with self.assertRaises(ValidationFailure) as raised:
                search_records(malformed, "synthetic")
            self.assertEqual(raised.exception.code, "projection-unavailable")

    def test_projection_queries_reject_metadata_and_derived_row_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            schema_output = root / "schema"
            project_records([FIXTURE], schema_output)
            connection = sqlite3.connect(schema_output / "records.sqlite")
            connection.execute("UPDATE projection_metadata SET projection_schema_id = 'artifact-memory/sqlite-projection/v999'")
            connection.commit()
            connection.close()
            with self.assertRaises(ValidationFailure) as raised:
                related_records(schema_output / "records.sqlite", "record://synthetic/record-0001")
            self.assertEqual(raised.exception.code, "projection-schema-mismatch")

            count_output = root / "count"
            project_records([FIXTURE], count_output)
            connection = sqlite3.connect(count_output / "records.sqlite")
            connection.execute("UPDATE projection_metadata SET record_count = 99")
            connection.commit()
            connection.close()
            with self.assertRaises(ValidationFailure) as raised:
                projection_metadata(count_output / "records.sqlite")
            self.assertEqual(raised.exception.code, "projection-unavailable")

            provenance_output = root / "provenance"
            project_records([FIXTURE], provenance_output)
            connection = sqlite3.connect(provenance_output / "records.sqlite")
            connection.execute("PRAGMA ignore_check_constraints = ON")
            connection.execute("UPDATE provenance SET ordinal = -1")
            connection.commit()
            connection.close()
            with self.assertRaises(ValidationFailure) as raised:
                records_with_provenance(provenance_output / "records.sqlite", "fixture://synthetic/contracts/v0")
            self.assertEqual(raised.exception.code, "projection-unavailable")

            search_output = root / "search"
            project_records([FIXTURE], search_output)
            connection = sqlite3.connect(search_output / "records.sqlite")
            connection.execute("UPDATE records_fts SET summary = 'forged stale summary'")
            connection.commit()
            connection.close()
            with self.assertRaises(ValidationFailure) as raised:
                search_records(search_output / "records.sqlite", "forged")
            self.assertEqual(raised.exception.code, "projection-unavailable")

    def test_projection_queries_reject_fts_inverted_index_tampering(self):
        """A two-step forgery reindexes through records_fts and then restores
        records_fts_content, so every content row still matches its canonical
        record while the inverted index serves forged terms; reads must fail
        closed on physical integrity instead of trusting the content rows."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "generated"
            project_records([FIXTURE], output)
            index = output / "records.sqlite"
            connection = sqlite3.connect(index)
            original_id, original_summary = connection.execute("SELECT c0, c1 FROM records_fts_content").fetchone()
            connection.execute(
                "UPDATE records_fts SET summary = ? WHERE record_id = ?",
                ("forged summary containing syntheticforged", original_id),
            )
            connection.execute(
                "UPDATE records_fts_content SET c1 = ? WHERE c0 = ?",
                (original_summary, original_id),
            )
            connection.commit()
            connection.close()
            probes = {
                "search": lambda: search_records(index, "syntheticforged"),
                "related": lambda: related_records(index, original_id),
                "provenance": lambda: records_with_provenance(index, "fixture://synthetic/contracts/v0"),
                "metadata": lambda: projection_metadata(index),
                "logical-snapshot": lambda: logical_projection_snapshot(index),
            }
            for surface, probe in probes.items():
                with self.subTest(surface=surface):
                    with self.assertRaises(ValidationFailure) as raised:
                        probe()
                    self.assertEqual(raised.exception.code, "projection-unavailable")

    def test_projection_reads_fail_closed_without_fts5_integrity_runtime(self):
        """A runtime whose PRAGMA integrity_check cannot reach the FTS5
        inverted index returns ok without evidence, so reads must fail closed
        instead of treating that ok as verification."""
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "generated"
            project_records([FIXTURE], output)
            index = output / "records.sqlite"
            with mock.patch.object(projection, "_RUNTIME_VERIFIES_FTS5_INTEGRITY", False):
                with self.assertRaises(ValidationFailure) as raised:
                    search_records(index, "synthetic")
                self.assertEqual(raised.exception.code, "projection-unavailable")
            self.assertEqual(search_records(index, "synthetic"), ["record://synthetic/record-0001"])

    def test_projection_read_holds_one_snapshot_against_concurrent_writers(self):
        """Verification and the caller query must observe one read snapshot: a
        writer cannot commit the two-step forgery after the integrity check but
        before the query while the read transaction is open."""
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "generated"
            project_records([FIXTURE], output)
            index = output / "records.sqlite"
            with _read_index(index) as reader:
                snapshot = reader.execute("SELECT record_id FROM records ORDER BY record_id").fetchall()
                writer = sqlite3.connect(index, timeout=0.05)
                try:
                    with self.assertRaises(sqlite3.OperationalError):
                        writer.execute(
                            "UPDATE records_fts SET summary = 'forged summary containing syntheticforged'"
                        )
                        writer.commit()
                finally:
                    writer.close()
                self.assertEqual(
                    reader.execute("SELECT record_id FROM records ORDER BY record_id").fetchall(),
                    snapshot,
                )
            writer = sqlite3.connect(index)
            writer.execute("UPDATE records_fts SET summary = 'forged summary containing syntheticforged'")
            writer.commit()
            writer.close()
            with self.assertRaises(ValidationFailure) as raised:
                search_records(index, "syntheticforged")
            self.assertEqual(raised.exception.code, "projection-unavailable")

    def test_search_receipt_pins_results_to_source_record_set(self):
        """The digest-bearing receipt is additive: same matches as the raw
        search surface, plus the source digest and gate state, while
        search_records keeps its shape."""
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "generated"
            projection_receipt = project_records([FIXTURE], output)
            index = output / "records.sqlite"
            receipt = search_receipt(index, "synthetic")
            self.assertEqual(receipt["schema_id"], "artifact-memory/search-receipt/v1")
            self.assertEqual(receipt["outcome"], "complete")
            self.assertNotIn("query", receipt)
            self.assertEqual(receipt["query_digest"], sha256_bytes(b"synthetic"))
            self.assertEqual(receipt["record_ids"], search_records(index, "synthetic"))
            self.assertEqual(receipt["source_record_set_digest"], projection_receipt["source_record_set_digest"])
            self.assertEqual(receipt["integrity_gate"], "verified")
            with self.assertRaises(ValidationFailure) as raised:
                search_receipt(index, '"')
            self.assertEqual(raised.exception.code, "query-invalid")

    def test_search_receipt_refuses_tampered_index(self):
        """A receipt must not vouch for an index whose inverted index failed
        the read gate, even though its content rows still validate."""
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "generated"
            project_records([FIXTURE], output)
            index = output / "records.sqlite"
            connection = sqlite3.connect(index)
            original_id, original_summary = connection.execute("SELECT c0, c1 FROM records_fts_content").fetchone()
            connection.execute(
                "UPDATE records_fts SET summary = ? WHERE record_id = ?",
                ("forged summary containing syntheticforged", original_id),
            )
            connection.execute(
                "UPDATE records_fts_content SET c1 = ? WHERE c0 = ?",
                (original_summary, original_id),
            )
            connection.commit()
            connection.close()
            with self.assertRaises(ValidationFailure) as raised:
                search_receipt(index, "syntheticforged")
            self.assertEqual(raised.exception.code, "projection-unavailable")

    def _literal_fixture(self, root: Path) -> Path:
        summaries = (
            "Synthetic alpha-beta adjacency proves literal quoting.",
            "Scattered alpha and beta words never form the phrase.",
            'Synthetic five "inches recorded without escapes.',
        )
        for ordinal, summary in enumerate(summaries, start=1):
            record = {
                "schema_id": "artifact-memory/knowledge-record/v1",
                "record_id": f"record://synthetic/literal-000{ordinal}",
                "record_type": "note",
                "lifecycle": "accepted",
                "meaning": {"summary": summary},
                "artifact_refs": [],
                "provenance": [{"kind": "author", "source_ref": "fixture://synthetic/literal/v1"}],
                "sensitivity": "public",
            }
            (root / f"literal-000{ordinal}.json").write_text(json.dumps(record), encoding="utf-8")
        return root

    def test_literal_search_matches_one_term_without_syntax_reinterpretation(self):
        """Literal mode treats the query as a single term: a hyphenated query
        is a phrase match instead of raw column-filter syntax, an embedded
        double quote is doubled instead of parsed as FTS5 string syntax, and
        an empty literal query fails typed without reaching SQLite."""
        with tempfile.TemporaryDirectory() as temporary:
            root = self._literal_fixture(Path(temporary))
            output = root / "generated"
            project_records(sorted(root.glob("literal-*.json")), output)
            index = output / "records.sqlite"
            self.assertEqual(
                search_records(index, "alpha-beta", literal=True),
                ["record://synthetic/literal-0001"],
            )
            with self.assertRaises(ValidationFailure) as raised:
                search_records(index, "alpha-beta")
            self.assertEqual(raised.exception.code, "query-invalid")
            self.assertEqual(
                search_records(index, 'five "inches', literal=True),
                ["record://synthetic/literal-0003"],
            )
            with self.assertRaises(ValidationFailure) as raised:
                search_records(index, 'five "inches')
            self.assertEqual(raised.exception.code, "query-invalid")
            with self.assertRaises(ValidationFailure) as raised:
                search_records(index, "", literal=True)
            self.assertEqual(raised.exception.code, "query-invalid")

    def test_search_failure_classification_uses_sqlite_error_code(self):
        """Query failures classify on sqlite_errorcode & 0xff, not message
        text: 1 (SQLITE_ERROR) is query-invalid, anything else is
        projection-unavailable."""
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE VIRTUAL TABLE t USING fts5(body)")
        connection.commit()
        try:
            connection.execute('SELECT rowid FROM t WHERE t MATCH ?', ("'",)).fetchall()
            self.fail("malformed match expression did not raise")
        except sqlite3.Error as exc:
            syntax_error = exc
        finally:
            connection.close()
        self.assertEqual(syntax_error.sqlite_errorcode & 0xFF, 1)
        self.assertEqual(projection._classify_search_failure(syntax_error).code, "query-invalid")
        io_error = sqlite3.OperationalError("disk I/O error during match execution")
        io_error.sqlite_errorcode = 10
        self.assertEqual(projection._classify_search_failure(io_error).code, "projection-unavailable")

    def test_search_receipt_literal_mode_pins_typed_query(self):
        """The receipt works in literal mode and digests the query exactly as
        the caller typed it, not the quoted match expression."""
        with tempfile.TemporaryDirectory() as temporary:
            root = self._literal_fixture(Path(temporary))
            output = root / "generated"
            project_records(sorted(root.glob("literal-*.json")), output)
            receipt = search_receipt(output / "records.sqlite", "alpha-beta", literal=True)
            self.assertEqual(receipt["record_ids"], ["record://synthetic/literal-0001"])
            self.assertEqual(receipt["query_digest"], sha256_bytes(b"alpha-beta"))


if __name__ == "__main__":
    unittest.main()
