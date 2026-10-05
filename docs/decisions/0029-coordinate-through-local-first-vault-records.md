# 0029: Coordinate through local-first vault records

- Status: accepted
- Date: 2026-09-25
- Issues: [#134](https://github.com/joefeser/artifact-memory/issues/134)
  through [#142](https://github.com/joefeser/artifact-memory/issues/142)
- Contract: `docs/contracts/v0-coordination-plane.md`

## Context

Parallel agents need a shared task queue, immutable work evidence, scoped
disclosure, and recovery from temporary hub failure. A machine-local session
ledger gives one writer useful continuity but cannot provide cross-machine
claim exclusivity or a shared, durable record set. A transport bus can notify
workers but cannot become the source of truth.

Coordination data also crosses an authority boundary. Record prose, digests,
transport authentication, and generated kickoff packs must not silently grant
execution or disclosure authority. Restricted clients must not learn denied
project identities merely because a merged vault contains them.

## Options considered

1. Keep one machine-local ledger and copy it between workers. This is simple
   but creates a single point of failure, ambiguous merges, and no safe claim
   exclusivity.
2. Make WITS or the notification bus a second coordination database. This can
   centralize operations but duplicates canonical truth and couples durable
   history to a transport or product-specific store.
3. Use peer-to-peer replication with consensus. This removes one hub but is
   substantially larger than the v0 problem and adds leader-election and
   partition semantics.
4. Keep canonical coordination revisions in Artifact Memory vaults, use WITS
   for authenticated validation and hub-authoritative claims, and use HTTP plus
   the bus only for transport and fan-out.

## Decision

Choose option 4.

- Writers append immutable revisions to a local vault first and retry delivery
  through an outbox.
- In the reference runtime, the outbox is the local canonical pair set minus
  exact pairs evidenced by a successful authenticated sync. It is not a second
  mutable queue: failed delivery leaves canonical local pairs untouched, and
  exact replay remains idempotent.
- "Versioned text" means immutable canonical JSON revisions in a governed
  vault; it does not require private operational records to be committed to the
  public software repository.
- Sync is set union over exact `(record_id, revision_digest)` pairs. Record IDs
  include a stable origin UUID so independent vaults cannot mint colliding
  logical records.
- WITS authenticates principals, intersects project-scoped capabilities with a
  server-bound AccessLabel, validates submitted records, and decides exclusive
  claims. It does not keep a second canonical coordination store.
- Pull responses carry bounded, canonical sync receipts and authorized
  membership manifests. Scope changes rebuild a generated authorized
  projection without deleting append-only vault history.
- The bus carries notifications only. Loss or duplication of a notification
  cannot create or erase canonical state.
- Task commands and all other record prose remain untrusted informational data.
  Separate authenticated authority is required before execution.

## Security consequences

- Hub egress and intake are independently gated by authentication,
  project-scoped capabilities, and the server-bound AccessLabel. Caller-chosen
  label references cannot widen access.
- Restricted responses contain authorized identities and count-only exclusion
  evidence, never denied identities or full policy bodies.
- Exact resource and pagination limits bound parser, canonicalization, storage,
  and response work. Passing authentication does not waive those limits.
- Sync receipts obtained over authenticated transport remain
  `integrity-verified / issuer-unverified` when later replayed; they do not
  establish trust or authority.
- Local canonical history may retain records that a later scope no longer
  exposes. Suppression from generated views is not deletion or global erasure.

## Compatibility consequences

- TaskPacket, WorkReceipt, AccessLabel, sync-receipt, and membership-page v0
  shapes must be implemented and tested before interoperability is claimed.
- WorkReceipt binds an exact TaskPacket revision. Earlier drafts that identify
  only `taskId` are not valid v0 WorkReceipts.
- Freshness uses the structured optional extension contract. Adding
  `trueAsOfCommit` as a v0 top-level field is incompatible.
- V0 permits one hub failure domain and no peer consensus. A later topology or
  authenticity mechanism requires a new reviewed contract rather than silent
  reinterpretation.

## Evidence and follow-up

The implementation sequence and executable acceptance surfaces are maintained
in `docs/roadmap/coordination-plane-stories.md`. This decision and the contract
define behavior; they do not claim that the AM or WITS stories are already
implemented.
