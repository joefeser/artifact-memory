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
    def test_sanitized_custody_attestation_renders_exact_public_receipt(self):
        attestation_path = ROOT / public_safety_check.SANITIZED_CUSTODY_ATTESTATION_PATH
        attestation_text = attestation_path.read_text(encoding="utf-8")
        receipt = (ROOT / public_safety_check.SANITIZED_CUSTODY_RECEIPT_PATH).read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            public_safety_check.sanitized_custody_attestation_findings(
                attestation_text
            ),
            [],
        )
        self.assertEqual(public_safety_check.sanitized_custody_receipt_findings(receipt), [])

    def test_sanitized_custody_receipt_rejects_semantic_drift(self):
        receipt = (ROOT / public_safety_check.SANITIZED_CUSTODY_RECEIPT_PATH).read_text(
            encoding="utf-8"
        )
        for original, replacement in (("ten allowlisted", "zero allowlisted"), ("snapshot completed", "snapshot failed")):
            with self.subTest(replacement=replacement):
                findings = public_safety_check.sanitized_custody_receipt_findings(
                    receipt.replace(original, replacement)
                )
                self.assertIn("contract-render-mismatch", findings)

    def test_sanitized_custody_receipt_rejects_unrecognized_prose(self):
        receipt = (ROOT / public_safety_check.SANITIZED_CUSTODY_RECEIPT_PATH).read_text(
            encoding="utf-8"
        )
        findings = public_safety_check.sanitized_custody_receipt_findings(
            receipt + "\nPrivate repository: vault-prod-7\n"
        )
        self.assertIn("contract-render-mismatch", findings)
        self.assertIn("machine-binding-detected", findings)

    def test_sanitized_custody_receipt_rejects_endpoint_alias_suffix(self):
        receipt = (ROOT / public_safety_check.SANITIZED_CUSTODY_RECEIPT_PATH).read_text(
            encoding="utf-8"
        )
        findings = public_safety_check.sanitized_custody_receipt_findings(
            receipt + "\nEndpoint alias: endpoint://joe-home-proxmox-vault-1-nas\n"
        )
        self.assertIn("contract-render-mismatch", findings)
        self.assertIn("machine-binding-detected", findings)

    def test_sanitized_custody_receipt_rejects_private_binding_forms(self):
        receipt = (ROOT / public_safety_check.SANITIZED_CUSTODY_RECEIPT_PATH).read_text(
            encoding="utf-8"
        )
        private_bindings = (
            "https://[fd00::1]/repo",
            "C:/vault",
            r"\\server\share",
            "backup@host:/mnt/repo",
            "backup://vault-1/abc",
            "codex-task://local/job-1",
            "A" * 64,
        )
        for binding in private_bindings:
            with self.subTest(binding=binding):
                findings = public_safety_check.sanitized_custody_receipt_findings(
                    receipt + f"\nObserved private binding: {binding}\n"
                )
                self.assertIn("machine-binding-detected", findings)

    def test_historical_custody_receipt_uses_path_aware_privacy_scan(self):
        receipt = (ROOT / public_safety_check.SANITIZED_CUSTODY_RECEIPT_PATH).read_text(
            encoding="utf-8"
        )
        object_id = "a" * 40
        history = {
            object_id: {public_safety_check.SANITIZED_CUSTODY_RECEIPT_PATH}
        }
        with patch.object(
            public_safety_check,
            "read_blobs",
            return_value={
                object_id: (
                    receipt
                    + "\nEndpoint alias: endpoint://joe-home-proxmox-vault-1-nas\n"
                ).encode()
            },
        ):
            findings = public_safety_check.check_historical_content(history)
        self.assertEqual(
            findings,
            [
                "sanitized custody receipt historical content invalid: "
                f"object {object_id}, unsupported-contract-shape"
            ],
        )

    def test_historical_custody_receipt_allows_legacy_scheme_explanation(self):
        receipt = (
            ROOT
            / "evidence/sanitized/custody/v1/compatibility/markdown-network-clarified-v0.md"
        ).read_text(encoding="utf-8")
        object_id = "b" * 40
        history = {
            object_id: {public_safety_check.SANITIZED_CUSTODY_RECEIPT_PATH}
        }
        with patch.object(
            public_safety_check,
            "read_blobs",
            return_value={object_id: receipt.encode()},
        ):
            findings = public_safety_check.check_historical_content(history)
        self.assertEqual(findings, [])

    def test_historical_custody_receipt_rejects_changed_claim_or_extra_prose(self):
        receipt = (
            ROOT
            / "evidence/sanitized/custody/v1/compatibility/markdown-pre-contract-v0.md"
        ).read_text(encoding="utf-8")
        mutations = (
            receipt.replace(
                "one non-empty snapshot completed",
                "snapshot failed",
            ),
            receipt + "\nUnexpected custody assertion.\n",
        )
        for text in mutations:
            with self.subTest(text_length=len(text)):
                self.assertEqual(
                    public_safety_check._historical_custody_receipt_findings(text),
                    ["unsupported-contract-shape"],
                )

    def test_historical_custody_receipt_allows_crlf(self):
        receipt = (ROOT / public_safety_check.SANITIZED_CUSTODY_RECEIPT_PATH).read_text(
            encoding="utf-8"
        ).replace("\n", "\r\n")
        object_id = "c" * 40
        history = {
            object_id: {public_safety_check.SANITIZED_CUSTODY_RECEIPT_PATH}
        }
        with patch.object(
            public_safety_check,
            "read_blobs",
            return_value={object_id: receipt.encode()},
        ):
            findings = public_safety_check.check_historical_content(history)
        self.assertEqual(findings, [])

    def test_sanitized_custody_attestation_rejects_duplicate_keys(self):
        attestation = (ROOT / public_safety_check.SANITIZED_CUSTODY_ATTESTATION_PATH).read_text(
            encoding="utf-8"
        )
        duplicate = attestation.replace(
            '  "transport_profile":',
            '  "transport_profile": "backup@private-host:/srv/repo",\n'
            '  "transport_profile":',
        )
        self.assertEqual(
            public_safety_check.sanitized_custody_attestation_findings(duplicate),
            ["contract-invalid"],
        )

    def test_historical_custody_attestation_dispatches_known_versions(self):
        paths = (
            ROOT / "evidence/sanitized/custody/v1/compatibility/pre-provenance-v1.json",
            ROOT / "evidence/sanitized/custody/v1/compatibility/provenance-v1.json",
            ROOT / public_safety_check.SANITIZED_CUSTODY_ATTESTATION_PATH,
        )
        for path in paths:
            with self.subTest(path=path.name):
                self.assertEqual(
                    public_safety_check._custody_compatibility_attestation_findings(
                        path.read_text(encoding="utf-8")
                    ),
                    [],
                )

    def test_historical_custody_attestation_rejects_duplicate_keys(self):
        text = (ROOT / public_safety_check.SANITIZED_CUSTODY_ATTESTATION_PATH).read_text(
            encoding="utf-8"
        ).replace(
            '  "transport_profile":',
            '  "transport_profile": "backup@private-host:/srv/repo",\n'
            '  "transport_profile":',
        )
        object_id = "d" * 40
        history = {
            object_id: {public_safety_check.SANITIZED_CUSTODY_ATTESTATION_PATH}
        }
        with patch.object(
            public_safety_check,
            "read_blobs",
            return_value={object_id: text.encode()},
        ):
            findings = public_safety_check.check_historical_content(history)
        self.assertEqual(
            findings,
            [
                "sanitized custody attestation historical content invalid: "
                f"object {object_id}, path "
                f"{public_safety_check.SANITIZED_CUSTODY_ATTESTATION_PATH}, "
                "contract-invalid"
            ],
        )

    def test_current_compatibility_attestation_rejects_duplicate_keys(self):
        path = next(iter(sorted(public_safety_check.SANITIZED_CUSTODY_COMPATIBILITY_PATHS)))
        text = (ROOT / path).read_text(encoding="utf-8").replace(
            '  "transport_profile":',
            '  "transport_profile": "backup@private-host:/srv/repo",\n'
            '  "transport_profile":',
        )
        with (
            patch.object(public_safety_check, "staged_objects", return_value={}),
            patch.object(Path, "read_bytes", return_value=text.encode()),
        ):
            findings = public_safety_check.check_current_content([path])
        self.assertEqual(
            findings,
            ["sanitized custody compatibility attestation invalid: contract-invalid"],
        )

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
    def test_raw_history_preserves_every_blob_path_association(self):
        malicious = (
            ROOT / public_safety_check.SANITIZED_CUSTODY_RECEIPT_PATH
        ).read_text(encoding="utf-8").replace(
            "one non-empty snapshot completed",
            "snapshot failed",
        )
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            subprocess.run(
                ["git", "init", "-b", "main"],
                cwd=repo,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Synthetic Fixture"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "fixture@example.invalid"],
                cwd=repo,
                check=True,
            )
            shared = repo / "shared.md"
            shared.write_text(malicious, encoding="utf-8")
            subprocess.run(
                ["git", "add", "shared.md"], cwd=repo, check=True
            )
            subprocess.run(
                ["git", "commit", "-m", "Add shared blob"],
                cwd=repo,
                check=True,
                capture_output=True,
            )
            receipt = repo / public_safety_check.SANITIZED_CUSTODY_RECEIPT_PATH
            receipt.parent.mkdir(parents=True)
            receipt.write_text(malicious, encoding="utf-8")
            subprocess.run(
                ["git", "add", public_safety_check.SANITIZED_CUSTODY_RECEIPT_PATH],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "Reuse blob as receipt"],
                cwd=repo,
                check=True,
                capture_output=True,
            )
            receipt.unlink()
            subprocess.run(
                ["git", "add", "-u"], cwd=repo, check=True
            )
            subprocess.run(
                ["git", "commit", "-m", "Remove receipt path"],
                cwd=repo,
                check=True,
                capture_output=True,
            )
            blob = subprocess.check_output(
                ["git", "hash-object", "shared.md"],
                cwd=repo,
                text=True,
            ).strip()
            previous = Path.cwd()
            os.chdir(repo)
            try:
                history = public_safety_check.history_entries(["HEAD"])
                findings = public_safety_check.check_historical_content(history)
            finally:
                os.chdir(previous)
        self.assertEqual(
            history[blob],
            {"shared.md", public_safety_check.SANITIZED_CUSTODY_RECEIPT_PATH},
        )
        self.assertIn(
            "sanitized custody receipt historical content invalid: "
            f"object {blob}, unsupported-contract-shape",
            findings,
        )

    def test_public_refs_excludes_only_remote_head_and_keeps_head_tag(self):
        output = (
            "refs/remotes/origin/HEAD\t" + "a" * 40 + "\n"
            "refs/tags/HEAD\t" + "b" * 40 + "\n"
        )
        with patch.object(
            public_safety_check.subprocess,
            "check_output",
            return_value=output,
        ):
            refs = public_safety_check.public_refs()
        self.assertEqual(
            refs,
            [{"ref": "refs/tags/HEAD", "object_id": "b" * 40}],
        )

    def test_public_refs_rejects_malformed_records_before_git_scan(self):
        for output in (
            "malformed-record\n",
            "refs/tags/synthetic\tnot-an-object-id\n",
            "not-a-public-ref\t" + "a" * 40 + "\n",
        ):
            with self.subTest(output=output):
                with patch.object(
                    public_safety_check.subprocess,
                    "check_output",
                    return_value=output,
                ):
                    with self.assertRaises(
                        public_safety_check.PublicSafetyInvalidGitOutput
                    ):
                        public_safety_check.public_refs()

    def test_public_refs_validates_remote_head_before_excluding_it(self):
        with patch.object(
            public_safety_check.subprocess,
            "check_output",
            return_value="refs/remotes/origin/HEAD\tbad\n",
        ):
            with self.assertRaises(public_safety_check.PublicSafetyInvalidGitOutput):
                public_safety_check.public_refs()

    def test_public_refs_rejects_protected_names_before_receipt_use(self):
        for ref in (
            "refs/remotes/origin/private/vault",
            "refs/tags/" + "sk" + "-" + "a" * 16,
        ):
            with self.subTest(ref=ref):
                with patch.object(
                    public_safety_check.subprocess,
                    "check_output",
                    return_value=f"{ref}\t{'a' * 40}\n",
                ):
                    with self.assertRaisesRegex(
                        public_safety_check.PublicSafetyInvalidGitOutput,
                        "violates public-safety policy",
                    ):
                        public_safety_check.public_refs()

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

    def test_real_git_audit_rejects_forbidden_name_after_same_blob_rename(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Synthetic Fixture"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=repo, check=True)
            (repo / ".env").write_text("synthetic public fixture\n", encoding="utf-8")
            subprocess.run(["git", "add", ".env"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "Add synthetic old name"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "mv", ".env", "public.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "Rename synthetic path"], cwd=repo, check=True, capture_output=True)
            candidate = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()

            result = subprocess.run(
                [sys.executable, str(MODULE_PATH), "--candidate", candidate],
                cwd=repo,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("forbidden repository path: .env", result.stderr)

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

    def test_receipt_accepts_an_empty_current_tree(self):
        candidate = "a" * 40
        with (
            patch.object(public_safety_check, "head_commit", return_value=candidate),
            patch.object(public_safety_check, "worktree_is_clean", return_value=True),
            patch.object(public_safety_check, "public_refs", return_value=[]),
            patch.object(
                public_safety_check,
                "scan",
                return_value=({candidate: set()}, [], []),
            ),
            patch.object(public_safety_check, "commits", return_value=[candidate]),
        ):
            receipt, findings = public_safety_check.exact_candidate_receipt(candidate)
        self.assertEqual(findings, [])
        self.assertEqual(receipt["current_path_count"], 0)

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
            patch.object(public_safety_check, "commits", return_value=[candidate]),
        ):
            with self.assertRaisesRegex(ValueError, "public refs changed"):
                public_safety_check.exact_candidate_receipt(candidate)

    def test_external_receipt_write_rejects_repository_hard_link(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repo"
            repository.mkdir()
            tracked = repository / "tracked.txt"
            tracked.write_text("synthetic\n", encoding="utf-8")
            destination = root / "receipt.json"
            destination.hardlink_to(tracked)
            with patch.object(
                public_safety_check,
                "repository_root",
                return_value=repository,
            ):
                with self.assertRaisesRegex(ValueError, "share a repository file inode"):
                    public_safety_check.write_external_receipt(destination, "{}\n")
            self.assertEqual(tracked.read_text(encoding="utf-8"), "synthetic\n")

    def test_external_receipt_write_atomically_replaces_regular_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repo"
            repository.mkdir()
            destination = root / "receipt.json"
            destination.write_text("old\n", encoding="utf-8")
            with patch.object(
                public_safety_check,
                "repository_root",
                return_value=repository,
            ):
                public_safety_check.write_external_receipt(destination, "new\n")
            self.assertEqual(destination.read_text(encoding="utf-8"), "new\n")

    def test_cli_normalizes_rejected_external_receipt_destination(self):
        with (
            patch.object(
                public_safety_check,
                "exact_candidate_receipt",
                return_value=({"outcome": "pass"}, []),
            ),
            patch.object(public_safety_check, "require_external_path"),
            patch.object(
                public_safety_check,
                "write_external_receipt",
                side_effect=ValueError("receipt output must not be a symbolic link"),
            ),
            patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            result = public_safety_check.main(
                ["--candidate", "a" * 40, "--receipt-out", "/external/receipt.json"]
            )
        self.assertEqual(result, 1)
        self.assertIn("PUBLIC SAFETY CHECK FAILED", stderr.getvalue())
        self.assertIn("must not be a symbolic link", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
