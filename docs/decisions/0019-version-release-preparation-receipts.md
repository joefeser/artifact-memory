# 0019 — Version release-preparation receipts after v0.1.0

- Status: accepted
- Date: 2026-08-08
- Issue: <https://github.com/joefeser/artifact-memory/issues/85>

## Context

The first release deliberately pinned preview and candidate preparation receipt
v1 to v0.1.0. That made the initial proof exact, but reusing v1 for v0.1.1 would
either fail its constant fields or silently reinterpret a published contract.
The release manifest and signed-candidate verifier already support semantic
`X.Y.Z` identities.

## Decision

Keep both v1 preparation schemas and all v0.1.0 fixtures unchanged. Add v2
preview and candidate preparation receipts with semantic-version-shaped fields
and enforce package-version, release-ID, and tag coherence in semantic
validation. Derive archive and notes names from the exact committed package
version. Emit v1 only for the historical 0.1.0 identity and v2 thereafter.

Preparation continues to accept only the public fingerprint and key-generation
label. Owner signing, tag creation, publication, visibility, and deployment
remain outside preparation authority.

## Consequences

Existing v0.1.0 receipts remain byte-for-byte replayable. Subsequent releases
gain deterministic preparation without editing old schemas. A mismatched
package version, release ID, tag, runtime version, notes path, or receipt version
fails closed. Adding two schemas changes the exact schema-inventory digest for
new release candidates as intended.

## Evidence

- `artifact_memory/schemas/core/release-preparation-receipt.v2.schema.json`
- `artifact_memory/schemas/core/release-candidate-preparation-receipt.v2.schema.json`
- `tests/test_release_preparation.py`
- `docs/release/v0.1.1-release-notes.md`
