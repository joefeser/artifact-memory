# 0031: Bootstrap coordination projects from server-bound labels

- Status: accepted
- Date: 2026-09-26
- Issue: [#142](https://github.com/joefeser/artifact-memory/issues/142)
- Contract: `docs/contracts/v0-coordination-plane.md`

## Context

AM-9 needs one onboarding command without weakening the coordination contract.
The client cannot choose an AccessLabel, create a credential binding, or infer
project authority from record text. Repository identity also must not depend on
a checkout path, remote URL, or display name. Finally, creating a public
repository file does not authorize Artifact Memory to commit Git history.

AM-1 separately owns session-ledger import. AM-5 separately owns queue
selection and safe rendering of untrusted acceptance commands. AM-9 must not
silently implement either contract ahead of its issue.

## Decision

`artifact-memory onboard` selects a project only from the authenticated hub
binding's readable project set. If that set has one project, the command uses
its UUID. If it has more than one, the operator must name one of those UUIDs
with `--project-id`. A new repository identity also requires an explicit
public-safe `--human-name`; the command never copies a potentially private
AccessLabel display name into the public repository. The client never submits
an AccessLabel body or chooses an arbitrary label reference.

The command then:

1. creates or verifies `.agent-memory/repo.json` at the exact Git worktree
   root;
2. performs one provider-free push/pull sync under the already established
   server-side principal and AccessLabel binding;
3. stores a local project link containing only the logical hub ID and exact
   opaque AccessLabel reference;
4. emits a minimal informational bootstrap kickoff pack; and
5. emits a digest-bound bootstrap receipt.

The full AccessLabel body remains hub-side. The bootstrap pack contains a
static startup protocol, aggregate project-record count, and exact sync
observation. It deliberately renders no queue item or acceptance command and
states that AM-5 is required for those semantics.

When the command creates `repo.json`, the receipt reports
`created-pending-commit`. Artifact Memory does not stage or commit it. A human
or separately authorized Git workflow must review and commit that public
identity. Repo-bound `sync` and `record append` preflights fail typed and name
`artifact-memory onboard` until both the committed identity and local project
link exist. The low-level provider-free adapter remains available without
`--repo` for conformance and compatibility.

Repo-bound sync compares the live server-side binding to the stored logical
hub ID and exact AccessLabel reference under the same principal lock. A
repo-bound local append must name the linked project and exact label; it cannot
append a full AccessLabel body. These checks prevent the preflight from being a
presence-only marker.

A complete existing bootstrap is replayed without syncing or rewriting. The
vault remains byte-identical even if a later invocation supplies a different
observation timestamp. Conflicting bootstrap state fails closed. Matching
partial state backed by the publication transaction is resumed as described
below; partial state without that evidence fails closed.

Publication is serialized per project. Before sync, onboarding retains one
immutable, digest-bound attempt containing the selected project and label,
policy generation, observation timestamp, initial record count, and initial
repo/vault states. After the pull response is fully validated but before it is
applied, onboarding retains an immutable checkpoint containing that exact
bounded response. A retry validates the checkpoint against the authenticated
principal, hub, label revision, policy generation, and timestamp from the
attempt. It resumes an existing pending pull before attempting another push,
consumes only pending outcomes represented by the checkpoint receipt, and can
recover the checkpoint even if a later successful pull advances the mutable
current marker. Before exposing the project link, kickoff projections, or
bootstrap receipt, onboarding then retains one immutable, digest-bound
publication transaction containing their exact bytes. A retry validates that
transaction and installs only missing matching outputs; any conflicting output
fails closed. This makes interruption recoverable without rewriting or
deleting immutable evidence, and concurrent calls replay the first completed
receipt.

Automatic `repo.json` creation requires held parent-directory descriptors and
no-follow traversal. A runtime without equivalent primitives fails typed with
`repo-identity-create-unsupported`; it never falls back to a checked pathname
that could be redirected after validation. An independently trusted workflow
may create and commit the strict manifest before rerunning onboarding.

## Security consequences

- The onboarding client cannot widen the authenticated label or discover
  denied project identities.
- No full AccessLabel body, credential, session handle, machine path, hostname,
  or provider URL enters the local project link, kickoff pack, or receipt.
- Repository identity creation refuses links and reparse points and never
  overwrites an existing manifest; bare repositories are rejected.
- Runtimes without safe parent-directory creation primitives make no identity
  write and return an explicit unsupported outcome.
- A crash after publication begins is recoverable from the immutable
  transaction, while conflicting partial bytes remain a hard failure.
- A crash during sync or before publication reuses only the exact bounded
  response checkpoint bound to the pre-sync attempt. Pending admission evidence
  is reconciled before another push, and a later current projection cannot
  erase the attempt-specific evidence.
- A bootstrap receipt proves local orchestration evidence only. It grants no
  execution, disclosure, mutation, spending, deployment, approval, or merge
  authority.
- Git commit verification remains mandatory for later repo-bound operations;
  a newly written working-tree manifest alone is not durable identity proof.

## Compatibility consequences

- Existing `artifact-memory sync` and `record append` invocations remain valid
  as low-level provider-free operations.
- Callers opt into the AM-9 precondition with `--repo`.
- Session-ledger/history import remains AM-1 and is reported as deferred.
- Queue selection and untrusted command rendering remain AM-5 and are reported
  as not rendered.
