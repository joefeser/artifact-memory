# 0030: Bind repository identity to UUID

- Status: accepted
- Date: 2026-09-26
- Issue: [#141](https://github.com/joefeser/artifact-memory/issues/141)
- Contract: `docs/contracts/v0-coordination-plane.md`

## Context

Coordination records need a project identity that survives repository renames,
same-name repositories, and multiple checkouts. A filename, checkout path,
remote URL, or human-readable name is mutable or machine-local and therefore
cannot be the durable join key. The committed identity manifest is public
metadata, not a credential or authority grant.

## Decision

Each onboarded repository carries exactly `.agent-memory/repo.json` with a
stable UUID and a display-only `humanName`. Coordination records reference the
UUID. Human names are non-unique provenance and are never used for joins,
authorization, or conflict detection.

A registry may observe the same UUID through multiple checkouts or across a
display-name rename; those observations identify one project. Distinct UUIDs
remain distinct even when their human names are identical. An unknown UUID
fails repository-bound coordination validation with a typed diagnostic.

Identity loading rejects redirected repository roots, identity directories,
and manifest files. It reads a stable regular file without following the final
link where the platform supports that flag, then rechecks each inspected entry
to detect substitution during the read.

## Security consequences

- The manifest contains no secret, credential, bearer URL, or machine-local
  resolver configuration.
- A UUID proves only which repository identity a record names. It does not
  prove authorship, authenticity, trust, disclosure permission, or execution
  authority.
- Symlinked identity paths fail closed so external machine-local state cannot
  silently define a repository identity.
- An operator must supply the intended repository roots explicitly; discovery
  and onboarding remain separate behavior.

## Compatibility consequences

- Existing coordination schemas already use UUID project references and do not
  change.
- Existing `records validate` remains repository-agnostic. The explicit
  `repo validate` boundary adds manifest-backed project validation.
- Renaming `humanName` changes neither canonical coordination records nor their
  revision digests.
- Automatic identity minting and onboarding are deferred to AM-9.
