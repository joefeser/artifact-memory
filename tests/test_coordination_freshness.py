import contextlib
import copy
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from artifact_memory.cli import main
from artifact_memory.coordination import (
    FRESHNESS_EXTENSION_ID,
    revision_digest,
)
from artifact_memory.coordination_freshness import evaluate_coordination_freshness
from artifact_memory.coordination_kickoff import (
    FRESH_KICKOFF_PACK_SCHEMA_ID,
    KICKOFF_PACK_SCHEMA_ID,
    build_kickoff_pack,
    render_kickoff_prompt,
    validate_kickoff_pack,
)
from artifact_memory.coordination_onboarding import onboard_project
from artifact_memory.coordination_sync import (
    configure_local_hub,
    pull,
    store_coordination_record,
)
from artifact_memory.schema_resources import core_schemas
from artifact_memory.repo_identity import compare_commit_to_head
from artifact_memory.validator import ValidationFailure, load_json


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "coordination"
PROJECT_ID = "11111111-1111-4111-8111-111111111111"
HUB_ID = "coordination-hub://synthetic/freshness"
SESSION_ID = "coordination-session://synthetic/freshness"
PRINCIPAL_ID = "coordination-principal://synthetic/freshness"


class CoordinationFreshnessTests(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return completed.stdout.strip()

    def commit(self, repo: Path, message: str, timestamp: str) -> str:
        environment = os.environ.copy()
        environment["GIT_AUTHOR_DATE"] = timestamp
        environment["GIT_COMMITTER_DATE"] = timestamp
        subprocess.run(
            ["git", "commit", "-q", "-m", message],
            cwd=repo,
            env=environment,
            check=True,
        )
        return self.git(repo, "rev-parse", "HEAD")

    def setup_plane(self, root: Path) -> tuple[Path, Path, Path, dict]:
        repo, vault, hub = root / "repo", root / "vault", root / "hub"
        repo.mkdir()
        self.git(repo, "init", "-q", "-b", "main")
        self.git(repo, "config", "user.name", "Synthetic Fixture")
        self.git(repo, "config", "user.email", "fixture@example.invalid")
        label = copy.deepcopy(load_json(FIXTURES / "access-label.json"))
        label["projectNames"] = [
            {"projectId": PROJECT_ID, "projectName": "synthetic-service"}
        ]
        for field in label["may"]:
            label["may"][field] = [PROJECT_ID]
        label["mayNot"]["readProjects"] = []
        configure_local_hub(
            hub,
            hub_id=HUB_ID,
            scope_generation=11,
            bindings=[
                {
                    "session_id": SESSION_ID,
                    "principal_id": PRINCIPAL_ID,
                    "access_label": label,
                }
            ],
        )
        onboard_project(
            repo,
            vault,
            hub,
            session_id=SESSION_ID,
            completed_at="2026-09-27T15:00:00Z",
            human_name="synthetic-service",
        )
        self.git(repo, "add", ".agent-memory/repo.json")
        self.commit(repo, "Add synthetic identity", "2026-09-27T15:01:00Z")
        return repo, vault, hub, label

    def divergent_commits(self, repo: Path) -> tuple[str, str]:
        self.git(repo, "switch", "-q", "-c", "synthetic-stale")
        (repo / "stale.txt").write_text("synthetic stale branch\n", encoding="utf-8")
        self.git(repo, "add", "stale.txt")
        stale = self.commit(repo, "Synthetic stale branch", "2026-09-27T15:02:00Z")
        self.git(repo, "switch", "-q", "main")
        (repo / "current.txt").write_text("synthetic current branch\n", encoding="utf-8")
        self.git(repo, "add", "current.txt")
        head = self.commit(repo, "Synthetic current head", "2026-09-27T15:03:00Z")
        return stale, head

    def task(self, label: dict, ordinal: int, commit: str) -> dict:
        task = copy.deepcopy(load_json(FIXTURES / "task-open.json"))
        task_id = "task_01J0000000000000000000000" + str(ordinal)
        task["taskId"] = task_id
        task["record_id"] = (
            f"record://coordination/{task['originId']}/task/{task_id}"
        )
        task["projectId"] = PROJECT_ID
        task["projectName"] = "synthetic-service"
        task["assignedWriter"] = PRINCIPAL_ID
        task["accessLabelRef"] = {
            "record_id": label["record_id"],
            "revision_digest": revision_digest(label),
        }
        task["extensions"][FRESHNESS_EXTENSION_ID]["value"][
            "trueAsOfCommit"
        ] = commit
        task["extensions"]["https://synthetic.example/extensions/opaque"] = {
            "version": "v1",
            "required": False,
            "value": {"opaque": ["synthetic", 1, True]},
        }
        return task

    def test_repo_bound_pack_marks_divergent_and_ancestor_commits(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo, vault, hub, label = self.setup_plane(Path(temporary).resolve())
            stale, head = self.divergent_commits(repo)
            stale_task = self.task(label, 3, stale)
            before = copy.deepcopy(stale_task["extensions"])
            store_coordination_record(hub, stale_task)
            pull(
                vault,
                hub,
                session_id=SESSION_ID,
                completed_at="2026-09-27T15:04:00Z",
            )

            opaque_pack = build_kickoff_pack(vault, PROJECT_ID)
            self.assertEqual(opaque_pack["schema_id"], KICKOFF_PACK_SCHEMA_ID)
            self.assertNotIn(
                "freshness", opaque_pack["queue"]["selected_task"]
            )

            stale_pack = build_kickoff_pack(
                vault, PROJECT_ID, repo_root=repo
            )
            validate_kickoff_pack(stale_pack)
            stale_freshness = stale_pack["queue"]["selected_task"]["freshness"]
            self.assertEqual(stale_pack["schema_id"], FRESH_KICKOFF_PACK_SCHEMA_ID)
            self.assertEqual(stale_freshness["status"], "stale-verify")
            self.assertEqual(stale_freshness["true_as_of_commit"], stale)
            self.assertEqual(stale_freshness["observed_head"], head)
            self.assertEqual(stale_task["extensions"], before)
            self.assertIn("Repository freshness: `stale-verify`", render_kickoff_prompt(stale_pack))

            current_task = self.task(label, 5, head)
            store_coordination_record(hub, current_task)
            pull(
                vault,
                hub,
                session_id=SESSION_ID,
                completed_at="2026-09-27T15:05:00Z",
            )
            current_pack = build_kickoff_pack(
                vault, PROJECT_ID, repo_root=repo
            )
            self.assertEqual(
                current_pack["queue"]["selected_task"]["freshness"]["status"],
                "current",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(
                    [
                        "kickoff",
                        "--project",
                        PROJECT_ID,
                        "--vault",
                        str(vault),
                        "--repo",
                        str(repo),
                        "--json",
                    ]
                )
            self.assertEqual(exit_code, 0)
            emitted = json.loads(stdout.getvalue())
            self.assertEqual(
                emitted["queue"]["selected_task"]["freshness"]["status"],
                "current",
            )

    def test_unavailable_and_wrong_format_commits_fail_typed(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo, _, _, _ = self.setup_plane(Path(temporary).resolve())
            with self.assertRaises(ValidationFailure) as raised:
                compare_commit_to_head(repo, "0" * 40)
            self.assertEqual(
                raised.exception.code,
                "coordination-freshness-commit-unavailable",
            )

            with self.assertRaises(ValidationFailure) as raised:
                compare_commit_to_head(repo, "0" * 64)
            self.assertEqual(
                raised.exception.code,
                "coordination-freshness-object-format-mismatch",
            )

    def test_unknown_required_and_top_level_freshness_fail_closed(self):
        label = copy.deepcopy(load_json(FIXTURES / "access-label.json"))
        task = self.task(label, 3, "a" * 40)
        required = copy.deepcopy(task)
        required["extensions"]["https://synthetic.example/extensions/required"] = {
            "version": "v1",
            "required": True,
            "value": {},
        }
        with self.assertRaises(ValidationFailure) as raised:
            evaluate_coordination_freshness(required, Path.cwd())
        self.assertEqual(raised.exception.code, "required-extension-unsupported")

        top_level = copy.deepcopy(task)
        top_level["trueAsOfCommit"] = "a" * 40
        with self.assertRaises(ValidationFailure) as raised:
            evaluate_coordination_freshness(top_level, Path.cwd())
        self.assertEqual(raised.exception.code, "unknown-field")

    def test_fresh_pack_schema_is_packaged(self):
        self.assertIn(FRESH_KICKOFF_PACK_SCHEMA_ID, core_schemas())


if __name__ == "__main__":
    unittest.main()
