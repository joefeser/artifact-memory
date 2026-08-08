# Public-readiness audit record

This record is a repeatable audit procedure and evidence summary. It does not
authorize a tag or release publication, authenticate an owner signing key, or
prove that a bounded scanner can recognize every form of protected material.

## Current public evidence

On 2026-08-08, owner-authorized publication and bounded post-visibility
verification completed against exact `main` commit
`e74b87e0cb81baa2a56b59281d724413a19204d9`. Two fresh anonymous clones
reproduced external receipt
`public-safety-receipt://194e6ecf3f95b00844f8e93402e495766583e4f69b8a326841f617ba9748a555`.
The checked source passed 531 tests, 231 public JSON validations, aggregate
conformance, compilation, `git fsck`, install, CLI, and packaged-schema smoke
checks. Exact release-preview preparation also passed as
`release-preparation-receipt://56b5865ebdde2219d046dfd984030aac04875242961ba25da7b8d7be28017fc7`.

The public repository has protected `main` and `dev` branches. Both reject
force pushes and deletions, require pull requests, dismiss stale review state,
require resolved conversations, enforce their rules for administrators, and
require the public-safety plus macOS, Ubuntu, and Windows probe checks. Only Joe
has direct write access. Secret scanning, push protection, vulnerability
alerts, and private vulnerability reporting are enabled. Merge commits are
enabled while squash and rebase merges are disabled. No tag, release, or
retained Actions artifact existed at the audited head.

The visibility and public-control gates are complete; their accepted evidence
is recorded in the closed public-readiness issue. They do not establish an
owner-signed `v0.1.0` release. Final release preparation must repeat the relevant
source/history checks against its own exact commit, bind the final manifest to
the dedicated owner-signed tag, and verify that tag before publishing release
assets.

## Historical pre-public evidence

### First real off-machine custody proof

On 2026-08-06, an external owner attestation recorded that an authorized
private dogfood run exercised the configured
logical endpoint `endpoint://joe-home-proxmox-vault-1`. It registered two exact
public-source artifacts in an owner-local private vault, created and verified a
Git bundle, admitted only explicit vault and knowledge-store inputs, wrote one
non-empty encrypted restic snapshot through the restricted SFTP fallback, read
every repository data blob, and restored the exact snapshot into a new isolated
target. The restored allowlist contained ten source files; four canonical
artifact/version records validated, two content objects matched their digests,
and the restored Git bundle verified. No application home, credential, raw task
transcript, browser state, or machine-local resolver configuration was admitted.

The dedicated guest uses ZFS-backed storage with a separately controlled weekly
snapshot timer and bounded retention. A manual server-controlled snapshot after
the first remote write also succeeded, so the initial proof has a post-write
storage rollback point without granting snapshot control to the backup client.
The endpoint proves off-machine custody on the same owner-controlled premises,
not geographically off-site protection. Recovery material remains
owner-controlled and was neither requested nor inspected; the public evidence
therefore does not prove key recoverability. The repository validates the
sanitized attestation's exact public fields and rejects machine-binding forms;
it cannot independently replay or establish the private operational facts.
Private evidence retains the exact
snapshot, manifest, backup, and restore bindings, including validated private
receipts where the published contracts apply. The public-safe summary is
`evidence/sanitized/custody/v1/receipt.md`.

### Post-PR #69 non-VM refresh

The non-VM audit was refreshed on 2026-08-05 against exact private `dev`
commit `08ecc43bf2565aceb25ae4a560bed92e4260b1f7`. Two independent fresh clones
reproduced external receipt
`public-safety-receipt://83700206fb2ae5f8aea6c236692188415c9c8606c8ef630da96d91e422778c6e`:

- 219 reachable commits, 3,041 historical Git objects, and 497 current paths;
- exactly two remote refs (`main` and `dev`), with no tags or releases;
- clean detached index/worktree scope and exact receipt replay in clone two;
- 37 issues and 29 pull requests, with four issues and no pull requests open;
- 208 issue comments, 780 reviews, 1,071 inline review comments, and three
  Discussions were inventoried;
- all 360 retained Actions log archives were readable; 356 runs succeeded and
  four historical PR-head runs failed before later corrective commits; no log
  contained a private-key header, credential-shaped token, bearer credential,
  or owner workstation path;
- the only high-confidence matches in GitHub prose were bot-authored reviews
  quoting the repository's safety patterns or synthetic scanner diff hunks;
  they are policy/test descriptions, not observed credentials;
- no Actions artifacts exist; merge commits are enabled while squash/rebase
  are disabled; the default branch is `main`; merged branches auto-delete;
  Pages, wiki, and Projects are disabled.

At that historical point the repository remained private and the private-plan
branch/security controls were unavailable. Those observations were superseded
by the current public evidence above. The refresh was not a signed release or a
substitute for #21 remote-custody evidence.

### Earlier baseline

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
  allowlisted exception for real vault data. The earlier sanitized
  Codex-history dogfood receipt excludes source text, raw history, record
  content, machine paths, credentials, and custody details. The later custody
  attestation intentionally publishes only bounded logical endpoint, transport,
  and storage-boundary metadata while excluding private machine bindings.
