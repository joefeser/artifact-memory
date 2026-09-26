import copy
import json
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from artifact_memory.coordination import revision_digest
from artifact_memory.repo_identity import (
    _is_link_or_reparse,
    load_repo_identity,
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

    def test_repository_manifest_is_strict_and_public(self):
        identity = load_repo_identity(ROOT)
        self.assertEqual(identity["humanName"], "artifact-memory")
        self.assertEqual(
            identity["uuid"], "6f2d78a4-c0e5-4fa2-a9ce-2c4f760c5a31"
        )

    def test_same_human_name_with_different_uuids_is_unambiguous(self):
        roots = [
            FIXTURE / "repositories" / "alpha",
            FIXTURE / "repositories" / "beta",
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
        with self.assertRaises(ValidationFailure) as caught:
            validate_repo_bound_coordination_records(
                [label, task], [FIXTURE / "repositories" / "beta"]
            )
        self.assertEqual(caught.exception.code, "coordination-project-unknown")
        self.assertEqual(caught.exception.path, "$.records[0].projectNames[0].projectId")

    def test_human_name_rename_changes_no_record_digest(self):
        task = load_json(COORDINATION / "task-open.json")
        before = revision_digest(task)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            manifest_dir = root / ".agent-memory"
            manifest_dir.mkdir()
            manifest = {
                "uuid": task["projectId"],
                "humanName": task["projectName"],
            }
            (manifest_dir / "repo.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            first = load_repo_identity(root)
            manifest["humanName"] = "renamed-display-only"
            (manifest_dir / "repo.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
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
                self.write_manifest(root, candidate)
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


if __name__ == "__main__":
    unittest.main()
