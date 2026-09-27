# Onboard a repository to the coordination plane

AM-9 provides the shortest provider-free path from a Git repository and an
already administered hub binding to a local coordination replica. It does not
issue credentials, register WITS authority, or commit Git history.

Before running it, a separately authorized WITS administrator—or the synthetic
local-hub setup used by conformance tests—must bind the authenticated session
to a stable principal and exact AccessLabel revision. The label must grant read
access to the intended project UUID. The client cannot choose another label by
naming it.

```sh
artifact-memory onboard /path/to/repository \
  --vault /path/to/private-coordination-vault \
  --hub /path/to/provider-free-hub \
  --session-id coordination-session://synthetic/example \
  --human-name public-project-name \
  --completed-at 2026-09-26T20:00:00Z \
  --json
```

If the authenticated binding exposes multiple readable projects, add the UUID
of the intended project:

```sh
  --project-id 11111111-1111-4111-8111-111111111111
```

The UUID still comes from the authenticated server binding. `--project-id`
narrows that authorized set; it cannot introduce an unrelated project. For a
new manifest, `--human-name` is required and must be a deliberately public-safe
display name. Artifact Memory does not copy a possibly private label name into
the repository.

## What the command writes

The only coordination file written inside the repository is:

```text
.agent-memory/repo.json
```

If it is new, inspect and commit it through the repository's normal Git
governance. The bootstrap receipt reports `created-pending-commit`; Artifact
Memory never stages or commits the file for you.

Safe automatic creation requires filesystem support for held parent-directory
descriptors and no-follow traversal. If the command returns
`repo-identity-create-unsupported`, create and commit the strict two-field
manifest through an independently trusted workflow, then rerun onboarding.
Artifact Memory does not use a pathname-only fallback. Bare repositories are
not onboarding roots.

The private vault receives:

```text
config/coordination/projects/<project-uuid>.json
generated/coordination-onboarding/<project-uuid>/bootstrap-kickoff.json
generated/coordination-onboarding/<project-uuid>/bootstrap-kickoff.md
receipts/coordination-onboarding/<project-uuid>.json
transactions/coordination-onboarding/<project-uuid>.json
transactions/coordination-onboarding/<project-uuid>.attempt.json
transactions/coordination-onboarding/<project-uuid>.sync.json
```

The project link stores logical IDs and the exact opaque AccessLabel reference,
not a hostname, path, credential, or full label body. The generated bootstrap
pack is informational. AM-5 will add queue selection and safe rendering of
untrusted acceptance commands; AM-9 explicitly does neither. AM-1 will add
session-ledger ingestion; onboarding preserves existing history without
claiming it was imported.

The attempt is immutable pre-sync evidence. The sync checkpoint retains the
exact bounded response after validation and before application. If sync or
publication is interrupted, a retry first reconciles a pending pull, consumes
only matching admission outcomes, and reuses the checkpoint only when the
authenticated principal, hub, label revision, policy generation, and timestamp
match the attempt. Recovery does not depend on the mutable current-projection
marker. The publication transaction is an immutable, digest-bound journal. It
lets a retry complete missing matching outputs after interruption without
deleting or rewriting durable evidence. Project onboarding is serialized so
concurrent calls replay the first completed receipt instead of creating
divergent packs.

## Repo-bound commands

After the repository identity is committed, use `--repo` to require AM-9
preflight before a coordination operation:

```sh
artifact-memory sync \
  --repo /path/to/repository \
  --vault /path/to/private-coordination-vault \
  --hub /path/to/provider-free-hub \
  --session-id coordination-session://synthetic/example \
  --completed-at 2026-09-26T20:05:00Z \
  --json
```

An un-onboarded repo fails with `coordination-onboarding-required` and names
`artifact-memory onboard` as the corrective action. Omitting `--repo` keeps the
existing low-level local adapter behavior for conformance use; it does not
prove repository onboarding. In repo-bound mode, sync also rejects a different
logical hub or exact AccessLabel revision, and local append rejects a record
for another project, another label revision, or a full AccessLabel body.

Rerunning `onboard` against a complete matching bootstrap validates and returns
the original receipt without syncing or changing vault bytes. Partial state,
a different logical hub, a changed exact label reference, or a project outside
the authenticated readable set fails typed.

Run the public synthetic proof with:

```sh
python3 scripts/run_coordination_onboarding_conformance.py --check
```

All checked-in inputs and outputs are synthetic. Real vaults, hub topology,
session handles, credentials, records, and machine paths remain outside this
public repository.
