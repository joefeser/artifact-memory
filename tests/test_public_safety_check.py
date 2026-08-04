import importlib.util
import io
import json
import os
import subprocess
import sys
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
    def test_checked_synthetic_receipt_and_human_rendering(self):
        fixture = ROOT / "fixtures/synthetic/public-safety/v1"
        receipt = json.loads((fixture / "expected-receipt.json").read_text(encoding="utf-8"))
        public_safety_check.validate(
            receipt,
            public_safety_check.load_schema("core", "public-safety-receipt.v1.schema.json"),
        )
        body = {key: value for key, value in receipt.items() if key not in {"schema_id", "receipt_id"}}
        self.assertEqual(
            public_safety_check.receipt_with_digest(
                public_safety_check.RECEIPT_SCHEMA_ID,
                public_safety_check.RECEIPT_ID_PREFIX,
                body,
            ),
            receipt,
        )
        self.assertEqual(
            public_safety_check.render_candidate_receipt(receipt),
            (fixture / "receipt.md").read_text(encoding="utf-8"),
        )

    def test_real_git_cli_generates_replays_and_renders_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Synthetic Fixture"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=repo, check=True)
            (repo / "synthetic.txt").write_text("newly authored synthetic public fixture\n", encoding="utf-8")
            subprocess.run(["git", "add", "synthetic.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "Synthetic fixture"], cwd=repo, check=True, capture_output=True)
            candidate = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            receipt_path = root / "receipt.json"

            generated = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--candidate",
                    candidate,
                    "--receipt-out",
                    str(receipt_path),
                ],
                cwd=repo,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertIn(receipt["receipt_id"], generated.stdout)
            self.assertIn("- Reachable commits: 1", generated.stdout)
            self.assertIn("- Current paths: 1", generated.stdout)
            public_safety_check.validate(
                receipt,
                public_safety_check.load_schema("core", "public-safety-receipt.v1.schema.json"),
            )

            replay = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--candidate",
                    candidate,
                    "--expect-receipt",
                    str(receipt_path),
                    "--json",
                ],
                cwd=repo,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(replay.returncode, 0, replay.stderr)
            self.assertEqual(json.loads(replay.stdout), receipt)

            tampered_path = root / "tampered-receipt.json"
            tampered = dict(receipt)
            tampered["current_path_count"] = receipt["current_path_count"] + 1
            tampered_path.write_text(json.dumps(tampered), encoding="utf-8")
            rejected = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--candidate",
                    candidate,
                    "--expect-receipt",
                    str(tampered_path),
                ],
                cwd=repo,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("canonical identity does not match", rejected.stderr)

            inside = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--candidate",
                    candidate,
                    "--receipt-out",
                    str(repo / "receipt.json"),
                ],
                cwd=repo,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(inside.returncode, 1)
            self.assertIn("outside the audited repository", inside.stderr)

            marker = ("pass" + "word") + "=synthetic-tag-message"
            subprocess.run(
                ["git", "tag", "-a", "synthetic-v1", "-m", marker],
                cwd=repo,
                check=True,
                capture_output=True,
            )
            tagged = subprocess.run(
                [sys.executable, str(MODULE_PATH), "--candidate", candidate],
                cwd=repo,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(tagged.returncode, 1)
            self.assertIn("secret-like revision metadata: tag object", tagged.stderr)
            self.assertNotIn("synthetic-tag-message", tagged.stderr)

    def test_cli_normalizes_git_failures_without_traceback(self):
        with (
            patch.object(
                public_safety_check,
                "exact_candidate_receipt",
                side_effect=subprocess.CalledProcessError(1, ["git", "synthetic"]),
            ),
            patch.object(public_safety_check, "require_external_path"),
            patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            result = public_safety_check.main(["--candidate", "a" * 40])
        self.assertEqual(result, 1)
        self.assertIn("Git audit command failed", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

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

    def test_receipt_rechecks_candidate_state_after_scan(self):
        candidate = "a" * 40
        refs = [{"ref": "refs/remotes/origin/dev", "object_id": "b" * 40}]
        changed_refs = [{"ref": "refs/remotes/origin/dev", "object_id": "c" * 40}]
        with (
            patch.object(public_safety_check, "head_commit", return_value=candidate),
            patch.object(public_safety_check, "worktree_is_clean", return_value=True),
            patch.object(public_safety_check, "public_refs", side_effect=[refs, changed_refs]),
            patch.object(
                public_safety_check,
                "scan",
                return_value=({"object": {"tracked.txt"}}, ["tracked.txt"], []),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "public refs changed"):
                public_safety_check.exact_candidate_receipt(candidate)


if __name__ == "__main__":
    unittest.main()
