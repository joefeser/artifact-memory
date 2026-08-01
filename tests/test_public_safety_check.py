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


if __name__ == "__main__":
    unittest.main()
