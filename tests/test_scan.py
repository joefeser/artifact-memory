import tempfile
import unittest
from pathlib import Path
import hashlib
import json
import os
import stat
from types import SimpleNamespace
from unittest.mock import patch

import artifact_memory.scan as scan_module
from artifact_memory.canonical import canonical_bytes
from artifact_memory.scan import ScanLimits, diff_manifests, make_scan_policy, scan_path, validate_manifest_identity, validate_scan_policy, validate_scan_receipt, verify_path
from artifact_memory.scan_conformance import render_scan_conformance_receipt, run_scan_conformance
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import ValidationFailure, validate

ROOT = Path(__file__).resolve().parents[1]
SCAN_FIXTURE = ROOT / "fixtures/synthetic/scan/v2"


class ScanTests(unittest.TestCase):
    def test_v2_policy_and_receipt_bind_scope_attempt_and_manifest(self):
        policy = make_scan_policy(endpoint_ref="endpoint://synthetic/vault", root_relative_path="records")
        validate_scan_policy(policy)
        tampered = json.loads(json.dumps(policy))
        tampered["root_relative_path"] = "other"
        with self.assertRaises(ValidationFailure) as failure:
            validate_scan_policy(tampered)
        self.assertEqual(failure.exception.code, "scan-policy-identity-invalid")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "record.json").write_text("synthetic", encoding="utf-8")
            manifest, receipt = scan_path(root, policy=policy)
        self.assertEqual(receipt["schema_id"], "artifact-memory/scan-receipt/v2")
        self.assertRegex(receipt["attempt_id"], r"^urn:uuid:[0-9a-f-]{36}$")
        self.assertEqual(receipt["policy_ref"], policy["policy_id"])
        self.assertEqual(receipt["policy_digest"], policy["policy_digest"])
        self.assertEqual(receipt["scope"], {"endpoint_ref": "endpoint://synthetic/vault", "root_relative_path": "records"})
        self.assertEqual(receipt["manifest_ref"], manifest["manifest_id"])
        self.assertEqual(receipt["manifest_tree_digest"], manifest["tree_digest"])
        self.assertEqual(receipt["implementation"]["name"], "artifact-memory-python")
        self.assertLessEqual(receipt["started_at"], receipt["ended_at"])
        self.assertNotIn(str(root), json.dumps(receipt))
        validate_scan_receipt(receipt, policy, manifest)
        tampered_receipt = json.loads(json.dumps(receipt))
        tampered_receipt["manifest_tree_digest"] = "sha-256:" + "0" * 64
        with self.assertRaises(ValidationFailure) as receipt_failure:
            validate_scan_receipt(tampered_receipt, policy, manifest)
        self.assertEqual(receipt_failure.exception.code, "scan-receipt-identity-invalid")

        mismatched_count = json.loads(json.dumps(receipt))
        mismatched_count["accounted_entry_count"] = 0
        body = {key: value for key, value in mismatched_count.items() if key not in {"schema_id", "receipt_id"}}
        mismatched_count["receipt_id"] = "scan-receipt://sha-256/" + hashlib.sha256(canonical_bytes(body)).hexdigest()
        with self.assertRaises(ValidationFailure) as count_failure:
            validate_scan_receipt(mismatched_count, policy, manifest)
        self.assertEqual(count_failure.exception.code, "scan-receipt-count-invalid")

    def test_scan_policy_rejects_non_normalized_relative_paths(self):
        for invalid in (
            ".",
            "nested//value",
            "nested/./value",
            "../value",
            "/absolute",
            "windows\\path",
            "line\nbreak",
            "tab\tpath",
            "report:final.txt",
            "CON",
            "con.txt",
            "folder/NUL.json",
            "trailing.",
            "trailing ",
            "angle<name>",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValidationFailure) as failure:
                    make_scan_policy(root_relative_path=invalid)
                self.assertIn(failure.exception.code, {"constraint-failed", "scan-policy-path-invalid"})

    def test_scan_policy_schema_rejects_windows_reserved_components(self):
        schema = load_schema("core", "scan-policy.v2.schema.json")
        for invalid in ("con", "dir/con.txt", "AUX", "nested/Com1.log", "lpt9", "COM¹.txt"):
            with self.subTest(root_relative_path=invalid):
                policy = {**make_scan_policy(), "root_relative_path": invalid}
                with self.assertRaises(ValidationFailure) as failure:
                    validate(policy, schema)
                self.assertEqual(failure.exception.code, "constraint-failed")

            with self.subTest(exclusion_prefix=invalid):
                policy = {**make_scan_policy(), "exclusion_prefixes": [invalid]}
                with self.assertRaises(ValidationFailure) as failure:
                    validate(policy, schema)
                self.assertEqual(failure.exception.code, "constraint-failed")

    def test_attempt_id_distinguishes_otherwise_identical_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                patch("artifact_memory.scan._utc_now", side_effect=["2099-01-01T00:00:00Z"] * 4),
                patch("artifact_memory.scan._new_attempt_id", side_effect=[
                    "urn:uuid:00000000-0000-4000-8000-000000000001",
                    "urn:uuid:00000000-0000-4000-8000-000000000002",
                ]),
            ):
                _, first = scan_path(root)
                _, second = scan_path(root)
        self.assertNotEqual(first["attempt_id"], second["attempt_id"])
        self.assertNotEqual(first["receipt_id"], second["receipt_id"])

    def test_declared_exclusion_is_applied_before_entry_metadata_or_content_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root_metadata = os.lstat(root)

            class ExcludedEntry:
                name = "private"
                path = str(root / name)

                @staticmethod
                def stat(*, follow_symlinks):
                    raise AssertionError("excluded entry metadata must not be read")

            class Scandir:
                def __enter__(self):
                    return iter([ExcludedEntry()])

                def __exit__(self, *_args):
                    return False

            policy = make_scan_policy(exclusion_prefixes=("private",))
            with (
                patch("artifact_memory.scan.os.lstat", return_value=root_metadata),
                patch("artifact_memory.scan.os.scandir", return_value=Scandir()),
                patch("artifact_memory.scan._hash_regular_file") as hash_file,
            ):
                manifest, receipt = scan_path(root, policy=policy)
            hash_file.assert_not_called()
        self.assertEqual(manifest["entries"], [])
        self.assertEqual(receipt["outcome"], "complete")
        self.assertEqual(receipt["excluded_entry_count"], 1)
        self.assertEqual(receipt["exclusions"], [{"relative_path": "private", "rule": "prefix:private"}])
        self.assertEqual(receipt["warnings"], [])
        self.assertEqual(receipt["failures"], [])

    def test_checked_scan_conformance_vectors_replay(self):
        receipt = run_scan_conformance(SCAN_FIXTURE / "vectors.json")
        expected = json.loads((SCAN_FIXTURE / "expected-receipt.json").read_text(encoding="utf-8"))
        expected_markdown = (SCAN_FIXTURE / "receipt.md").read_text(encoding="utf-8")
        self.assertEqual(receipt, expected)
        self.assertEqual(render_scan_conformance_receipt(receipt), expected_markdown)
        by_id = {item["id"]: item for item in receipt["cases"]}
        self.assertEqual(by_id["inaccessible-entry"]["failure_codes"], ["unreadable"])
        self.assertEqual(by_id["changing-file"]["failure_codes"], ["unstable"])

    def test_cross_platform_ordinary_tree_vector_is_path_layout_independent(self):
        vector = json.loads((Path(__file__).resolve().parents[1] / "fixtures/synthetic/manifests/v0-ordinary-tree.json").read_text(encoding="utf-8"))
        lines = "".join(f"file\t{entry['path']}\t{entry['content_digest']}\t{entry['byte_size']}\n" for entry in vector["logical_entries"])
        self.assertEqual("sha-256:" + hashlib.sha256(lines.encode()).hexdigest(), vector["tree_digest"])
        self.assertNotEqual(vector["container_digest"], vector["extracted_tree_digest"])
        self.assertEqual(len(set(vector["platform_layouts"].values())), 3)

    def test_deterministic_scan_and_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            (root / "src" / "orders.txt").write_bytes(b"synthetic orders\n")
            first, receipt = scan_path(root)
            second, _ = scan_path(root)
            self.assertEqual(first, second)
            self.assertEqual(receipt["outcome"], "complete")
            self.assertEqual(verify_path(root, first)["outcome"], "verified")
            self.assertEqual(verify_path(root / "missing", first)["outcome"], "incomplete")

    def test_verification_rejects_malformed_manifest_before_digest_comparison(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            malformed = {
                "schema_id": "artifact-memory/manifest/v1",
                "completeness": "complete",
                "tree_digest": "sha-256:" + hashlib.sha256(b"").hexdigest(),
            }
            result = verify_path(root, malformed)
            self.assertEqual(result["outcome"], "rejected")
            self.assertEqual(result["diagnostics"][0]["code"], "required-field-missing")

    def test_verification_rejects_manifest_identity_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_root = root / "first"
            second_root = root / "second"
            first_root.mkdir()
            second_root.mkdir()
            (first_root / "value.txt").write_text("first", encoding="utf-8")
            (second_root / "value.txt").write_text("second", encoding="utf-8")
            first, _ = scan_path(first_root)
            second, _ = scan_path(second_root)
            tampered_digest = {**first, "tree_digest": second["tree_digest"]}
            self.assertEqual(verify_path(second_root, tampered_digest)["outcome"], "rejected")
            tampered_id = {**first, "manifest_id": second["manifest_id"]}
            self.assertEqual(verify_path(first_root, tampered_id)["outcome"], "rejected")

    def test_verification_does_not_substitute_an_undeclared_scan_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "value.txt").write_text("synthetic", encoding="utf-8")
            manifest, _ = scan_path(root)
            manifest["policy_ref"] = "scan-policy://synthetic/other"
            identity_payload = {key: value for key, value in manifest.items() if key not in {"manifest_id", "tree_digest"}}
            manifest["manifest_id"] = "manifest://" + hashlib.sha256(canonical_bytes(identity_payload)).hexdigest()
            result = verify_path(root, manifest)
            self.assertEqual(result["outcome"], "policy-required")
            self.assertEqual(result["diagnostics"][0]["code"], "scan-policy-required")
            supplied = verify_path(root, manifest, policy=make_scan_policy())
            self.assertEqual(supplied["outcome"], "unsupported")
            self.assertEqual(supplied["diagnostics"][0]["code"], "scan-policy-unsupported")

    def test_diff_reports_content_changes_and_move_candidates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "old.txt").write_text("same", encoding="utf-8")
            before, _ = scan_path(root)
            (root / "old.txt").rename(root / "new.txt")
            (root / "changed.txt").write_text("new", encoding="utf-8")
            after, _ = scan_path(root)
            result = diff_manifests(before, after)
            self.assertEqual(result["outcome"], "complete")
            self.assertEqual(result["before_completeness"], "complete")
            self.assertEqual(result["after_completeness"], "complete")
            self.assertEqual(result["added"], ["changed.txt", "new.txt"])
            self.assertEqual(result["removed"], ["old.txt"])
            self.assertEqual(result["changed"], [])
            self.assertEqual(result["moved_candidates"][0]["from"], "old.txt")
            self.assertEqual(result["moved_candidates"][0]["to"], "new.txt")

    def test_duplicate_content_move_candidates_are_not_collapsed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "old-a.txt").write_text("same", encoding="utf-8")
            (root / "old-b.txt").write_text("same", encoding="utf-8")
            before, _ = scan_path(root)
            (root / "old-a.txt").unlink()
            (root / "old-b.txt").unlink()
            (root / "new.txt").write_text("same", encoding="utf-8")
            after, _ = scan_path(root)
            candidates = diff_manifests(before, after)["moved_candidates"]
            self.assertEqual([item["from"] for item in candidates], ["old-a.txt", "old-b.txt"])

    def test_diff_rejects_invalid_manifest_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "value.txt").write_text("synthetic", encoding="utf-8")
            before, _ = scan_path(root)
            after, _ = scan_path(root)
            after["entries"][0]["content_digest"] = "sha-256:" + "0" * 64
            with self.assertRaises(ValidationFailure) as raised:
                diff_manifests(before, after)
            self.assertEqual(raised.exception.code, "manifest-identity-invalid")

    def test_diff_keeps_partial_input_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "value.txt").write_text("synthetic", encoding="utf-8")
            complete, _ = scan_path(root)
            partial, _ = scan_path(root, ScanLimits(max_bytes=0))
            result = diff_manifests(partial, complete)
            self.assertEqual(result["outcome"], "partial")
            self.assertEqual(result["before_completeness"], "partial")
            self.assertEqual(result["diagnostics"][0]["code"], "input-manifest-incomplete")
            self.assertIn("partial input manifests", result["limitations"][1])

    def test_diff_rejects_mixed_scan_policies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "value.txt").write_text("synthetic", encoding="utf-8")
            before, _ = scan_path(root)
            after = json.loads(json.dumps(before))
            after["policy_ref"] = "scan-policy://synthetic/other"
            identity_payload = {key: value for key, value in after.items() if key not in {"manifest_id", "tree_digest"}}
            after["manifest_id"] = "manifest://" + hashlib.sha256(canonical_bytes(identity_payload)).hexdigest()
            with self.assertRaises(ValidationFailure) as raised:
                diff_manifests(before, after)
            self.assertEqual(raised.exception.code, "scan-policy-mismatch")

    def test_manifest_semantics_require_normalized_entries_and_parents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "nested").mkdir()
            (root / "nested" / "value.txt").write_text("synthetic", encoding="utf-8")
            manifest, _ = scan_path(root)
            missing_parent = {**manifest, "entries": [manifest["entries"][1]]}
            with self.assertRaises(ValidationFailure) as raised:
                validate_manifest_identity(missing_parent)
            self.assertEqual(raised.exception.code, "manifest-parent-missing")
            missing_content = json.loads(json.dumps(manifest))
            del missing_content["entries"][1]["content_digest"]
            with self.assertRaises(ValidationFailure) as raised:
                validate_manifest_identity(missing_content)
            self.assertEqual(raised.exception.code, "required-field-missing")

            reserved_name = json.loads(json.dumps(manifest))
            reserved_name["entries"][0]["path"] = "CON.txt"
            with self.assertRaises(ValidationFailure) as raised:
                validate_manifest_identity(reserved_name)
            self.assertEqual(raised.exception.code, "constraint-failed")

    def test_manifest_canonicalization_failures_are_typed(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest, _ = scan_path(Path(temporary))
        manifest["extensions"] = {"synthetic": 9_007_199_254_740_992}
        with self.assertRaises(ValidationFailure) as failure:
            validate_manifest_identity(manifest)
        self.assertEqual(failure.exception.code, "canonicalization-failed")

    def test_symlink_is_explicitly_unsupported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "target").write_text("synthetic", encoding="utf-8")
            try:
                (root / "link").symlink_to(root / "target")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable on this platform")
            _, receipt = scan_path(root)
            self.assertEqual(receipt["outcome"], "partial")
            self.assertEqual(receipt["diagnostics"][0]["code"], "unsupported")

    def test_hard_link_is_explicitly_unsupported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            source.write_text("synthetic", encoding="utf-8")
            try:
                os.link(source, root / "alias.txt")
            except OSError:
                self.skipTest("hard links unavailable on this platform")
            manifest, receipt = scan_path(root)
        self.assertEqual(manifest["entries"], [])
        self.assertEqual(receipt["outcome"], "partial")
        self.assertEqual({item["code"] for item in receipt["failures"]}, {"unsupported"})

    def test_sparse_file_observation_is_explicitly_unsupported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "sparse.bin"
            path.write_bytes(b"synthetic")
            observed = os.stat(path, follow_symlinks=False)
            sparse = SimpleNamespace(
                st_mode=observed.st_mode,
                st_dev=observed.st_dev,
                st_ino=observed.st_ino,
                st_size=4096,
                st_mtime_ns=observed.st_mtime_ns,
                st_ctime_ns=observed.st_ctime_ns,
                st_nlink=1,
                st_blocks=0,
            )
            with patch.object(Path, "stat", return_value=sparse):
                with self.assertRaises(scan_module._ObservationFailure) as raised:
                    scan_module._hash_regular_file(path, root)
        self.assertEqual(raised.exception.code, "unsupported")

    def test_symlink_root_is_not_silently_resolved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.mkdir()
            (target / "value.txt").write_text("synthetic", encoding="utf-8")
            link = root / "linked-root"
            try:
                link.symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks unavailable on this platform")
            manifest, receipt = scan_path(link)
            self.assertEqual(manifest["entries"], [])
            self.assertEqual(receipt["outcome"], "failed")
            self.assertEqual(receipt["diagnostics"][0]["code"], "unsupported")

    def test_mocked_windows_reparse_entry_is_rejected_before_hashing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root_metadata = os.lstat(root)
            reparse_metadata = SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_file_attributes=0x400)

            class ReparseEntry:
                name = "junction"
                path = str(root / name)

                @staticmethod
                def stat(*, follow_symlinks):
                    self.assertFalse(follow_symlinks)
                    return reparse_metadata

            class Scandir:
                def __enter__(self):
                    return iter([ReparseEntry()])

                def __exit__(self, *_args):
                    return False

            with (
                patch("artifact_memory.scan.os.lstat", return_value=root_metadata),
                patch("artifact_memory.scan.os.scandir", return_value=Scandir()),
                patch("artifact_memory.scan._hash_regular_file") as hash_file,
            ):
                manifest, receipt = scan_path(root)
            hash_file.assert_not_called()
            self.assertEqual(manifest["entries"], [])
            self.assertEqual(receipt["outcome"], "partial")
            self.assertEqual(receipt["diagnostics"][0]["code"], "unsupported")

    def test_unavailable_root_is_failed_not_partial(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing"
            manifest, receipt = scan_path(missing)
            self.assertEqual(manifest["completeness"], "failed")
            self.assertEqual(receipt["outcome"], "failed")
            self.assertEqual(receipt["diagnostics"][0]["code"], "unreadable")

    def test_casefold_collision_is_explicit_without_platform_dependency(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            walked = iter([(root / "Case.txt", "file"), (root / "case.txt", "file")])
            with (
                patch("artifact_memory.scan._walk", return_value=walked),
                patch("artifact_memory.scan._hash_regular_file", return_value=(9, "sha-256:" + "a" * 64)),
            ):
                manifest, receipt = scan_path(root)
            self.assertEqual(manifest["completeness"], "partial")
            self.assertEqual([entry["path"] for entry in manifest["entries"]], ["Case.txt", "case.txt"])
            self.assertEqual(receipt["diagnostics"][0]["code"], "collision")

    def test_resource_limit_and_cancellation_are_distinct(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "a.txt").write_bytes(b"1234")
            (root / "b.txt").write_bytes(b"5678")
            with patch("artifact_memory.scan._hash_exact_size", wraps=scan_module._hash_exact_size) as hash_stream:
                _, limited = scan_path(root, ScanLimits(max_bytes=4))
            self.assertEqual(limited["outcome"], "partial")
            self.assertEqual(limited["diagnostics"][0]["code"], "resource-limit")
            self.assertEqual([item["code"] for item in limited["warnings"]], ["resource-limit"])
            self.assertEqual(limited["failures"], [])
            self.assertEqual(hash_stream.call_count, 1)
            _, cancelled = scan_path(root, ScanLimits(cancellation_check=lambda: True))
            self.assertEqual(cancelled["outcome"], "cancelled")
            self.assertEqual(cancelled["diagnostics"][0]["code"], "cancelled")
            schema = json.loads((Path(__file__).resolve().parents[1] / "artifact_memory/schemas/core/scan-receipt.v2.schema.json").read_text(encoding="utf-8"))
            validate(limited, schema)
            validate(cancelled, schema)

    def test_oversized_file_is_rejected_before_content_streaming(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "oversized.bin").write_bytes(b"x" * 64)
            with patch("artifact_memory.scan._hash_exact_size", side_effect=AssertionError("content stream must not be read")) as hash_stream:
                manifest, receipt = scan_path(root, ScanLimits(max_bytes=8))
            hash_stream.assert_not_called()
            self.assertEqual(manifest["entries"], [])
            self.assertEqual(receipt["outcome"], "partial")
            self.assertEqual(receipt["diagnostics"][0]["code"], "resource-limit")
            self.assertEqual([item["code"] for item in receipt["warnings"]], ["resource-limit"])
            self.assertEqual(receipt["failures"], [])

    @unittest.skipIf(os.name == "nt", "backslash is a separator rather than a legal filename on Windows")
    def test_nonportable_backslash_filename_is_explicitly_unsupported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "synthetic\\name.txt").write_text("synthetic", encoding="utf-8")
            manifest, receipt = scan_path(root)
            self.assertEqual(manifest["completeness"], "partial")
            self.assertEqual(receipt["diagnostics"][0]["code"], "unsupported")
            self.assertEqual(manifest["entries"], [])

    @unittest.skipIf(os.name == "nt", "backslash is a separator rather than a legal filename on Windows")
    def test_scan_receipt_identity_covers_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "first\\name.txt").write_text("synthetic", encoding="utf-8")
            _, first = scan_path(root)
            (root / "second\\name.txt").write_text("synthetic", encoding="utf-8")
            _, second = scan_path(root)
            self.assertNotEqual(first["receipt_id"], second["receipt_id"])
            self.assertNotEqual(len(first["diagnostics"]), len(second["diagnostics"]))

    def test_entry_limit_bounds_directory_enumeration_before_sorting(self):
        real_scandir = os.scandir

        class CountingScandir:
            def __init__(self, path):
                self._inner = real_scandir(path)
                self.next_calls = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self._inner.close()

            def __iter__(self):
                return self

            def __next__(self):
                self.next_calls += 1
                if self.next_calls > 3:
                    raise AssertionError("directory enumeration exceeded max_entries + 1")
                return next(self._inner)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index in range(20):
                (root / f"{index:02d}.txt").write_text("synthetic", encoding="utf-8")
            wrappers = []

            def bounded_scandir(path):
                wrapper = CountingScandir(path)
                wrappers.append(wrapper)
                return wrapper

            with patch("artifact_memory.scan.os.scandir", side_effect=bounded_scandir):
                manifest, receipt = scan_path(root, ScanLimits(max_entries=2))
            self.assertEqual(receipt["outcome"], "partial")
            self.assertEqual(receipt["diagnostics"][0]["code"], "resource-limit")
            self.assertEqual(manifest["entries"], [])
            self.assertEqual(wrappers[0].next_calls, 3)


if __name__ == "__main__":
    unittest.main()
