import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from artifact_memory.canonical import CanonicalizationFailure, canonical_bytes
from artifact_memory.canonical_content_conformance import render_receipt, run_conformance
from artifact_memory.content import verify_content
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import ValidationFailure, load_json, validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "synthetic"


class CanonicalContentTests(unittest.TestCase):
    def test_language_neutral_canonical_vectors_and_revision_examples(self):
        vectors = json.loads((FIXTURES / "canonical/v1/vectors.json").read_text(encoding="utf-8"))
        for vector in vectors["vectors"]:
            encoded = canonical_bytes(vector["input"])
            self.assertEqual(encoded.decode("utf-8"), vector["canonical_utf8"])
            self.assertEqual("sha-256:" + hashlib.sha256(encoded).hexdigest(), vector["digest"])

        revisions = json.loads((FIXTURES / "canonical/v1/revisions.json").read_text(encoding="utf-8"))
        schema = load_schema("core", "knowledge-record.v1.schema.json")
        for item in [*revisions["revisions"], revisions["replacement"]]:
            validate(item["record"], schema)
            self.assertEqual("sha-256:" + hashlib.sha256(canonical_bytes(item["record"])).hexdigest(), item["revision_digest"])
        self.assertEqual(revisions["git_identity_role"], "not-protocol-identity")

    def test_invalid_and_unsupported_canonical_inputs_fail_closed(self):
        invalid = FIXTURES / "canonical/v1/invalid"
        with self.assertRaises(ValidationFailure) as duplicate:
            load_json(invalid / "duplicate-key.json.invalid")
        self.assertEqual(duplicate.exception.code, "duplicate-key")
        with self.assertRaises(ValidationFailure) as non_finite:
            load_json(invalid / "non-finite.json.invalid")
        self.assertEqual(non_finite.exception.code, "invalid-json")
        for name in ("fractional-number.json.invalid", "unsafe-integer.json.invalid", "unpaired-surrogate.json.invalid"):
            with self.subTest(name=name), self.assertRaises(CanonicalizationFailure):
                canonical_bytes(load_json(invalid / name))
        cyclic: list[object] = []
        cyclic.append(cyclic)
        with self.assertRaisesRegex(CanonicalizationFailure, "cyclic container"):
            canonical_bytes(cyclic)

    def test_zero_and_large_content_recipes_stream_and_verify_all_digests(self):
        vectors = json.loads((FIXTURES / "content/v1/vectors.json").read_text(encoding="utf-8"))
        receipt_schema = load_schema("core", "content-verification-receipt.v1.schema.json")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for vector in vectors["recipes"]:
                recipe = vector["recipe"]
                data = bytes.fromhex(recipe["byte_hex"]) * recipe["count"]
                path = root / vector["id"]
                path.write_bytes(data)
                receipt = verify_content(path, vector["content_object"])
                self.assertEqual(receipt["outcome"], "verified")
                self.assertTrue(all(item["outcome"] == "verified" for item in receipt["digest_results"]))
                validate(receipt, receipt_schema)

    def test_verification_distinguishes_mismatch_unreadable_and_unsupported(self):
        content_object = json.loads((FIXTURES / "content/v1/vectors.json").read_text(encoding="utf-8"))["recipes"][0]["content_object"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mismatch = root / "mismatch"
            mismatch.write_bytes(b"not empty")
            self.assertEqual(verify_content(mismatch, content_object)["outcome"], "mismatch")
            unreadable = verify_content(root / "missing", content_object)
            self.assertEqual(unreadable["outcome"], "unreadable")
            self.assertNotIn(str(root), json.dumps(unreadable))
            unsupported = {"schema_id": "artifact-memory/content-object/v2", "content_id": "content://blake3/abcd", "digest": "blake3:abcd", "byte_size": 0, "media_type": "application/octet-stream"}
            unsupported_receipt = verify_content(root / "unused", unsupported)
            self.assertEqual(unsupported_receipt["outcome"], "unsupported")
            validate(unsupported_receipt, load_schema("core", "content-verification-receipt.v1.schema.json"))

            unsupported_secondary = json.loads(json.dumps(content_object))
            unsupported_secondary["secondary_digests"].append("blake3:abcd")
            secondary_receipt = verify_content(root / "unused", unsupported_secondary)
            self.assertEqual(secondary_receipt["outcome"], "unsupported")
            self.assertEqual(secondary_receipt["digest_results"][0]["outcome"], "not-checked")

            checked = root / "zero"
            checked.write_bytes(b"")
            secondary_mismatch = json.loads(json.dumps(content_object))
            secondary_mismatch["secondary_digests"] = ["sha-512:" + "0" * 128]
            mismatch_receipt = verify_content(checked, secondary_mismatch)
            self.assertEqual(mismatch_receipt["outcome"], "mismatch")
            self.assertEqual([item["outcome"] for item in mismatch_receipt["digest_results"]], ["verified", "mismatch"])

    def test_malformed_digest_claims_fail_before_byte_verification(self):
        content_object = json.loads((FIXTURES / "content/v1/vectors.json").read_text(encoding="utf-8"))["recipes"][0]["content_object"]
        malformed = json.loads(json.dumps(content_object))
        malformed["content_id"] = "content://sha-256/" + "0" * 64
        with self.assertRaises(ValidationFailure) as identity:
            verify_content(Path("unused"), malformed)
        self.assertEqual(identity.exception.code, "content-identity-mismatch")
        duplicate = json.loads(json.dumps(content_object))
        duplicate["secondary_digests"] = [duplicate["digest"]]
        with self.assertRaises(ValidationFailure) as repeated:
            verify_content(Path("unused"), duplicate)
        self.assertEqual(repeated.exception.code, "duplicate-digest-algorithm")

    def test_receipt_schema_binds_observations_to_outcomes(self):
        schema = load_schema("core", "content-verification-receipt.v1.schema.json")
        content_object = json.loads((FIXTURES / "content/v1/vectors.json").read_text(encoding="utf-8"))["recipes"][0]["content_object"]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "zero"
            path.write_bytes(b"")
            verified = verify_content(path, content_object)
        missing_observation = json.loads(json.dumps(verified))
        missing_observation.pop("observed_byte_size")
        with self.assertRaises(ValidationFailure):
            validate(missing_observation, schema)
        unreadable_with_observation = verify_content(Path("not-present"), content_object)
        unreadable_with_observation["observed_byte_size"] = 0
        with self.assertRaises(ValidationFailure):
            validate(unreadable_with_observation, schema)

    def test_checked_machine_and_human_receipts_replay(self):
        receipt = run_conformance(FIXTURES)
        expected = json.loads((FIXTURES / "canonical-content/v1/expected-receipt.json").read_text(encoding="utf-8"))
        expected_markdown = (FIXTURES / "canonical-content/v1/receipt.md").read_text(encoding="utf-8")
        self.assertEqual(receipt, expected)
        self.assertEqual(render_receipt(receipt), expected_markdown)


if __name__ == "__main__":
    unittest.main()
