# Versioning and launch policy

Artifact Memory versions five surfaces independently:

| Surface | Version rule | Compatibility boundary |
| --- | --- | --- |
| Protocol | Product protocol generation such as `v0`. | Describes the supported product contract set; it is not an implementation API promise. |
| Schemas | Every schema identifier ends in its own `/vN`. | Breaking field, identity, authority, or required-behavior changes require a new schema version. |
| Reference CLI/package | Python package semantic version, currently `0.1.0.dev0`. | Before 1.0, implementation APIs may change; versioned record and receipt contracts are not silently reinterpreted. |
| Adapters/providers | Provider-owned contract `/vN` plus the Artifact Memory adapter-manifest version. | Provider schemas remain provider contracts and never become core schemas implicitly. |
| Fixtures/receipts | Each vector and receipt schema has its own `/vN`. | Checked receipts bind exact fixture bytes and cannot be carried forward after vectors change. |

Unknown optional extensions are preserved without interpretation. Unknown
required extensions fail closed. A breaking change requires a new version plus
an explicit migration or rejection rule.

Release manifests retain the legacy `manifest_schema` field and may also list
`supported_manifest_schemas`. Preview preparation derives that list from the
exact source commit, so an archive advertises adapter-manifest v2 only when its
schema is actually present while keeping v1 discoverable.

Once a supported surface is deprecated, Artifact Memory retains it for at
least one subsequent minor release and 90 days after the public deprecation
announcement, whichever is later. Security fixes may reject unsafe input
immediately, but the rejection and migration boundary must be documented.

## Preview versus release

A development preview is not a release. `release-manifest/v2` requires preview
manifests to be `unsigned-preview` with no tag, fingerprint, or key generation.
A manifest may claim `status: release` only with an owner-signed annotated tag,
the dedicated SSH Ed25519 public fingerprint and key generation, and a tag that
matches the release identifier.

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
3. a canonical `SHA256SUMS` asset covering every release asset except itself;
4. a final pre-public history and repository-surface audit, including Actions
   history and artifact review;
5. after explicit owner visibility approval, an anonymous clone/install/verify
   smoke using the quickstart and restoration of public push rules; if either
   fails, stop release publication and return the repository to private while
   correcting the failure;
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
