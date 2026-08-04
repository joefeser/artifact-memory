import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "public_safety_check.py"
SPEC = importlib.util.spec_from_file_location("public_safety_check", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
public_safety_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(public_safety_check)


class PublicSafetyCurrentContentTests(unittest.TestCase):
    def test_unstaged_worktree_content_is_scanned_when_index_is_clean(self):
        marker = ("pass" + "word") + "=synthetic-sensitive-value"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tracked.txt"
            path.write_text(marker, encoding="utf-8")
            previous = Path.cwd()
            os.chdir(temporary)
            try:
                with (
                    patch.object(public_safety_check, "staged_objects", return_value={"tracked.txt": "index"}),
                    patch.object(public_safety_check, "read_blobs", return_value={"index": b"safe"}),
                ):
                    findings = public_safety_check.check_current_content(["tracked.txt"])
            finally:
                os.chdir(previous)
        self.assertEqual(findings, ["secret-like current content: path tracked.txt"])

    def test_staged_content_is_scanned_when_worktree_is_clean(self):
        marker = (("pass" + "word") + "=synthetic-sensitive-value").encode()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tracked.txt"
            path.write_text("safe", encoding="utf-8")
            previous = Path.cwd()
            os.chdir(temporary)
            try:
                with (
                    patch.object(public_safety_check, "staged_objects", return_value={"tracked.txt": "index"}),
                    patch.object(public_safety_check, "read_blobs", return_value={"index": marker}),
                ):
                    findings = public_safety_check.check_current_content(["tracked.txt"])
            finally:
                os.chdir(previous)
        self.assertEqual(findings, ["secret-like current content: path tracked.txt"])

    def test_staged_content_is_scanned_when_worktree_read_fails(self):
        marker = (("pass" + "word") + "=synthetic-sensitive-value").encode()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tracked.txt"
            path.write_text("safe", encoding="utf-8")
            previous = Path.cwd()
            os.chdir(temporary)
            try:
                with (
                    patch.object(public_safety_check, "staged_objects", return_value={"tracked.txt": "index"}),
                    patch.object(public_safety_check, "read_blobs", return_value={"index": marker}),
                    patch.object(Path, "read_bytes", side_effect=OSError("synthetic read failure")),
                ):
                    findings = public_safety_check.check_current_content(["tracked.txt"])
            finally:
                os.chdir(previous)
        self.assertEqual(
            findings,
            [
                "current content scan failed: tracked.txt (synthetic read failure)",
                "secret-like current content: path tracked.txt",
            ],
        )


class PublicSafetyCandidateReceiptTests(unittest.TestCase):
    def test_receipt_paths_must_be_external_to_repository(self):
        with patch.object(public_safety_check, "repository_root", return_value=Path("/repo")):
            with self.assertRaisesRegex(ValueError, "outside the audited repository"):
                public_safety_check.require_external_path(Path("/repo/audit/receipt.json"), "receipt output")

    def test_receipt_binds_candidate_refs_counts_and_clean_scope(self):
        candidate = "a" * 40
        refs = [{"ref": "refs/remotes/origin/dev", "object_id": "b" * 40}]
        with (
            patch.object(public_safety_check, "head_commit", return_value=candidate),
            patch.object(public_safety_check, "worktree_is_clean", return_value=True),
            patch.object(public_safety_check, "public_refs", return_value=refs),
            patch.object(
                public_safety_check,
                "scan",
                return_value=({"object": {"tracked.txt"}}, ["tracked.txt"], []),
            ),
            patch.object(public_safety_check, "commits", return_value=[candidate]),
        ):
            receipt, findings = public_safety_check.exact_candidate_receipt(candidate)
        self.assertEqual(findings, [])
        self.assertEqual(receipt["candidate_commit"], candidate)
        self.assertEqual(receipt["head_commit"], candidate)
        self.assertEqual(receipt["scanned_refs"], refs)
        self.assertEqual(receipt["commit_count"], 1)
        self.assertEqual(receipt["historical_object_count"], 1)
        self.assertEqual(receipt["current_path_count"], 1)
        self.assertTrue(receipt["worktree_clean"])
        self.assertRegex(receipt["receipt_id"], r"^public-safety-receipt://[0-9a-f]{64}$")

    def test_receipt_rejects_cross_candidate_head(self):
        with patch.object(public_safety_check, "head_commit", return_value="b" * 40):
            with self.assertRaisesRegex(ValueError, "HEAD does not equal"):
                public_safety_check.exact_candidate_receipt("a" * 40)

    def test_receipt_rejects_dirty_worktree(self):
        candidate = "a" * 40
        with (
            patch.object(public_safety_check, "head_commit", return_value=candidate),
            patch.object(public_safety_check, "worktree_is_clean", return_value=False),
        ):
            with self.assertRaisesRegex(ValueError, "clean index and worktree"):
                public_safety_check.exact_candidate_receipt(candidate)


if __name__ == "__main__":
    unittest.main()
