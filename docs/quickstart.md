# Quickstart

Artifact Memory v0 is a provider-free Python reference runtime. It is not a
service and it does not require a vault, credentials, or network access.
Querying a generated SQLite/FTS5 projection requires a loaded SQLite runtime
whose integrity check behaviorally demonstrates FTS5 inverted-index coverage;
upstream SQLite added that capability in 3.44. An incapable or custom runtime
fails closed with `projection-unavailable` rather than serving unverifiable
results. The version linked to Python is useful diagnostic context, but it is
not the capability decision:

```shell
python3 -c 'import sqlite3; print(sqlite3.sqlite_version)'
```

From a clean clone:

```shell
python3 -m pip install --no-deps .
artifact-memory version --json
python3 -m artifact_memory version --json
scripts/validate_contracts.sh
scripts/run_conformance.sh
python3 -m artifact_memory validate fixtures/synthetic/contracts/v0-valid-record.json --json
```

Exercise the authoritative behavioral gate by building and reading a synthetic
projection outside the repository:

```shell
(
  set -eu
  am_probe_dir="$(mktemp -d)"
  trap 'rm -r -- "$am_probe_dir"' EXIT
  python3 -m artifact_memory project \
    fixtures/synthetic/contracts/v0-valid-record.json \
    --out "$am_probe_dir" \
    --json
  python3 -m artifact_memory search \
    "$am_probe_dir/records.sqlite" \
    synthetic \
    --json
)
```

A successful search demonstrates the required behavior for that loaded
SQLite/FTS5 build. If the build cannot create or verify the projection, the
`project` or `search` command returns the typed `projection-unavailable`
outcome regardless of its reported version. The subshell removes the temporary
projection on success or failure.

The repository contains synthetic fixtures only. A generated index or context
pack is a derived view; it is not a replacement for canonical records.

The v0 support boundary is documented in the contract files and receipts.
Unsupported filesystem semantics, unverified authenticity, unknown required
extensions, and authority-bearing adapter requests fail closed or remain
explicit outcomes.

To evaluate Artifact Memory from another repository, start with the read-only
fit audit in the [repository adoption prompts](onboarding/repository-adoption.md).
The prompts pin implementation claims to the owner-signed v0.1.2 release and
keep product meaning and operational authority with their owning systems.
