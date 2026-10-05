import unittest
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from artifact_memory.platform_matrix import (
    _initialize_synthetic_repository,
    probe_platform,
)
from artifact_memory.schema_resources import load_schema
from artifact_memory.validator import validate


class PlatformMatrixTests(unittest.TestCase):
    def test_repository_fixture_ignores_ambient_templates_and_hooks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "repository"
            manifest = target / ".agent-memory" / "repo.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                '{"uuid":"11111111-1111-4111-8111-111111111111",'
                '"humanName":"synthetic-platform-repository"}\n',
                encoding="utf-8",
            )
            marker = target / "ambient-hook-ran"
            template = root / "ambient-template"
            hooks = template / "hooks"
            hooks.mkdir(parents=True)
            hook = hooks / "post-commit"
            hook.write_text(
                "#!/bin/sh\nprintf x > ambient-hook-ran\n",
                encoding="utf-8",
            )
            hook.chmod(0o755)
            ambient_config = root / "ambient-gitconfig"
            ambient_config.write_text(
                f"[init]\n\ttemplateDir = {template}\n"
                f"[core]\n\thooksPath = {hooks}\n",
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {"GIT_CONFIG_GLOBAL": str(ambient_config)},
            ):
                self.assertTrue(_initialize_synthetic_repository(root, target))
            self.assertFalse(marker.exists())

    def test_probe_is_sanitized_and_explicit(self):
        receipt = probe_platform()
        self.assertEqual(
            receipt["schema_id"], "artifact-memory/platform-matrix-receipt/v2"
        )
        validate(
            receipt,
            load_schema("core", "platform-matrix-receipt.v2.schema.json"),
        )
        self.assertNotIn("/", receipt["runtime"]["family"])
        self.assertIn(
            receipt["observations"]["symlink_behavior"],
            {
                "created-but-v0-scan-unsupported",
                "creation-unsupported",
                "probe-failed",
            },
        )
        if os.name == "nt":
            self.assertEqual(
                receipt["observations"]["repo_identity_redirect_behavior"],
                "junction-rejected",
            )
        else:
            self.assertEqual(
                receipt["observations"]["repo_identity_redirect_behavior"],
                "not-applicable",
            )
        self.assertEqual(
            receipt["observations"]["timestamps"],
            "ignored-by-v0-profile",
        )
        self.assertEqual(
            receipt["observations"]["mount_layout"],
            "logical-relative-paths-only",
        )

    def test_committed_receipts_validate_without_machine_paths(self):
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root / "artifact_memory/schemas/core/platform-matrix-receipt.v1.schema.json").read_text(encoding="utf-8"))
        for path in sorted((root / "fixtures/synthetic/platform/receipts").glob("*.json")):
            receipt = json.loads(path.read_text(encoding="utf-8"))
            validate(receipt, schema)
            self.assertNotIn("/Users/", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
