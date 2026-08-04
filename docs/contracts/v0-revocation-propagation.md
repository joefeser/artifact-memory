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

Validated tombstones can suppress matching record identities from generated
projections and context-export input. Projection receipts bind the suppressed
set digest without disclosing record identities. Already-issued packs and
unknown or unmanaged replicas remain outside the local suppression claim.

Artifact Memory owns the portable envelope, recipient state, suppression, and
receipts. External adapters enforce endpoint behavior. WITS may supply owner
policy or authorization, but revocation does not create HACP work or execution
authority. Endpoint evidence never becomes a global or cryptographic erasure
claim.
