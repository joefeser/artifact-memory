# 0033: Bind coordination freshness to an exact repository head

Status: accepted for AM-6

## Context

Coordination records may carry the optional namespaced freshness declaration
`https://artifact-memory.dev/extensions/coordination-freshness/v1`. Its
`trueAsOfCommit` identifies the Git commit against which the record was
prepared, but the identifier alone does not establish whether that commit is
still in the current repository history or even belongs to the intended
project.

Kickoff-pack v0 intentionally makes no repository freshness claim. Extending
that closed schema in place would break strict readers, while silently treating
an unknown or unbound repository as current would overstate the evidence.

## Decision

Repository freshness evaluation is explicit through `artifact-memory kickoff
--repo`. The selected path must be the exact top level of the project repository
already bound to the vault through AM-9 onboarding. The evaluator reads the
project identity from the exact observed HEAD commit and requires its UUID to
match the kickoff project before reporting ancestry.

Git replacement objects and ambient repository/configuration overrides are
disabled. The evaluator records the exact observed HEAD, rejects a changed HEAD
during the comparison, and uses `git merge-base --is-ancestor` over full object
IDs of the repository's declared object format. A valid ancestor is `current`;
a valid non-ancestor is `stale-verify`. Missing objects, malformed identities,
object-format mismatches, unsafe roots, and observation races fail typed.

Repo-bound output uses `artifact-memory/coordination-kickoff-pack/v1`, which
requires the selected record's freshness status and both object IDs. Without
`--repo`, the optional declaration remains opaque and the existing v0 pack is
unchanged. Generic knowledge context-pack v2-v4 contracts are also unchanged.

## Consequences

- Freshness is an exact, local repository observation, not issuer
  authenticity, global truth, or proof that the worktree is clean.
- An empty queue still validates the requested repository binding even though
  there is no selected record to annotate.
- Unknown optional extensions remain preserved but uninterpreted. Unknown
  required extensions and top-level `trueAsOfCommit` fields fail closed.
- A `stale-verify` marker is informational. It grants no execution, mutation,
  routing, disclosure, credential, spending, deployment, approval, or merge
  authority.