- The canonical Apache License 2.0 text and a separate copyright `NOTICE` are
  present. Security policy, contribution guidance, support scope, quickstart,
  release notes, versioning policy, roadmap, and historical WhereAreMyFiles
  clean-rewrite lineage are documented.
- Real macOS, Linux, and Windows CI receipts cover the supported platform
  matrix. Performance claims remain descriptive and tied to the checked
  synthetic profile rather than universal guarantees.

This dated snapshot describes the accepted `dev` base before the audit patch;
it is not the final visibility-approval receipt. The later public evidence above
supersedes it and identifies the external
`artifact-memory/public-safety-receipt/v1` consumed for owner approval. Such a
receipt binds its own candidate and HEAD commits, scanned remote refs and tags,
commit/object/path counts, clean index/worktree scope, and canonical receipt
identity.

The contract has checked synthetic machine and human evidence at
`fixtures/synthetic/public-safety/v1/expected-receipt.json` and
`fixtures/synthetic/public-safety/v1/receipt.md`. Those fixtures are reviewable
contract evidence, not visibility approval. The accepted real receipt remains
external so recording it did not change the clone it claimed was clean.

These checks are high-confidence guardrails, not proof of absence. Public
visibility does not remove the requirement for human review of each exact
release candidate and its repository settings before publication.

## Remaining release gates

The following remain incomplete and must not be inferred from public visibility
or the earlier unsigned preview:

- issue #21 has an external owner attestation backed by owner-controlled private
  evidence for the first encrypted write, full-data integrity verification,
  isolated restore, verified Git bundle, and post-write storage snapshot. The
  repository gate validates the sanitized attestation's exact fields and
  machine-binding exclusions but cannot independently verify those private
  operations. Merging the attestation records, rather than proves, the observed
  completion; ongoing monthly checks and quarterly restore rehearsals remain
  owner operations rather than release-time claims;
- the final candidate must repeat the relevant Git, GitHub prose, Actions
  log/artifact, release, tag, and settings audit after its last merge;
- Joe must provide the dedicated release-signing public key and fingerprint,
  add it to GitHub as a signing key, and personally create the owner-signed
  annotated tag; agents must not receive or invoke the private key;
- the exact signed candidate must pass isolated verification and an anonymous
  clone, `git fsck`, install, test, checksum, and tag-verification replay;
- Joe must separately authorize tag and GitHub release publication. A failed
  verification stops publication while the candidate is corrected;
- keyless build and artifact attestations remain deferred pending a reviewed
  public workflow.

## Final release-candidate procedure

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
   public settings state and owner release decision without recording secrets.
   Do not compare a prose count tuple from another commit.

## Signed-release anonymous verification

After Joe authorizes publication of the owner-signed tag, use a machine or
environment with no repository credentials or vault mounts. First configure
SSH signature verification with the owner-published release public key as
described in `ssh-signing-key-policy.md`, then run:

```shell
set -eu
git clone --no-checkout https://github.com/joefeser/artifact-memory.git artifact-memory-public-check
cd artifact-memory-public-check
git fetch --tags --force
git verify-tag v0.1.0
git checkout --detach v0.1.0
git fsck --full --no-reflogs
python -m pip install --no-deps .
release_manifest_path=/external/release/release-manifest.json
release_verification_path=/external/audit/release-candidate-verification.json
: "${ARTIFACT_MEMORY_RELEASE_OWNER_FINGERPRINT:?set from the owner-published release policy}"
artifact-memory verify-release-candidate "$release_manifest_path" --tag v0.1.0 --repo . --owner-fingerprint "$ARTIFACT_MEMORY_RELEASE_OWNER_FINGERPRINT" --isolated-checkout --json > "$release_verification_path"
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
the verified SSH fingerprint must exactly match the manifest. The verifier
does not parse human diagnostics: it filters the configured allowed-signers
file to the independently supplied owner-published Ed25519 fingerprint,
rejects any different fingerprint claimed by the candidate manifest, verifies
one pinned tag object against that key, and compares initial/final ref, commit,
and detached-HEAD endpoints. The caller must assert exclusive control of this
fresh checkout; endpoint equality does not detect an A→B→A mutation. This
behavior is
the `git-verify-tag-filtered-allowed-signers-v1` profile and is covered by a
real ephemeral Git/SSH signing regression test. Git SHA-256 object-format
repositories receive an explicit unsupported outcome in v0. Its pass evidence
is a digest-bound
`artifact-memory/release-candidate-verification-receipt/v1` containing that
fingerprint, signed tag object, exact manifest digest, key generation,
authority boundary, caller-asserted isolation, endpoint-only concurrency scope,
and explicit unevaluated owner-authorization and repository-settings gates.
Preserve the external
receipt with the release audit evidence; the second command rejects schema,
duplicate-key, canonical-identity, or internal-coherence tampering and reports
`integrity-verified`; it does not replay Git, signature, manifest, package, or
owner-policy verification and therefore does not independently establish the
receipt's factual claims. The
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

If GitHub cannot enforce or positively report any required control, the
settings gate fails: stop release publication rather than recording the control
as “unavailable.”
