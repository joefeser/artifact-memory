# Versioning and launch policy

Artifact Memory versions five surfaces independently:

| Surface | Version rule | Compatibility boundary |
| --- | --- | --- |
| Protocol | Product protocol generation such as `v0`. | Describes the supported product contract set; it is not an implementation API promise. |
| Schemas | Every schema identifier ends in its own `/vN`. | Breaking field, identity, authority, or required-behavior changes require a new schema version. |
| Reference CLI/package | Python package semantic version, currently `0.1.0`. | Before 1.0, implementation APIs may change; versioned record and receipt contracts are not silently reinterpreted. |
| Adapters/providers | Provider-owned contract `/vN` plus the Artifact Memory adapter-manifest version. | Provider schemas remain provider contracts and never become core schemas implicitly. |
| Fixtures/receipts | Each vector and receipt schema has its own `/vN`. | Checked receipts bind exact fixture bytes and cannot be carried forward after vectors change. |

Unknown optional extensions are preserved without interpretation. Unknown
required extensions fail closed. A breaking change requires a new version plus
an explicit migration or rejection rule.

Release manifests retain the legacy `manifest_schema` field and may also list
`supported_manifest_schemas`. Preview preparation derives that list from the
exact source commit and advertises a version only when the candidate bytes match
the runtime's immutable versioned schema contract. A matching filename alone is
not support evidence. Isolated v1-only and no-adapter commit fixtures prove that
discovery does not fall back to the running checkout.

The v1 adapter manifest schema remains the release surface's required primary
contract; a candidate whose exact commit supports only v2 causes preparation
to fail closed with `release-preparation-adapter-primary-schema-unsupported`.
This is a permanent rejection for that commit, not a transient or retryable
failure: the candidate tree must retain the v1 adapter manifest schema
alongside v2 (v2-only candidates cannot yet publish previews or releases).
Migrating a v2-only candidate requires restoring the checked-in v1 schema
file at that exact commit before preparation is retried. Release conformance
independently re-derives the supported adapter manifest schema set from the
exact source commit and rejects a manifest whose `manifest_schema` or
`supported_manifest_schemas` claim does not match that reproduction, even
when `supported_manifest_schemas` is absent from the manifest.

Once a supported surface is deprecated, Artifact Memory retains it for at
least one subsequent minor release and 90 days after the public deprecation
announcement, whichever is later. Security fixes may reject unsafe input
immediately, but the rejection and migration boundary must be documented.

## Preview versus release

A development preview is not a release. `release-manifest/v2` requires preview
manifests to be `unsigned-preview` with no tag, fingerprint, or key generation.
Preparation emits `status: release-candidate` and
`signature.state: pending-owner-signature`, even though it records the dedicated
SSH Ed25519 public fingerprint, key generation, and intended matching tag. New
candidate key-generation labels use 1–64 ASCII letters, digits, dots,
underscores, or hyphens and begin with a letter or digit. Historical
`status: release` records retain their published non-empty-string compatibility.
A standalone manifest cannot authenticate itself. Existing v2 `status: release`
records remain structurally and semantically readable for compatibility, while
the generic validation command explicitly documents that it does not verify an
owner signature or accept release evidence. Its stable v0 result shape is not
expanded with authenticity claims. The signed-candidate verifier accepts the
immutable pending candidate and emits a digest-bound v2 verification receipt;
those two records establish the release evidence without rewriting bytes after
signing. A valid v2 `status: release` record is live-verifiable only when its
artifact provenance opts into the same strict replay profile. Older free-form
provenance remains structurally readable but returns the explicit
`release-candidate-historical-asset-replay-unsupported` outcome instead of a
misleading verification receipt. Historical v1 verification receipts remain
integrity-readable but do not contain the mandatory staged-asset replay evidence
added in v2.

The published v2 schema remains able to read its earlier permissive fingerprint
shape, but such a value is not releasable evidence. Semantic validation returns
`release-fingerprint-migration-required`; migration means replacing the claim
with the canonical 43-character unpadded fingerprint obtained independently
from the owner-published key, then regenerating and owner-signing the manifest
binding. Candidate verification reports a noncanonical claim as
`release-candidate-owner-fingerprint-invalid` and never normalizes it silently.

A public release requires one reviewed exact-head set containing:

1. an owner-signed annotated `v0.1.0` tag made with the dedicated release key;
2. a v2 release manifest naming the source commit and reproducible source-tree
   digest, all five versioned surfaces, artifacts, byte sizes, SHA-256 digests,
   checksum manifest, provenance, signature generation, and limitations;
