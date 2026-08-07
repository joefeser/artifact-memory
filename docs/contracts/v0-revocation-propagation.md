# v0 tombstone and revocation propagation

Issue #67 adds `revocation-envelope/v1`, `revocation-receipt/v1`, and
`revocation-propagation-receipt/v1`. A revocation envelope binds a validated
tombstone, target record revision, issuer, audience, correlation, scope, and
expiry. It carries no bytes, credentials, task authority, or deletion command.

Recipients return immutable acknowledgements. An acknowledgement records the
recipient outcome, suppression state, endpoint-specific receipt references, and
whether the audit receipt was retained. Aggregation reports acknowledged and
unresolved recipients; unavailable or rejected recipients keep the aggregate
`partially-complete`.

Successful acknowledgements require a caller-supplied durable replay ledger.
The ledger atomically retains the canonical acknowledgement together with its
`(envelope_id, recipient_ref)` replay key and returns that same receipt on a
retry. A missing, unavailable, malformed, or incorrectly bound ledger result
fails closed as `unavailable`. Validation failures and non-terminal recipient
outcomes do not consume replay state.

Only digest-valid recipient acknowledgements with `outcome: acknowledged`,
`suppression_state: applied`, and an exact target revision match can suppress a
record from generated projections and context-export input. Raw record IDs and
opaque receipt strings are not suppression authority. Projection receipts bind
the effective suppressed set digest without disclosing record identities.
Already-issued packs and unknown or unmanaged replicas remain outside the local
suppression claim.

Artifact Memory owns the portable envelope, recipient state, suppression, and
receipts. External adapters enforce endpoint behavior. WITS may supply owner
policy or authorization, but revocation does not create HACP work or execution
authority. Endpoint evidence never becomes a global or cryptographic erasure
claim.
