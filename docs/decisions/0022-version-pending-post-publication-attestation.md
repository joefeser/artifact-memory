# 0022: Version pending post-publication attestation evidence

## Status

Accepted, 2026-08-11, for issue #98.

## Context

The released v2 manifest describes keyless attestations as
`deferred-public-workflow-review`. That wording is immutable historical
compatibility evidence for v0.1.0 and v0.1.1, but the public workflow review is
now complete. A future release candidate still cannot truthfully claim an
attestation exists because the workflow runs only after publication.

## Decision

- Keep every released v1/v2 schema and fixture byte unchanged and readable.
- Use the v3 release-candidate family for future release preparation and
  verification. Unsigned previews remain on their existing contracts.
- Restrict v3 manifests to `status: release-candidate` and
  `attestations.state: pending-post-publication`.
- State that keyless build/artifact attestation is required after publication
  and that its subject-bound bundle is external evidence.
- Receipt preparation and signed-candidate verification separately. The
  preparation receipt records that attestation evidence is absent; the
  verification receipt records that attestation evidence was not evaluated.
- Reject candidate claims of `published`, `verified`, an attestation URL, or an
  embedded bundle. A later workflow run never rewrites signed candidate bytes.

## Compatibility

The v1/v2 readers, semantic outcomes, schemas, and synthetic fixtures remain
supported. Release preparation selects the frozen contracts for v0.1.0 and
v0.1.1 and the v3 candidate family for later package versions. Readers
negotiate by exact schema ID; no v2 payload is interpreted as v3.

## Authority and limitations

The owner-signed annotated SSH tag remains release authority. A v3 pending
state is neither publication approval nor proof that an attestation exists or
passed. A later external Sigstore bundle may prove workflow identity and exact
subject digests, but it does not prove owner approval, claim truth, repository
settings, future availability, or any execution, mutation, merge, deployment,
spending, credential, disclosure, or declassification authority.

This decision does not run or backfill a workflow, create or push a tag,
publish a release, access a private key, or change repository visibility.

## Evidence

- GitHub issue: <https://github.com/joefeser/artifact-memory/issues/98>
- Prior workflow decision:
  `docs/decisions/0021-attest-verified-release-assets-after-publication.md`
- Schemas: `artifact_memory/schemas/core/release-manifest.v3.schema.json` and
  v3 candidate preparation/verification receipt schemas
- Synthetic fixture:
  `fixtures/synthetic/release/v0-pending-candidate-manifest.v3.json`
- Tests: `tests/test_release_manifest.py`,
  `tests/test_release_preparation.py`, and `tests/test_release_candidate.py`
