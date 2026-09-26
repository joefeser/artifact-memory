import copy
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from artifact_memory.coordination import revision_digest
from artifact_memory.repo_identity import (
    _is_link_or_reparse,
    create_repo_identity_manifest,
    load_repo_identity,
    load_repo_identity_candidate,
    load_repo_identity_registry,
    validate_repo_bound_coordination_records,
)
from artifact_memory.validator import ValidationFailure, load_json


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "coordination-repo-identity" / "v0"
COORDINATION = ROOT / "fixtures" / "coordination"


class RepoIdentityTests(unittest.TestCase):
    def write_manifest(self, root: Path, candidate: dict) -> None:
        manifest_dir = root / ".agent-memory"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "repo.json").write_text(
            json.dumps(candidate), encoding="utf-8"
        )

    def commit_repository(
        self, root: Path, message: str = "Synthetic identity"
    ) -> None:
        if not (root / ".git").exists():
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.name", "Synthetic Fixture"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "fixture@example.invalid"],
                cwd=root,
                check=True,
            )
        subprocess.run(
            ["git", "add", ".agent-memory/repo.json"], cwd=root, check=True
        )
        subprocess.run(
            ["git", "commit", "-q", "-m", message], cwd=root, check=True
        )

    def write_committed_manifest(self, root: Path, candidate: dict) -> None:
        self.write_manifest(root, candidate)
        self.commit_repository(root)

    def fixture_repository(self, root: Path, name: str) -> Path:
        candidate = load_json(
            FIXTURE / "repositories" / name / ".agent-memory" / "repo.json"
        )
        self.write_committed_manifest(root, candidate)
        return root

    def test_repository_manifest_is_strict_and_public(self):
        identity = load_repo_identity(ROOT)
        self.assertEqual(identity["humanName"], "artifact-memory")
        self.assertEqual(
            identity["uuid"], "6f2d78a4-c0e5-4fa2-a9ce-2c4f760c5a31"
        )

    def test_manifest_creation_is_no_overwrite_and_commit_separate(self):
        candidate = {
            "uuid": "11111111-1111-4111-8111-111111111111",
            "humanName": "synthetic",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "repository"
            root.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            self.assertEqual(create_repo_identity_manifest(root, candidate), "created")
            self.assertEqual(load_repo_identity_candidate(root), candidate)
            with self.assertRaises(ValidationFailure) as uncommitted:
                load_repo_identity(root)
            self.assertEqual(uncommitted.exception.code, "repo-identity-uncommitted")
            self.assertEqual(create_repo_identity_manifest(root, candidate), "existing")
            with self.assertRaises(ValidationFailure) as collision:
                create_repo_identity_manifest(
                    root,
                    {**candidate, "uuid": "22222222-2222-4222-8222-222222222222"},
                )
            self.assertEqual(collision.exception.code, "repo-identity-collision")

    def test_manifest_creation_portable_fallback_writes_one_valid_candidate(self):
        candidate = {
            "uuid": "11111111-1111-4111-8111-111111111111",
            "humanName": "synthetic",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "repository"
            root.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            with mock.patch.object(os, "supports_dir_fd", set()):
                self.assertEqual(
                    create_repo_identity_manifest(root, candidate), "created"
                )
                self.assertEqual(load_repo_identity_candidate(root), candidate)
            expected = json.dumps(candidate, sort_keys=True, indent=2) + "\n"
            self.assertEqual(
                (root / ".agent-memory" / "repo.json").read_text(
                    encoding="utf-8"
                ),
                expected,
            )

    def test_same_human_name_with_different_uuids_is_unambiguous(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            roots = [
                self.fixture_repository(base / "alpha", "alpha"),
                self.fixture_repository(base / "beta", "beta"),
            ]
            registry = load_repo_identity_registry(roots)
        self.assertEqual(len(registry["known_project_ids"]), 2)
        self.assertEqual(len(set(registry["human_names"])), 1)

    def test_unknown_project_uuid_fails_typed(self):
        label = load_json(COORDINATION / "access-label.json")
        task = load_json(COORDINATION / "task-open.json")
        unknown = "99999999-9999-4999-8999-999999999999"
        label["projectNames"][0]["projectId"] = unknown
        for field in label["may"]:
            label["may"][field] = [unknown]
        label["mayNot"]["readProjects"] = []
        task["projectId"] = unknown
        task["accessLabelRef"]["revision_digest"] = revision_digest(label)
        with tempfile.TemporaryDirectory() as temporary:
            root = self.fixture_repository(
                Path(temporary).resolve() / "beta", "beta"
            )
            with self.assertRaises(ValidationFailure) as caught:
                validate_repo_bound_coordination_records([label, task], [root])
        self.assertEqual(caught.exception.code, "coordination-project-unknown")
        self.assertEqual(caught.exception.path, "$.records[0].projectNames[0].projectId")

    def test_human_name_rename_changes_no_record_digest(self):
        task = load_json(COORDINATION / "task-open.json")
        before = revision_digest(task)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            manifest = {
                "uuid": task["projectId"],
                "humanName": task["projectName"],
            }
            self.write_committed_manifest(root, manifest)
            manifest_path = root / ".agent-memory" / "repo.json"
            first = load_repo_identity(root)
            manifest["humanName"] = "renamed-display-only"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValidationFailure) as caught:
                load_repo_identity(root)
            self.assertEqual(caught.exception.code, "repo-identity-uncommitted")
            self.commit_repository(root, "Rename synthetic identity")
            second = load_repo_identity(root)
        self.assertEqual(first["uuid"], second["uuid"])
        self.assertNotEqual(first["humanName"], second["humanName"])
        self.assertEqual(revision_digest(task), before)

    def test_manifest_rejects_extra_fields_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            manifest_dir = root / ".agent-memory"
            manifest_dir.mkdir()
            target = root / "identity.json"
            target.write_text(
                json.dumps(
                    {
                        "uuid": "11111111-1111-4111-8111-111111111111",
                        "humanName": "synthetic",
                    }
                ),
                encoding="utf-8",
            )
            (manifest_dir / "repo.json").symlink_to(target)
            with self.assertRaises(ValidationFailure) as caught:
                load_repo_identity(root)
            self.assertEqual(caught.exception.code, "repo-identity-unsafe")

            (manifest_dir / "repo.json").unlink()
            invalid = copy.deepcopy(json.loads(target.read_text(encoding="utf-8")))
            invalid["path"] = "/private/synthetic"
            (manifest_dir / "repo.json").write_text(
                json.dumps(invalid), encoding="utf-8"
            )
            self.commit_repository(root)
            with self.assertRaises(ValidationFailure) as caught:
                load_repo_identity(root)
            self.assertEqual(caught.exception.code, "unknown-field")

    def test_manifest_schema_constraints_fail_closed(self):
        invalid_candidates = (
            (
                {
                    "uuid": "not-a-uuid",
                    "humanName": "synthetic",
                },
                "constraint-failed",
                "$.uuid",
            ),
            (
                {"humanName": "synthetic"},
                "required-field-missing",
                "$",
            ),
            (
                {
                    "uuid": "11111111-1111-4111-8111-111111111111",
                    "humanName": "",
                },
                "constraint-failed",
                "$.humanName",
            ),
        )
        for candidate, code, path in invalid_candidates:
            with (
                self.subTest(code=code, path=path),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary).resolve()
                self.write_committed_manifest(root, candidate)
                with self.assertRaises(ValidationFailure) as caught:
                    load_repo_identity(root)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.path, path)

    def test_manifest_rejects_symlinked_root_and_identity_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            real_root = base / "real-root"
            self.write_manifest(
                real_root,
                {
                    "uuid": "11111111-1111-4111-8111-111111111111",
                    "humanName": "synthetic",
                },
            )
            linked_root = base / "linked-root"
            linked_root.symlink_to(real_root, target_is_directory=True)
            with self.assertRaises(ValidationFailure) as caught:
                load_repo_identity(linked_root)
            self.assertEqual(caught.exception.code, "repo-identity-unsafe")

            outside = base / "outside-identity"
            outside.mkdir()
            (outside / "repo.json").write_text(
                json.dumps(
                    {
                        "uuid": "22222222-2222-4222-8222-222222222222",
                        "humanName": "external-synthetic",
                    }
                ),
                encoding="utf-8",
            )
            local_root = base / "local-root"
            local_root.mkdir()
            (local_root / ".agent-memory").symlink_to(
                outside, target_is_directory=True
            )
            with self.assertRaises(ValidationFailure) as caught:
                load_repo_identity(local_root)
            self.assertEqual(caught.exception.code, "repo-identity-unsafe")

    def test_manifest_rejects_symlinked_ancestor_component(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            target_parent = base / "target-parent"
            real_root = target_parent / "repository"
            self.write_manifest(
                real_root,
                {
                    "uuid": "11111111-1111-4111-8111-111111111111",
                    "humanName": "synthetic",
                },
            )
            ancestor_alias = base / "ancestor-alias"
            ancestor_alias.symlink_to(target_parent, target_is_directory=True)
            with self.assertRaises(ValidationFailure) as caught:
                load_repo_identity(ancestor_alias / "repository")
            self.assertEqual(caught.exception.code, "repo-identity-unsafe")

    def test_manifest_rejects_parent_traversal_before_normalization(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            safe_root = base / "safe" / "repository"
            external_root = base / "external" / "repository"
            for root, project_id in (
                (safe_root, "11111111-1111-4111-8111-111111111111"),
                (external_root, "22222222-2222-4222-8222-222222222222"),
            ):
                self.write_manifest(
                    root,
                    {"uuid": project_id, "humanName": "synthetic"},
                )
            external_subdirectory = base / "external" / "subdirectory"
            external_subdirectory.mkdir()
            (base / "safe" / "redirect").symlink_to(
                external_subdirectory,
                target_is_directory=True,
            )
            ambiguous_root = base / "safe" / "redirect" / ".." / "repository"
            with self.assertRaises(ValidationFailure) as caught:
                load_repo_identity(ambiguous_root)
            self.assertEqual(caught.exception.code, "repo-identity-unsafe")

    def test_windows_reparse_attribute_is_treated_as_redirect(self):
        reparse = SimpleNamespace(
            st_mode=stat.S_IFDIR,
            st_file_attributes=0x400,
        )
        self.assertTrue(_is_link_or_reparse(reparse))

    def test_manifest_requires_exact_git_root_and_committed_bytes(self):
        candidate = {
            "uuid": "11111111-1111-4111-8111-111111111111",
            "humanName": "synthetic",
        }
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            arbitrary = base / "arbitrary"
            self.write_manifest(arbitrary, candidate)
            with self.assertRaises(ValidationFailure) as caught:
                load_repo_identity(arbitrary)
            self.assertEqual(caught.exception.code, "repo-identity-not-repository")

            repository = base / "repository"
            self.write_committed_manifest(repository, candidate)
            nested = repository / "nested"
            nested.mkdir()
            self.write_manifest(nested, candidate)
            with self.assertRaises(ValidationFailure) as caught:
                load_repo_identity(nested)
            self.assertEqual(caught.exception.code, "repo-identity-not-repository")

            manifest_path = repository / ".agent-memory" / "repo.json"
            changed = {**candidate, "uuid": "22222222-2222-4222-8222-222222222222"}
            manifest_path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaises(ValidationFailure) as caught:
                load_repo_identity(repository)
            self.assertEqual(caught.exception.code, "repo-identity-uncommitted")

    def test_git_verification_ignores_repository_selection_environment(self):
        candidate = {
            "uuid": "11111111-1111-4111-8111-111111111111",
            "humanName": "synthetic",
        }
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            external = base / "external"
            self.write_committed_manifest(external, candidate)
            arbitrary = base / "arbitrary"
            self.write_manifest(arbitrary, candidate)
            environment = {
                "GIT_DIR": str(external / ".git"),
                "GIT_WORK_TREE": str(arbitrary),
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "core.worktree",
                "GIT_CONFIG_VALUE_0": str(arbitrary),
            }
            with mock.patch.dict(os.environ, environment, clear=False):
                with self.assertRaises(ValidationFailure) as caught:
                    load_repo_identity(arbitrary)
                self.assertEqual(
                    caught.exception.code, "repo-identity-not-repository"
                )
                self.assertEqual(load_repo_identity(external), candidate)

    def test_git_replace_refs_cannot_supply_a_machine_local_manifest(self):
        candidate = {
            "uuid": "11111111-1111-4111-8111-111111111111",
            "humanName": "synthetic",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            root.mkdir(exist_ok=True)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.name", "Synthetic Fixture"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "fixture@example.invalid"],
                cwd=root,
                check=True,
            )
            placeholder = root / "placeholder.txt"
            placeholder.write_text("synthetic\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "placeholder.txt"], cwd=root, check=True
            )
            subprocess.run(
                ["git", "commit", "-q", "-m", "Synthetic base"],
                cwd=root,
                check=True,
            )
            original = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip()
            self.write_manifest(root, candidate)
            self.commit_repository(root, "Add replacement identity")
            replacement = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip()
            subprocess.run(
                ["git", "replace", original, replacement], cwd=root, check=True
            )
            subprocess.run(
                ["git", "--no-replace-objects", "reset", "--hard", original],
                cwd=root,
                check=True,
                stdout=subprocess.DEVNULL,
            )
            self.write_manifest(root, candidate)
            with self.assertRaises(ValidationFailure) as caught:
                load_repo_identity(root)
            self.assertEqual(caught.exception.code, "repo-identity-uncommitted")


if __name__ == "__main__":
    unittest.main()
