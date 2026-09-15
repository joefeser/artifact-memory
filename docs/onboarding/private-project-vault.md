# Using Artifact Memory for a private project vault

This guide is the shortest supported path from canonical private records to a
bounded context pack for a human or fresh agent. Artifact Memory remains a
provider-free local CLI. It does not discover private projects, grant access,
or authorize work.

Use an owner-signed release that contains this guide, or an explicitly reviewed
commit containing the semantic context-pack validator, and record that exact
version in the private vault README. The published `v0.1.3` release predates
that validator and is not a sufficient baseline for this workflow. Until a
newer release is published, pin the exact reviewed commit instead of relying on
the package version alone.

## Keep the public repository and private vault separate

The public Artifact Memory repository contains schemas, tooling, docs, and
synthetic fixtures. A real project vault belongs outside every Git worktree.
Do not put a vault in a public repository and rely on `.gitignore` as the
security boundary.

A recommended local layout is:

```text
~/.artifact-memory/vaults/<project-name>/
  README.md
  records/
    operations/
      <record>.json
    decisions/
      <record>.json
  generated/
    search-projection/
      records.ndjson
      records.sqlite
      projection-receipt.json
    context-pack-<purpose>/
      context-pack.json
```

`records/` contains canonical, versioned JSON records. `README.md` records
local purpose, readers, sensitivity, source policy, Artifact Memory version,
retention, and backup coverage. Everything under `generated/` is replaceable.
Generated views can still disclose private summaries, so protect them with the
same local access controls as the canonical records.

The directory name does not imply encryption or backup. Configure those
properties separately and record only accurate coverage claims.

## Create one record outside the repository

Choose a private root and create it with owner-only permissions:

```bash
umask 077
AM_VAULT_ROOT="$HOME/.artifact-memory/vaults/example-project"
mkdir -p "$AM_VAULT_ROOT/records/operations" "$AM_VAULT_ROOT/generated"
chmod 700 \
  "$AM_VAULT_ROOT" \
  "$AM_VAULT_ROOT/records" \
  "$AM_VAULT_ROOT/records/operations" \
  "$AM_VAULT_ROOT/generated"
```

Create `README.md` and record the allowed readers, source scope, lifecycle,
backup status, and exact Artifact Memory release or commit. Never place
credentials in that file.

Then save a record such as the following to
`$AM_VAULT_ROOT/records/operations/relay-connectivity.json`. This example is
synthetic; a real private record must be curated from an authorized source and
must preserve honest provenance.

Keep the shell `umask 077` while generating projections and context packs, and
verify that canonical and generated files are readable only by the intended
local account.

```json
{
  "artifact_refs": [],
  "lifecycle": "accepted",
  "meaning": {
    "labels": ["connectivity", "operations"],
    "summary": "Synthetic relay failures are diagnosed by checking overlay connectivity before service health."
  },
  "provenance": [
    {
      "kind": "author",
      "source_ref": "actor://local-owner/operator"
    }
  ],
  "record_id": "record://example-project/relay-connectivity",
  "record_type": "note",
  "schema_id": "artifact-memory/knowledge-record/v3",
  "sensitivity": "private"
}
```

The record identity is logical. Do not encode a username, hostname, IP
address, mount point, filename, or provider URL into it.

## Validate, project, and search

From a shell with the `artifact-memory` command installed:

```bash
record_paths=("$AM_VAULT_ROOT"/records/*/*.json)

for record_path in "${record_paths[@]}"; do
  artifact-memory validate "$record_path" --json
done

artifact-memory project \
  "${record_paths[@]}" \
  --out "$AM_VAULT_ROOT/generated/search-projection" \
  --json

artifact-memory search \
  "$AM_VAULT_ROOT/generated/search-projection/records.sqlite" \
  "overlay connectivity" \
  --literal \
  --exclude-superseded \
  --json
```

Projection creation and every projection read fail closed when the loaded
SQLite/FTS5 runtime cannot demonstrate the required integrity behavior.
Search helps find candidate records; rank or presence in search results does
not establish truth, freshness, relevance, or authority.

## Export a bounded context pack

Choose records deliberately after checking their lifecycle, sensitivity, and
freshness. The timestamp and freshness basis below are operator assertions,
not facts inferred by Artifact Memory:

```bash
AM_SELECTED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

artifact-memory context \
  "$AM_VAULT_ROOT/records/operations/relay-connectivity.json" \
  --allow-sensitivity private \
  --max-bytes 4096 \
  --selected-at "$AM_SELECTED_AT" \
  --freshness-basis "operator-reviewed-at-selection-time" \
  --support-context-schema artifact-memory/context-pack/v4 \
  --out "$AM_VAULT_ROOT/generated/context-pack-operator-startup" \
  --json

artifact-memory validate \
  "$AM_VAULT_ROOT/generated/context-pack-operator-startup/context-pack.json" \
  --json
```

Context-pack v4 records caller selection, lifecycle exclusions, sensitivity
exclusions, freshness assertions, revocation exclusions, and the byte limit.
Excluded protected identities are counted rather than disclosed. Artifact
references remain references; retrieving bytes requires separate authority.

## Fresh agent startup

Give a new agent the project path, the private vault path, the exact bounded
context-pack path, and explicit read authorization. Paste the
[fresh-agent startup template](templates/private-vault-agent-startup.md) into
the new context.

The agent should first read project `AGENTS.md` and project documentation, then
the vault README, then validate and read the bounded pack. It may read only the
specific canonical record paths separately named by the operator and should
confirm that their record IDs and revisions match the pack. It should report
the pack contract, identity, source-record-set
digest, selection time, byte bound, exclusions, freshness basis, and authority
limitations before using the context.

If the pack is missing, stale, invalid, over budget, or requests an unsupported
contract, the agent should stop and request a new bounded export. It must not
silently scan the whole vault or invent a freshness assertion.

## Leakage guardrails

Never put these in the public Artifact Memory repository, public issues, pull
requests, review comments, logs, or synthetic fixtures:

- real customer or project records;
- private hostnames, network addresses, emails, or machine-local paths;
- credentials, private keys, cookies, bearer URLs, or resolver configuration;
- raw conversations, task transcripts, attachments, exports, or artifact
  bytes;
- lightly redacted production or customer data.

Before committing public tooling changes:

```bash
git status --short --untracked-files=all
python3 scripts/public_safety_check.py
python3 scripts/run_private_vault_onboarding_slice.py --check >/dev/null
```

The repository safety scan checks tracked paths, reachable history, current
index/worktree content, and high-confidence secret patterns. The onboarding
slice adds fixture-specific checks for synthetic identity, network addresses,
emails, machine-local paths, credential fields, and raw source files. A clean
scan is a guardrail, not proof that no protected value exists. Human review and
strict physical separation remain required.

Storage does not imply backup. Expiry makes a source eligible for the governed
deletion process; it does not prove deletion from endpoints or backups and
never establishes global erasure.

## Reproduce the public synthetic proof

The checked-in proof uses only invented records and writes all generated files
to a disposable directory:

```bash
python3 scripts/run_private_vault_onboarding_slice.py --check
python3 scripts/run_private_vault_onboarding_slice.py --check --human
```

It validates three records, builds a projection, finds two operational topics,
exports a 4 KiB context-pack v4, verifies it with the independent reader, and
receipts the informational-only boundary.
