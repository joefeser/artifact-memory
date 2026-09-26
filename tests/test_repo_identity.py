import copy
import json
import tempfile
import unittest
from pathlib import Path

from artifact_memory.coordination import revision_digest
from artifact_memory.repo_identity import (
    load_repo_identity,
    load_repo_identity_registry,
    validate_repo_bound_coordination_records,
)
from artifact_memory.validator import ValidationFailure, load_json


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "coordination-repo-identity" / "v0"
COORDINATION = ROOT / "fixtures" / "coordination"


class RepoIdentityTests(unittest.TestCase):
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
            root = Path(temporary)
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
            root = Path(temporary)
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


if __name__ == "__main__":
    unittest.main()
