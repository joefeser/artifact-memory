"""Smoke the installed console script from outside the source checkout."""

from __future__ import annotations

import json
import subprocess
import sys
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
        packaged_schema = subprocess.run(
            [
                sys.executable,
                "-c",
                "from artifact_memory.schema_resources import load_schema; "
                "assert load_schema('core', 'authenticity-receipt.v2.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/authenticity-receipt/v2'; "
                "assert load_schema('core', 'content-object.v2.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/content-object/v2'; "
                "assert load_schema('core', 'content-verification-receipt.v1.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/content-verification-receipt/v1'; "
                "assert load_schema('core', 'conformance-fixture-manifest.v1.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/conformance-fixture-manifest/v1'; "
                "assert load_schema('core', 'conformance-expected-results.v1.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/conformance-expected-results/v1'; "
                "assert load_schema('core', 'manifest-conformance-vectors.v1.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/manifest-conformance-vectors/v1'; "
                "assert load_schema('core', 'manifest-conformance-receipt.v1.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/manifest-conformance-receipt/v1'; "
                "assert load_schema('core', 'extension-conformance-receipt.v1.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/extension-conformance-receipt/v1'; "
                "assert load_schema('core', 'exchange-envelope.v2.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/exchange-envelope/v2'; "
                "assert load_schema('core', 'admission-receipt.v2.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/admission-receipt/v2'; "
                "assert load_schema('core', 'exchange-conformance-vectors.v1.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/exchange-conformance-vectors/v1'; "
                "assert load_schema('core', 'exchange-conformance-receipt.v1.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/exchange-conformance-receipt/v1'; "
                "assert load_schema('core', 'independent-exchange-vectors.v1.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/independent-exchange-vectors/v1'; "
                "assert load_schema('core', 'independent-exchange-conformance-receipt.v1.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/independent-exchange-conformance-receipt/v1'; "
                "assert load_schema('adapters', 'adapter-manifest.v1.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/adapter-manifest/v1'; "
                "assert load_schema('adapters', 'adapter-manifest.v2.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/adapter-manifest/v2'; "
                "assert load_schema('adapters', 'adapter-receipt.v1.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/adapter-receipt/v1'; "
                "assert load_schema('adapters', 'adapter-manifest-conformance-receipt.v1.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/adapter-manifest-conformance-receipt/v1'; "
                "assert load_schema('adapters', 'adapter-manifest-conformance-receipt.v2.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/adapter-manifest-conformance-receipt/v2'; "
                "assert load_schema('adapters', 'tracemap-adapter-receipt.v1.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/tracemap-adapter-receipt/v1'; "
                "assert load_schema('adapters', 'tracemap-failure-conformance-receipt.v1.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/tracemap-failure-conformance-receipt/v1'; "
                "assert load_schema('core', 'vault-intake-receipt.v1.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/vault-intake-receipt/v1'; "
                "assert load_schema('core', 'vault-intake-vector.v1.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/vault-intake-vector/v1'; "
                "assert load_schema('core', 'vault-intake-conformance-receipt.v1.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/vault-intake-conformance-receipt/v1'; "
                "assert load_schema('core', 'release-manifest.v3.schema.json')"
                "['properties']['schema_id']['const'] == 'artifact-memory/release-manifest/v3'; "
                "assert load_schema('core', 'release-candidate-preparation-receipt.v3.schema.json')"
                "['properties']['schema_id']['const'] == "
                "'artifact-memory/release-candidate-preparation-receipt/v3'; "
                "assert load_schema('core', 'release-candidate-verification-receipt.v3.schema.json')"
                "['properties']['schema_id']['const'] == "
                "'artifact-memory/release-candidate-verification-receipt/v3'; "
                "assert load_schema('core', 'private-vault-onboarding-slice-receipt.v1.schema.json')"
                "['properties']['schema_id']['const'] == "
                "'artifact-memory/private-vault-onboarding-slice-receipt/v1'; "
                "assert load_schema('core', 'coordination-onboarding-bootstrap-receipt.v0.schema.json')"
                "['properties']['schema_id']['const'] == "
                "'artifact-memory/coordination-onboarding-bootstrap-receipt/v0'; "
                "assert load_schema('core', 'coordination-onboarding-kickoff-pack.v0.schema.json')"
                "['properties']['schema_id']['const'] == "
                "'artifact-memory/coordination-onboarding-kickoff-pack/v0'; "
                "assert load_schema('core', 'coordination-onboarding-conformance-receipt.v0.schema.json')"
                "['properties']['schema_id']['const'] == "
                "'artifact-memory/coordination-onboarding-conformance-receipt/v0'; "
                "assert load_schema('core', 'coordination-kickoff-pack.v0.schema.json')"
                "['properties']['schema_id']['const'] == "
                "'artifact-memory/coordination-kickoff-pack/v0'; "
                "assert load_schema('core', 'coordination-kickoff-conformance-receipt.v0.schema.json')"
                "['properties']['schema_id']['const'] == "
                "'artifact-memory/coordination-kickoff-conformance-receipt/v0'; "
                "assert load_schema('coordination', 'project-link.v0.schema.json')"
                "['properties']['schema_id']['const'] == "
                "'artifact-memory/local-coordination-project-link/v0'; "
                "assert load_schema('coordination', 'onboarding-publication.v0.schema.json')"
                "['properties']['schema_id']['const'] == "
                "'artifact-memory/local-coordination-onboarding-publication/v0'; "
                "assert load_schema('coordination', 'onboarding-attempt.v0.schema.json')"
                "['properties']['schema_id']['const'] == "
                "'artifact-memory/local-coordination-onboarding-attempt/v0'; "
                "assert load_schema('coordination', 'onboarding-sync-checkpoint.v0.schema.json')"
                "['properties']['schema_id']['const'] == "
                "'artifact-memory/local-coordination-onboarding-sync-checkpoint/v0'",
            ],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if packaged_schema.returncode != 0:
            raise SystemExit(packaged_schema.stderr or packaged_schema.stdout)
        codex_history_schemas = subprocess.run(
            [
                sys.executable,
                "-c",
                "from artifact_memory.schema_resources import load_schema; "
                "assert load_schema('adapters', 'codex-history-import-policy.v1.schema.json')"
                "['properties']['schema_id']['const'] == "
                "'artifact-memory/codex-history-import-policy/v1'; "
                "assert load_schema('core', 'declassification-receipt.v2.schema.json')"
                "['properties']['schema_id']['const'] == "
                "'artifact-memory/declassification-receipt/v2'",
            ],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if codex_history_schemas.returncode != 0:
            raise SystemExit(codex_history_schemas.stderr or codex_history_schemas.stdout)

        if sys.platform == "win32":
            target = root / "synthetic-vault-target"
            junction = root / "synthetic-vault-junction"
            source = root / "synthetic-done-log.md"
            target.mkdir()
            source.write_text(
                "2026-09-27 Verified synthetic session handoff.\n",
                encoding="utf-8",
            )
            linked = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if linked.returncode != 0:
                raise SystemExit(linked.stderr or linked.stdout)
            rejected = subprocess.run(
                [
                    "artifact-memory",
                    "import-session-ledger",
                    str(source),
                    "--vault",
                    str(junction),
                    "--json",
                ],
                cwd=root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if rejected.returncode != 2:
                raise SystemExit(rejected.stderr or rejected.stdout)
            payload = json.loads(rejected.stdout)
            if payload.get("diagnostics", [{}])[0].get("code") != "sync-storage-unsafe":
                raise SystemExit(rejected.stdout)
            if (target / "records").exists():
                raise SystemExit("session-ledger junction proof crossed the vault boundary")


if __name__ == "__main__":
    main()
