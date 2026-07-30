# Versioning and launch policy

Artifact Memory has three separately versioned surfaces:

- protocol and schema identifiers, such as `artifact-memory/knowledge-record/v1`;
- adapter/provider contracts, which retain their owning provider boundary;
- the reference implementation, currently `0.1.0.dev0` (development
  metadata; it is not a release).

Adding optional fields or extensions must preserve unknown optional data and
must not reinterpret unknown required behavior. Breaking schema or authority
changes require a new schema version and a documented migration or rejection
rule. A v0 implementation does not promise stable APIs beyond the contracts
explicitly marked supported.

A release candidate is not a release. A public release requires, in one
reviewed change set:

1. a signed `v0.1.0` tag made with the owner's controlled signing key;
2. a release manifest naming the source commit, protocol versions, artifacts,
   SHA-256 checksums, and provenance;
3. an anonymous clone/install/verify smoke using the quickstart;
4. the public-history and visibility checklist in
   `docs/release/public-readiness-audit.md`;
5. explicit release notes, support scope, limitations, and known gaps.

No unsigned tag, generated index, CI success, or valid digest is a substitute
for the owner's signing, publication, or authority decision.

The checked-in preview manifest demonstrates the intended checksum and
provenance shape without pretending that an unsigned preview is a release:
`fixtures/synthetic/release/v0-preview-manifest.json`.
