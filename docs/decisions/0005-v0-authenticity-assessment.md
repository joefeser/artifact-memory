# Decision 0005: v0 authenticity assessment contract

Status: accepted for v0
Date: 2026-07-31
Linked issues: #35, #2, #3, #4, #22, #39
Supersedes: 0004

## Context

Artifact Memory exchanges records and evidence whose bytes can be verified
without knowing who created them. V0 must represent that useful state honestly
without turning provenance, transport security, provider metadata, or another
system's authority receipt into proof that a claim came from a trusted issuer.

## Decision

V0 keeps six independent questions separate:

| Dimension | Question answered | Does not establish |
| --- | --- | --- |
| Identity | Which record, artifact, version, content object, endpoint, or actor reference is named? | Control of that identity, integrity, authenticity, or trust |
| Integrity | Do the observed bytes match the declared digest or canonical receipt identity? | Who issued them or whether their claims are true |
| Provenance | What source, tool, derivation, or observation history is asserted? | Issuer control, signature validity, authorization, or trust |
| Authenticity | Was the asserted issuer verified for this subject and audience? | Authorization to act or a receiver's trust judgment |
| Authorization | What may an actor do under a separate authority contract? | Integrity, authenticity, disclosure, or trust outside that contract |
| Trust | Will a receiver rely on a claim under local policy? | Truth, global acceptance, or authority in another system |

No state implicitly upgrades another. In particular:

- a content digest, Git commit, tool version, extractor identity, rule catalog
  entry, or TraceMap provenance can establish identity or integrity evidence
  but not operator authenticity;
- an authenticated SFTP, TLS, tailnet, or other transport authenticates only
  the channel or transport peer described by that transport contract. It does
  not authenticate a record's subject issuer or make the claim trusted;
- an ACK review or authority receipt governs its own workflow and does not
  authenticate Artifact Memory records, TraceMap evidence, or product claims;
- receiving knowledge never grants execution, mutation, spending, deployment,
  credential, disclosure, declassification, routing, or approval authority.

## V0 signed and unsigned behavior

Cryptographic record and receipt signature verification is deferred. V0 does
not define a signature envelope, supported algorithm set, signer-key identifier,
key discovery, delegation, rotation, revocation, expiry, or offline trust-root
distribution. It therefore cannot produce `authenticity-verified`.

Unsigned evidence may be accepted when integrity is verified and the receiving
policy permits integrity-only or optional-authenticity input. It is labeled
exactly:

`integrity-verified / issuer-unverified`

An `issuer_ref` or `audience_ref` on that assessment is self-asserted metadata,
not a verified identity. The v2 assessment deliberately has no signer-key or
algorithm fields. Signed input is `unsupported` when authenticity is optional
or integrity-only. Any input for which authenticity is required is rejected
with `authenticity-required-unmet`, including an input that merely claims to be
signed. Failed or unverified integrity is rejected before admission.

Because signing is not included, v0 has no fake signature-valid, unknown-key,
expired-key, revoked-key, delegated-key, or offline-verification outcomes.
Adding any of them requires a new versioned decision, schema, verifier, trust
store contract, and synthetic valid, invalid, unknown-key, expired, revoked,
delegated, and tampered vectors. Private keys, credentials, bearer values, and
real trust stores remain outside records and fixtures.

## Requirement classes

| Subject or use | V0 requirement | Result |
| --- | --- | --- |
| Deterministic local receipts used as implementation evidence | `integrity-only` | May be accepted after integrity verification; issuer remains unverified |
| Imported or provider evidence used informationally | `authenticity-optional` | May be accepted as `integrity-verified / issuer-unverified` |
| Unsigned TraceMap evidence | `authenticity-optional` | Same exact issuer-unverified label; TraceMap provenance remains provider evidence only |
| Claim that a named external party issued or endorsed a record | `authenticity-required` | Rejected in v0 |
| Cross-party/public claim advertised as authenticated | `authenticity-required` | Rejected in v0; #22 cannot claim authenticated exchange yet |
| Release tag signing | Separate owner release-signing policy | Does not make enclosed records cryptographically signed |
| ACK, WITS, HACP, or other authority receipt | Its owning system's contract | Never imported as Artifact Memory authenticity proof |

Receivers may impose `authenticity-required` on any class. They may not weaken a
sender's required-authenticity declaration or relabel an unverified issuer as
authentic. Trust remains a separate local receiving-policy decision even after
a future signature verifier exists.

## Assessment receipt

`artifact-memory/authenticity-receipt/v2` records:

- the subject reference and the fact that naming it does not authenticate it;
- integrity and provenance state;
- unsigned self-assertion or unsupported signed-input mode;
- self-asserted issuer and audience references when supplied;
- transport-channel state kept separate from subject-issuer state;
- authenticity requirement and fail-closed outcome;
- evaluation time, deterministic receipt identity, limitations, and a constant
  no-authority boundary.

The published v1 schema remains available unchanged. V2 tightens the contract
without reinterpreting old v1 receipts. The reference evaluator emits v2 and
validates its result against the packaged schema.

## Security and compatibility consequences

This decision permits useful unsigned local and provider evidence while making
its limitation machine-readable. It prevents authenticated transport,
provenance, a known provider schema, or workflow authority from being mistaken
for issuer authenticity. Cross-party exchange may proceed only with truthful
issuer-unverified labeling until a later signed-record version is designed and
proved. Unknown required authenticity fails closed; no implementation may
silently downgrade it to optional.
