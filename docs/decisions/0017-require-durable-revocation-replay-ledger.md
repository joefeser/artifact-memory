# Require a durable revocation replay ledger

Status: accepted
Date: 2026-08-07

## Decision

An `acknowledged` revocation receipt with `suppression_state: applied` is emitted
only after the exact v0 `SQLiteRevocationReplayLedger` commits the canonical
receipt under its `(envelope_id, recipient_ref)` replay key. The transaction is
atomic and first-writer-wins, and reopening the ledger must return the original
receipt unchanged.

Objects that merely provide a compatible `retain()` method are not admitted.
The process-local `SyntheticReplayLedger` remains useful for exchange fixtures
but cannot establish durable revocation acknowledgement. A future external
ledger requires a new versioned capability and conformance boundary.

## Consequences

- A no-op, overwriting, malformed, missing, or unavailable ledger fails closed.
- The runtime has one concrete restart-tested persistence path instead of
  treating structural typing as durability evidence.
- The SQLite file is operational replay custody, not canonical record identity;
  its path is local configuration and returned receipts remain immutable audit
  records.
- This proves local durable replay, not recipient honesty, tamper-proof storage,
  global deletion, or erasure of unknown replicas.
