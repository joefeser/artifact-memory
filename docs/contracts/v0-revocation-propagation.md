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

Successful acknowledgements require the approved v0 durable replay capability,
`artifact-memory/revocation-replay-ledger/sqlite-v1`. The reference runtime
admits only its exact `SQLiteRevocationReplayLedger` implementation; an
arbitrary object with a `retain()` method, including a subclass that overrides
retention, fails closed as `unavailable`. External ledger implementations need
a later versioned admission contract and cannot self-assert durability.

The replay key is the exact `(envelope_id, recipient_ref)` pair. Retention is
an atomic, durable, first-writer-wins transaction: the first canonical receipt
is committed before success is returned, and every later request for that key
returns the original bytes unchanged even when the requested endpoint evidence
or diagnostics differ. The ledger uses a versioned SQLite state contract,
full synchronous commits, an immediate write transaction, and a primary-key
conflict boundary. A restart or state reload must replay the same receipt;
same-process tests alone are not production evidence.

The retained value is a canonical JSON instance of
`artifact-memory/revocation-receipt/v1`. It contains all fields required by that
schema, its `receipt_id` is recomputed from every field except `receipt_id`, and
its envelope, recipient, target, target-revision, acknowledged outcome, and
applied suppression bindings must match the request. A missing, unapproved,
unavailable, malformed, non-canonical, or incorrectly bound ledger result fails
closed as `unavailable`. Validation failures and non-terminal recipient outcomes
do not consume replay state.

`SyntheticReplayLedger` remains a process-local exchange fixture and is not an
approved revocation ledger. Production operators must place the SQLite ledger
on durable managed storage, include it in custody and recovery policy, and keep
the returned canonical receipt in the immutable audit stream. The database path
is machine-local configuration, never durable artifact or record identity.

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