3. a canonical `SHA256SUMS` asset covering every manifest-listed release asset
   except itself, followed by verifier replay of the exact staged archive and
   release notes against both their checksums and the tagged source;
4. a final public history and repository-surface audit, including Actions
   history and artifact review;
5. an anonymous clone/install/verify smoke using the quickstart and confirmed
   public branch/security controls; repeat the smoke for the signed tag before
   release publication, and stop publication while correcting any failure;
6. release notes, support scope, roadmap, known gaps, and explicit historical
   WhereAreMyFiles lineage and attribution.

No unsigned tag, generated index, CI success, digest, preview receipt, or agent
action substitutes for owner signing or publication authority. Keyless build
and artifact attestations are added only after public workflow review supports
them.

## Reproducible unsigned preview

The checked v2 preview reproduces a source archive, `sha256sum-v1` file, Git
tree digest, canonical sorted-schema-ID inventory digest, and CLI package
version from an exact public-safe commit. It remains explicitly unsigned and
not authorized for publication:

```sh
python3 scripts/run_release_conformance.py --check
```

Prepare the same unsigned, non-authorizing asset set for an exact candidate in
an empty directory outside the repository:

```sh
python3 scripts/prepare_release_preview.py \
  --candidate <full-candidate-commit> \
  --repo . \
  --out <external-empty-directory>
```

The command rejects symbolic or abbreviated revisions, in-repository output,
and non-empty output directories. It writes a reproducible source tar,
`SHA256SUMS`, v2 preview manifest, and machine/human preparation receipts. It
does not generate or use a key, create a tag, publish assets, change visibility,
or grant release authority.

The v0 preparation receipt accepts package versions in `X.Y.Z` or
`X.Y.Z.devN` form. `SHA256SUMS` covers every manifest-listed release artifact
except the checksum file itself. The release manifest and preparation receipts
are evidence metadata bound to their own canonical/digest identities; they are
not silently claimed as checksum-covered release assets.

Preparation stages every output in a private sibling directory, rereads the
exact bytes, and atomically exposes the complete directory. Conflicting output
paths, symlinks, partial writes, or a changed destination fail closed without
leaving a passing receipt in the requested output directory.

The final release must be regenerated from the owner-approved release commit;
preview checksums and receipts cannot be relabeled as release evidence.

## Exact release-candidate preparation

After the reviewed source commit carries package version `0.1.0` and final
release notes, prepare the exact candidate in a new external directory using
only the owner's independently published public fingerprint and key-generation
label:

```sh
python3 scripts/prepare_release_candidate.py \
  --candidate <full-candidate-commit> \
  --repo . \
  --out <external-empty-directory> \
  --owner-fingerprint 'SHA256:<canonical-public-fingerprint>' \
  --key-generation 'generation-1'
```

The command deterministically writes the source tar, exact release-note bytes,
`SHA256SUMS`, the v2 pending release-candidate manifest, and machine/human candidate
preparation receipts. The checksum file covers the source tar and release
notes. The preparation receipt separately binds the release manifest and
prints the exact `Artifact-Memory-Manifest-SHA256` trailer required in the
annotated tag message.

Use `--plain-text` to print the exact persisted human receipt. Independent
readers can run
`artifact-memory validate-release-candidate-preparation-receipt <receipt.json>`
for that canonical rendering, or add `--json` for a machine-readable
schema/identity/trailer-coherence result. Neither mode verifies an owner
signature.

The manifest remains `status: release-candidate` with
`signature.state: pending-owner-signature`; its companion preparation receipt remains
`signature_verification_state: pending-owner-signature` and
`publication_state: not-authorized`. A standalone manifest therefore cannot claim
that its owner signature has already been verified. Preparation accepts no private-key path or
secret, does not invoke signing, and creates no tag or release. The owner must
independently confirm the public fingerprint, sign an annotated tag containing
the exact printed trailer, and separately authorize publication. The existing
`artifact-memory verify-release-candidate` command then verifies the tag,
manifest binding, commit identity, package version, signer fingerprint, source
tree, every staged asset against the manifest and canonical `SHA256SUMS`, exact
archive and release-note reproduction from the tagged commit, and the
isolated-checkout boundary before publication. Pass the external candidate
directory with `--asset-dir`; missing, substituted, or concurrently changed assets
fail closed.

Keyless build and artifact attestations remain explicitly
`deferred-public-workflow-review`; they are not implied by the source release
or owner signature.
