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
  errors in reachable history; local dangling worktree objects are not remote
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

This dated snapshot describes the accepted `dev` base before the audit patch;
it is not the final visibility-approval receipt. Final approval consumes one
external `artifact-memory/public-safety-receipt/v1` generated for the frozen
candidate after the last merge. The receipt binds its own candidate and HEAD
commits, scanned remote refs and tags, commit/object/path counts, clean
index/worktree scope, and canonical receipt identity.

The contract has checked synthetic machine and human evidence at
`fixtures/synthetic/public-safety/v1/expected-receipt.json` and
`fixtures/synthetic/public-safety/v1/receipt.md`. Those fixtures are reviewable
contract evidence, not visibility approval. The real final receipt remains
external so recording it cannot change the clone it claims was clean.

These checks are high-confidence guardrails, not proof of absence. A human must
still review the exact final public candidate and repository settings before
approving visibility.

## Remaining gates

The following are intentionally incomplete and must not be inferred from this
pre-public pass:

- issue #21 still needs the first encrypted write to the approved logical
  endpoint `endpoint://joe-home-proxmox-vault-1`, integrity verification, and
  an isolated restore receipt after the owner confirms its guest address,
  account, and storage;
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

1. From a clean full-history clone, detach `HEAD` at the exact owner-approved
   candidate and enumerate every remote branch, tag, release, Actions
   run/log/artifact, issue, PR, review, comment, Discussion, and enabled
   repository feature.
2. Generate the frozen Git receipt outside the clone, substituting the full
   candidate commit for `<candidate-sha>` and an external path for
   `<receipt-path>`:

   ```shell
   python scripts/public_safety_check.py --candidate <candidate-sha> --receipt-out <receipt-path> > <human-receipt-path>
   ```

   Both output paths must be outside the audited clone. The JSON and Markdown
   are produced from the same validated receipt body.

3. In a second clean full-history clone detached at the same candidate, rerun
   with `--expect-receipt <receipt-path>`. The command fails unless HEAD, the
   complete remote-ref/tag set, commit/object/path counts, and clean working
   scope reproduce exactly. Any mismatch blocks approval.
4. Rerun public JSON validation, unit tests, conformance, compilation,
   whitespace checks, and `git fsck` from that replay clone.
5. Review every scanner match by source and classification. Synthetic examples
   and reviewer descriptions must be distinguishable from real protected
   material; ambiguity fails closed.
6. Confirm fixtures are newly authored synthetic data and that no real vault
   record, raw conversation, attachment, customer material, private strategy,
   credential, resolver path, hostname, or bearer URL is present.
7. Verify Apache-2.0 detection, attribution/lineage, release notes, support,
   security reporting, contribution policy, and final SHA-256 release assets.
8. Record the frozen external receipt and its human rendering (using the same
   deterministic form demonstrated by `fixtures/synthetic/public-safety/v1`),
   successful replay result, reviewed GitHub surfaces, known gaps, and Joe's
   explicit visibility decision without recording secrets. Do not compare a
   prose count tuple from another commit.

## Post-visibility anonymous clone

Only after Joe explicitly approves and performs the visibility change, use a
machine or environment with no repository credentials or vault mounts. First
configure SSH signature verification with the owner-published release public
key as described in `ssh-signing-key-policy.md`, then run:

```shell
git clone --no-checkout https://github.com/joefeser/artifact-memory.git artifact-memory-public-check
cd artifact-memory-public-check
git fetch --tags --force
git verify-tag v0.1.0
git checkout --detach v0.1.0
git fsck --full --no-reflogs
python -m pip install --no-deps .
release_manifest_path=/external/release/release-manifest.json
release_verification_path=/external/audit/release-candidate-verification.json
artifact-memory verify-release-candidate "$release_manifest_path" --tag v0.1.0 --repo . --json > "$release_verification_path"
artifact-memory validate-release-candidate-receipt "$release_verification_path" --json
python tests/smoke_installed_package.py
python -m unittest discover -s tests -v
```

The executable candidate verifier fails unless the manifest's exact SHA-256 is
present once in the signed annotated tag as an
`Artifact-Memory-Manifest-SHA256:` trailer, its declared source-tree digest
matches the tagged commit's full tree, and the signed tag target, detached
HEAD, manifest `release_id`, manifest source commit, manifest package version,
and installed package version all identify `v0.1.0` / `0.1.0`. Every Git call
is scoped to the explicit checkout, the tag is confirmed as annotated, and
the verified SSH fingerprint must exactly match the manifest. SSH diagnostic
parsing is pinned to the `git-verify-tag-ssh-c-locale-v1` compatibility profile
and fails closed for unsupported output. Its pass evidence
is a digest-bound
`artifact-memory/release-candidate-verification-receipt/v1` containing that
fingerprint, signed tag object, exact manifest digest, key generation,
authority boundary, and limitations. Preserve the external
receipt with the release audit evidence; the second command rejects schema,
duplicate-key, or canonical-identity tampering. The
installed-package smoke runs the console script and packaged-schema checks from
a temporary directory outside the source checkout.

The newly authored synthetic contract evidence at
`fixtures/synthetic/release/v0-release-candidate-verification-receipt.json` and
its `.md` rendering demonstrates the receipt shape without claiming that a real
key, tag, release, or visibility decision exists.

Inspect the clone for real paths, credentials, customer material, raw task
transcripts, generated-only knowledge, unexpected network access, and mutation
behavior. Record the tag, source commit, signer fingerprint, and command
results. Before release publication, record positive API or settings-page
evidence for every control below:

- only merge commits are enabled; squash and rebase merges are disabled;
- `main` and `dev` reject force pushes and deletions, require pull requests,
  dismiss stale approvals, require conversation resolution, enforce rules for
  administrators, and require the CI public-safety job plus all three platform
  jobs;
- direct pushes and merges to `main` and `dev` are restricted to Joe, with
  `main` promotion remaining a separate human-mediated pull request;
- secret scanning, secret-scanning push protection, and private vulnerability
  reporting are enabled;
- the default branch is `main`, head branches delete after merge, and no Pages,
  wiki, or Projects surface is enabled unintentionally.

If GitHub cannot enforce or positively report any required control on the
public repository plan, the settings gate fails: stop publication and return
the repository to private rather than recording the control as “unavailable.”
