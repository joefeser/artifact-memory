# Public-readiness audit record

This record is a repeatable audit procedure and current evidence summary. It
does not itself change repository visibility, authorize publication, or prove
that a bounded scanner can recognize every form of protected material.

## Current pre-public evidence

Evidence was refreshed on 2026-08-04 from private `dev` commit
`68fcd19e8678338cfa265dff84c843edfd4de13a` after all implementation PRs were
merged:

- The complete reachable Git-object scan passed over 184 commits, 2,330
  historical objects, and 441 current paths. `git fsck` found no integrity
  error in reachable history; local dangling worktree objects are not remote
  refs or public repository content.
- The provider-free suite passed 364 tests, the aggregate conformance suite
  passed, 183 public JSON files validated, compilation passed, and
  `git diff --check` was clean.
- GitHub exposes only `main` and `dev`. No tags, releases, or retained Actions
  artifacts exist. The repository remains private and has no active branch
  protection under the current private personal-repository plan.
- All 293 retained Actions log bundles were readable. A bounded scan found no
  owner workstation path, authorized private-dogfood session identifier,
  private-key header, GitHub/OpenAI/AWS token shape, or bearer credential. Of
  those runs, 289 succeeded and four historical PR-head runs failed; later
  commits corrected those failures and the current `dev` CI run succeeds.
- Repository prose inspection covered 61 issue/PR records, 185 top-level
  comments, 792 inline review comments, 590 reviews, and all three Discussions.
  Two owner-authored personal worktree paths were replaced with source-neutral
  placeholders. Remaining path/token-pattern matches are synthetic examples or
  reviewer descriptions of the safety rules, not observed credentials or
  private resolver data.
- The fixtures are declared synthetic and the current tree contains no
  allowlisted exception for real vault data. The sole sanitized private-dogfood
  receipt excludes source text, raw history, record content, machine paths,
  credentials, and custody details.
- The canonical Apache License 2.0 text and a separate copyright `NOTICE` are
  present. Security policy, contribution guidance, support scope, quickstart,
  release notes, versioning policy, roadmap, and historical WhereAreMyFiles
  clean-rewrite lineage are documented.
- Real macOS, Linux, and Windows CI receipts cover the supported platform
  matrix. Performance claims remain descriptive and tied to the checked
  synthetic profile rather than universal guarantees.

These checks are high-confidence guardrails, not proof of absence. A human must
still review the exact final public candidate and repository settings before
approving visibility.

## Remaining gates

The following are intentionally incomplete and must not be inferred from this
pre-public pass:

- issue #21 still needs the first encrypted write to the approved
  `joe-home-proxmox-vault-1` guest, integrity verification, and an isolated
  restore receipt after the owner confirms its address, account, and storage;
- the final candidate must repeat the Git, GitHub prose, Actions log/artifact,
  release, tag, and settings audit after its last merge;
- Joe must provide the dedicated release-signing public key and fingerprint,
  add it to GitHub as a signing key, and personally create the owner-signed
  annotated tag; agents must not receive or invoke the private key;
- Joe must explicitly approve the visibility change after reviewing the final
  audit. The repository remains private until that approval;
- after visibility changes, an anonymous environment must clone, run
  `git fsck`, install, test, and verify the exact release candidate, and public
  branch protection/security settings must be restored before release
  publication. Failure stops publication and returns the repository to private.

## Final pre-public procedure

1. Freeze the exact candidate commit and enumerate every remote branch, tag,
   release, Actions run/log/artifact, issue, PR, review, comment, Discussion,
   and enabled repository feature.
2. Rerun the full-history scanner, public JSON validation, unit tests,
   conformance, compilation, whitespace check, and `git fsck` from a fresh
   full-history clone of the private repository.
3. Review every scanner match by source and classification. Synthetic examples
   and reviewer descriptions must be distinguishable from real protected
   material; ambiguity fails closed.
4. Confirm fixtures are newly authored synthetic data and that no real vault
   record, raw conversation, attachment, customer material, private strategy,
   credential, resolver path, hostname, or bearer URL is present.
5. Verify Apache-2.0 detection, attribution/lineage, release notes, support,
   security reporting, contribution policy, and final SHA-256 release assets.
6. Record the exact commit, counts, command results, reviewed surfaces, known
   gaps, and Joe's explicit visibility decision without recording secrets.

## Post-visibility anonymous clone

Only after Joe explicitly approves and performs the visibility change, use a
machine or environment with no repository credentials or vault mounts:

```shell
git clone https://github.com/joefeser/artifact-memory.git artifact-memory-public-check
cd artifact-memory-public-check
git fsck --full --no-reflogs
python3 -m unittest discover -s tests -v
bash scripts/run_conformance.sh
python3 -m artifact_memory version --json
```

Inspect the clone for real paths, credentials, customer material, raw task
transcripts, generated-only knowledge, unexpected network access, and mutation
behavior. Record the source commit and command results. Restore branch
protection, push rules, secret scanning, and private vulnerability reporting as
available. Do not publish the release if this smoke or settings restoration
fails.
