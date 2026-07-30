"""Smoke the installed console script from outside the source checkout."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        record = root / "record.json"
        record.write_text(
            json.dumps(
                {
                    "schema_id": "artifact-memory/knowledge-record/v1",
                    "record_id": "record://synthetic/installed-smoke",
                    "record_type": "decision",
                    "lifecycle": "accepted",
                    "meaning": {"summary": "Installed schema resource smoke test"},
                    "artifact_refs": [],
                    "provenance": [{"kind": "author", "source_ref": "fixture://synthetic/installed-smoke"}],
                    "sensitivity": "public",
                }
            ),
            encoding="utf-8",
        )
        completed = subprocess.run(
            ["artifact-memory", "validate", str(record), "--json"],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0:
            raise SystemExit(completed.stderr or completed.stdout)
        receipt = json.loads(completed.stdout)
        if receipt.get("valid") is not True or receipt.get("outcome") != "accepted":
            raise SystemExit(completed.stdout)


if __name__ == "__main__":
    main()
