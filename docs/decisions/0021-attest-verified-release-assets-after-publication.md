# 0021: Attest verified release assets after publication

## Status

Accepted, 2026-08-11, for issue #96.

## Context

Artifact Memory releases already use an owner-controlled SSH Ed25519 key,
annotated tags, a signed manifest-digest trailer, canonical SHA-256 manifests,
deterministic source archives, and exact replay receipts. Keyless build and
artifact attestations were deferred until the repository became public and a
workflow could be reviewed.

GitHub's public artifact-attestation service can bind release subject digests
to the identity of a GitHub-hosted Actions workflow using a short-lived
Sigstore certificate. That identity is useful supplemental provenance, but it
is not the owner's release-signing identity and does not establish trust in the
release's claims.

## Decision

- Run the attestation workflow automatically only after a future release is
  published. Manual exact-tag dispatch exists for separately authorized
  recovery or historical backfill.
- Pin the control checkout to `github.workflow_sha` and use a separate exact-tag
  checkout. Verify the annotated tag with the control checkout's pinned public
  key before executing tagged release code. Then reproduce candidate assets,
  repeat the full owner-signature and release-contract verification, download
  published assets, and require byte-for-byte equality and an exact file set
  before attestation.
- Attest all published assets, including the manifest and preparation and
  verification receipts, rather than only the files listed by `SHA256SUMS`.
- Commit only the generation-1 public key. The workflow receives no private
  key, signing secret, publication credential, or owner-approval token.
- Pin GitHub actions to reviewed immutable commits. The initial pins are
  `actions/checkout` `08eba0b27e820071cde6df949e0beb9ba4906955`
  (`v4.3.0`), `actions/setup-python`
  `ece7cb06caefa5fff74198d8649806c4678c61a1` (`v6`), and
  `actions/attest` `1e69f48acb82d1966a394da916b4c1698aa569d6`
  (`v4.2.2`). All three are MIT-licensed. Their reviewed license-file SHA-256
  values are, respectively,
  `3e855ffa704114a51628ef8f0bf3aeb41728adf9d9070e263bf58aa5640b0eb5`,
  `7d070f6b64d9bcc530fe99cc21eaaa4b3c364e0b2d367d7735671fa202a03b32`,
  and `32d0bae2419f014f5066af5915264c966efdb7b6e7fe8f90cf87dc75c5a8d6d0`.

## Compatibility

No released Artifact Memory schema or fixture changes. The v2 release
manifest's `deferred-public-workflow-review` value remains frozen pre-
publication compatibility wording; a post-publication GitHub attestation is
separate evidence and does not rewrite that immutable candidate manifest.
Future release-contract work may introduce a more precise pending-attestation
state only through a versioned contract.

## Authority and limitations

The owner-signed annotated tag remains release authority. A passing workflow
attestation proves the workflow identity and subject digests represented in
the Sigstore bundle. It does not prove owner approval, claim truth, repository
settings, future availability, or absence of compromise, and it grants no
signing, publication, deployment, execution, mutation, merge, spending,
credential, disclosure, or declassification authority.

Offline verification requires preserved attestation bundles and current
trusted-root evidence. Online verification should constrain the repository,
signer-workflow path, and independently trusted workflow commit digest, and
reject self-hosted runners.

The initial workflow supports signing-key generation 1 only. Rotation is a
fail-closed reviewed change: add the successor public key and policy while
retaining the old generation for separately authorized historical backfill.

## Evidence

- GitHub issue: <https://github.com/joefeser/artifact-memory/issues/96>
- GitHub attestation guidance:
  <https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations>
- Upstream action: <https://github.com/actions/attest>
- Workflow: `.github/workflows/release-attestations.yml`
- Gate: `artifact_memory/release_attestation.py`
- Tests: `tests/test_release_attestation.py`
