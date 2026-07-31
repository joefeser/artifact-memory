# V0 authenticity assessment contract

Status: accepted
Decision: `docs/decisions/0005-v0-authenticity-assessment.md`
Schema: `artifact-memory/authenticity-receipt/v2`

The reference assessment classifies integrity, provenance, assertion mode,
issuer and audience metadata, transport state, authenticity requirement,
authorization, and trust without conflating them. It never verifies a record
signature and never grants authority or trust.

## Outcome rules

1. Failed or unverified integrity is `rejected`.
2. `authenticity-required` is `rejected` with
   `authenticity-required-unmet`.
3. A signed input with optional or integrity-only authenticity is
   `unsupported`; v0 does not inspect signer keys or algorithms.
4. An unsigned integrity-verified input with optional or integrity-only
   authenticity is `accepted` only as
   `integrity-verified / issuer-unverified`.
5. Authenticated transport does not alter issuer authenticity, authorization,
   or trust.

`issuer_ref` and `audience_ref` are optional self-asserted references. Their
presence requires the corresponding `self-asserted / unverified` state. V2 has
no signer-key, signature, algorithm, revocation, delegation, expiry, or trust
root fields because those behaviors are deferred rather than partially
implemented.

The assessment receipt is canonical-digest identified and includes an explicit
evaluation timestamp. Its authority boundary is constant:

`assessment grants no execution, disclosure, authorization, or trust`

The executable synthetic matrix is
`fixtures/synthetic/security/authenticity-v0-v2.json`. It contains newly
authored synthetic references only and no private key, credential, bearer
material, or real trust-store data.

For source compatibility, the reference helper retains its original five-
argument call shape. A call that omits `evaluated_at` and all v2-only fields
returns the unchanged v1 receipt shape. Supplying any v2-only field requires an
explicit `evaluated_at`; the conformance runner always exercises v2.
