# v0 Coordination Plane Contract (draft for owner review)

Status: DRAFT — written 2026-09-25 from owner-reviewed coordination needs.
All names, identifiers, commands, paths, and locations in this public contract
are synthetic examples rather than deployment records.

## Problem

Multiple agents need shared coordination state: a task queue with one owner
per project, append-only work receipts from many writers, and scoped access
for restricted clients. A machine-local session ledger is effective for one
writer but is a single point of failure and cannot coordinate parallel work.

## Architecture (three jobs, three components)

**Transport ≠ storage ≠ validation.**

- **Storage** = this repo's record model (append-only, revision digests,
  provenance). One system of record. WITS never keeps a second copy of
  coordination truth.
- **Validation** = WITS (`what-is-the-spec`) as the bridge: schema-check,
  digest-verify, writer-authorize every record before commit; enforce
  single-writer on queue records; enforce claim exclusivity.
- **Transport** = HTTP to WITS (synchronous claim/post), with the bus
  (BUS_TRANSPORT) used only for fan-out notifications, never intake truth.

## Local-first sync (outbox pattern)

1. A writer ALWAYS appends to its local vault first. The local append is
   the primary act; delivery is secondary.
2. A background syncer pushes new local records to the hub through WITS.
   Delivery is idempotent: sync is set union of immutable revisions; retries
   are safe; order does not matter.
3. Pull is the same union in reverse, but hub egress is default-deny. The hub
   authenticates the caller and returns only revisions permitted by the
   credential-bound AccessLabel and read capabilities. Its response includes a
   count-only exclusion receipt so a replica can detect that records were
   withheld without learning their identities or contents.
4. Union membership is the complete `(record_id, revision_digest)` pair.
   Distinct valid revisions under one `record_id` merge normally. Different
   canonical bytes claiming the same complete pair are quarantined for human
   review and are never auto-resolved.
5. **Claims are hub-authoritative; receipts are local-append.** Cross-
   machine mutual exclusion ("no other machine claimed this task") cannot
   be decided locally without consensus, and this design has none. Hub
   down ⇒ agents finish packets they already hold; claims wait.
6. Hub storage and backup topology are deployment policy, not public protocol
   identity. V0 permits a single-hub failure domain; degradation is "work
   local, sync later," never discard a local append.

Convergence requires two explicit phases: every writer pushes its local
revisions, then every replica pulls its authorized delta. A combined sync
command may perform both phases for one replica, but one pass per replica is
not proof of convergence when a later writer has not pushed yet. After all
pushes and pulls complete, another sync of every unchanged replica is a
byte-identical no-op.

Every successful pull returns a canonical, digest-identified
`coordination-sync-receipt/v0`. It binds the authenticated principal and exact
AccessLabel revision used by the hub, the hub's logical (not network)
identifier, a monotonic hub scope generation, the completion time, and the
count plus canonical set digest of every authorized `(record_id,
revision_digest)` pair visible in that scope. It also carries the count-only
exclusion receipt. Submitted pairs receive typed `admitted`, `rejected`, or
`quarantined` outcomes; rejected and quarantined submissions never enter the
authorized set. The receipt never names excluded records, projects, labels, or
other protected identities.

A replica verifies the receipt's canonical digest and recomputes the
authorized-set count and digest after applying the returned delta. A mismatch
fails typed and cannot advance the replica's last-successful-sync marker. The
receipt is durable evidence of what the client observed over an authenticated
channel; under `docs/contracts/v0-authenticity-assessment.md` it remains
`integrity-verified / issuer-unverified`. Authenticated transport does not turn
the later-restored receipt into issuer authenticity, trust, or authority.

## Canonical coordination identity and task state

Each TaskPacket, WorkReceipt, and AccessLabel is itself one canonical record
revision. Its strict body includes `schema_id` and `record_id` in addition to
the type-specific identifier. The mapping is deterministic:

- TaskPacket: `record://coordination/<taskId>`;
- WorkReceipt: `record://coordination/<receiptId>`; and
- AccessLabel: `record://coordination/<labelId>`.

`revision_digest` is not stored inside the body. It is the SHA-256 digest of
the complete canonical record bytes under
`docs/contracts/v0-canonical-records.md` and travels beside the body in sync
and exchange references. A receiver recomputes it before admitting the pair.
This avoids a self-referential digest and gives AM-3 the exact
`(record_id, revision_digest)` union key.

TaskPacket evolution is an immutable predecessor chain. A genesis revision has
`predecessor: null`; every later revision uses an object containing exactly
`record_id` (the same TaskPacket identity) and `revision_digest` (the exact
digest of its immediate predecessor). A leaf is hub-admitted only when its
exact pair is present in the authorized set bound by the replica's latest
successful authenticated sync receipt. The unique admitted leaf is current as
of that receipt's hub scope generation and completion time; offline readers
must not claim fresher global state. Zero leaves, multiple leaves, a broken
predecessor, a predecessor from a different `record_id`, an absent receipt, or
a local set that does not match the receipt's authorized-set count and digest
is a typed conflict requiring quarantine or resync and human review.
Historical, pending, rejected, and quarantined revisions never become current
merely because they exist in a local vault or are replayed later. For AM-5,
"latest open task" means the lexicographically greatest ULID-bearing `taskId`
among unique current leaves whose status is `open`, explicitly qualified by the
receipt's observation time and generation.

Every TaskPacket and WorkReceipt carries `accessLabelRef`, an exact object with
`record_id` and `revision_digest` for the AccessLabel revision governing its
project disclosure. The hub validates that reference before admission and
egress. The reference identifies policy; it does not grant authority by itself.

## Repo identity (owner amendment 2026-09-25)

Every repo carries `.agent-memory/repo.json` at its root — committed,
non-secret — binding it to a stable identity:

```json
{ "uuid": "11111111-1111-4111-8111-111111111111", "humanName": "sample-service" }
```

All coordination records reference the UUID; the human name is
display-only. Same-named repos cannot collide; renames never break
history. This file is the ONLY coordination artifact that lives inside a
repo.

Display names ride on records as immutable provenance (like git author
names on commits): records may carry `projectName` alongside `projectId`
for human reading and dashboards. `projectName` is never authoritative,
never a join key, and never validated for uniqueness — the UUID is the
reference; the name is how it read at the time.

**Vault topology and merging.** Merged vaults are native to this design —
the hub in the sync model IS a merged vault (set union of immutable
revisions). Origin-unique ULIDs plus a vault/origin component remain the rule
when minting a new `record_id`, preventing independent origins from minting the
same logical identity. Revisions under one record ID union freely by their
complete `(record_id, revision_digest)` identity. TaskPackets and WorkReceipts
carry exact AccessLabel references so scoping survives a union. Full
AccessLabel bodies are hub/admin-side policy records and are not ordinary sync
payloads for restricted replicas: returning a label that names denied projects
would defeat the count-only privacy boundary. The hub enforces the referenced
label before egress. A separately authorized administrative export may carry a
full AccessLabel; a restricted replica receives only its own opaque exact
label reference, authorized records, authorized-set digest/count, and the
count-only exclusion receipt. Local context export without a trusted local
policy view defaults to deny; it must not infer permission from record text or
the opaque reference. Vault separation remains the default for isolation;
merging is an operator convenience, never a requirement.

## Records (three new record types)

### 1. TaskPacket (`artifact-memory/coordination-task-packet/v0`)

```json
{
  "schema_id": "artifact-memory/coordination-task-packet/v0",
  "record_id": "record://coordination/task_01J00000000000000000000000",
  "taskId": "task_01J00000000000000000000000",
  "projectId": "11111111-1111-4111-8111-111111111111",
  "projectName": "sample-service",
  "title": "Verify synthetic adapter parity",
  "dod": {
    "description": "Synthetic adapter and direct writes satisfy one contract",
    "acceptanceCommand": "python -m unittest tests.test_synthetic_adapter",
    "expected": "OK"
  },
  "scopeFence": {
    "allowedPaths": ["src/adapter/**"],
    "forbiddenPaths": ["src/credentials/**"]
  },
  "accessLabelRef": {
    "record_id": "record://coordination/label-scoped-client",
    "revision_digest": "sha-256:d1535edaaf14dfdbcf137736ecb8f881a96e859e90c91ceb280dc1d7f416731a"
  },
  "assignedWriter": "agent-session-synthetic-1",
  "claims": [],
  "status": "open",
  "parentEpic": "epic-synthetic-parity",
  "predecessor": null,
  "authority_boundary": "informational only; authority requires independently authenticated WITS enforcement"
}
```

### 2. WorkReceipt (`artifact-memory/coordination-work-receipt/v0`)

The "receipts over narrative" rule as a data type. Every completion claim
MUST carry one; validators reject claims without them.

Privacy contract: WorkReceipts (including machine, writer, and token
notes) live ONLY in the vault and are never committed to any repo, public
or private. Repo-side surfaces (PR bodies, CI logs) may repeat the
evidence commands and counts; the receipt record itself is vault-resident.

`evidence` is a TYPED array — each element has exactly `command`, `exitCode`,
`counts`, and `artifacts`, and validators reject unknown shapes. Each artifact
entry separately identifies the logical artifact, exact content, observed
location, media type, and semantic type. A location is never artifact or
content identity. Loose evidence would degrade receipts back into narrative.

```json
{
  "schema_id": "artifact-memory/coordination-work-receipt/v0",
  "record_id": "record://coordination/rcpt-01J00000000000000000000001",
  "receiptId": "rcpt-01J00000000000000000000001",
  "taskId": "task_01J00000000000000000000000",
  "writer": "agent-session-synthetic-1",
  "machine": "synthetic-client-a",
  "projectId": "11111111-1111-4111-8111-111111111111",
  "projectName": "sample-service",
  "headSha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "accessLabelRef": {
    "record_id": "record://coordination/label-scoped-client",
    "revision_digest": "sha-256:d1535edaaf14dfdbcf137736ecb8f881a96e859e90c91ceb280dc1d7f416731a"
  },
  "evidence": [
    {
      "command": "python -m unittest tests.test_synthetic_adapter",
      "exitCode": 0,
      "counts": { "passed": 1, "failed": 0, "skipped": 0 },
      "artifacts": [
        {
          "artifactId": "artifact://synthetic/review-receipt",
          "contentDigest": "sha-256:0000000000000000000000000000000000000000000000000000000000000000",
          "location": "https://example.invalid/reviews/42",
          "mediaType": "application/json",
          "semanticType": "code-review-receipt"
        }
      ]
    }
  ],
  "consumedTokensNote": null,
  "recordedAt": "2026-09-25T17:20:00Z",
  "authority_boundary": "informational only; authority requires independently authenticated WITS enforcement"
}
```

### 3. AccessLabel (`artifact-memory/coordination-access-label/v0`)

Pins what a credential may see and do. Maps onto WITS's existing
`AgentApiKey` capability model (`docs/api-surface-map.md`: bearer agent-key
+ capability + project checks).

```json
{
  "schema_id": "artifact-memory/coordination-access-label/v0",
  "record_id": "record://coordination/label-scoped-client",
  "labelId": "label-scoped-client",
  "credentialHint": "synthetic agent-key label; no credential material",
  "projectNames": [
    {
      "projectId": "11111111-1111-4111-8111-111111111111",
      "projectName": "sample-service"
    },
    {
      "projectId": "22222222-2222-4222-8222-222222222222",
      "projectName": "sample-analytics"
    }
  ],
  "may": {
    "claimProjects": ["11111111-1111-4111-8111-111111111111"],
    "postReceipts": ["11111111-1111-4111-8111-111111111111"],
    "readProjects": ["11111111-1111-4111-8111-111111111111"]
  },
  "mayNot": {
    "readProjects": ["22222222-2222-4222-8222-222222222222"]
  },
  "notes": "Synthetic scoped client may access one project and cannot read the other.",
  "authority_boundary": "informational only; authority requires independently authenticated WITS enforcement"
}
```

`credentialHint` is display-only provenance and never selects or authenticates
a policy. WITS maintains a server-owned binding from the authenticated
`AgentApiKey` identity to both (a) one stable coordination principal identifier
and (b) one exact accepted AccessLabel `(record_id, revision_digest)` pair. A
client cannot submit or choose either binding. Missing, unknown, stale,
revoked, or multiply bound labels or principals fail closed. On receipt intake,
WITS requires `WorkReceipt.writer` to equal the server-bound principal and the
TaskPacket's `assignedWriter`; a caller-controlled writer string is never
authorization. Claim intake applies the same principal binding. Registering,
replacing, or revoking either binding requires separate WITS administrative
authority; ordinary sync, claim, and receipt capabilities cannot mutate it.
AccessLabel records are portable policy evidence, not self-authorizing grants,
and their full bodies are visible only to separately authorized administrators
or policy readers.

## Authority boundary

Coordination records, sync receipts, context packs, and kickoff packs are
informational. They grant no execution, mutation, routing, disclosure,
credential, spending, deployment, approval, or merge authority. A TaskPacket
may describe scope and acceptance evidence, but an agent acts only under a
separately authenticated authority contract. A kickoff pack may carry an
opaque WITS authority reference for independent resolution; it must not render
record text as standing authorization.

## WITS bridge boundary

WITS gains exactly two mutation routes plus one authenticated sync route; it
stores no second copy of coordination truth outside the vault:

- `POST /api/agent/coordination/receipts` — validated append to the vault
  (schema + digest + writer check), then fan-out notification on the bus.
- `POST /api/agent/coordination/claims` — hub-authoritative claim with
  exclusivity check, single-writer queue enforcement.
- `POST /api/agent/coordination/sync` — authenticated union exchange. The
  response is filtered by the credential-bound AccessLabel and read
  capabilities before egress and includes the canonical sync receipt,
  authorized-set count/digest, and count-only exclusion receipt. Restricted
  responses never include full AccessLabel bodies or denied identities.
- Existing strengths reused as-is: bearer + capability auth
  (`AgentApiKey`), append-only handoff precedent (`/api/handoffs`), and
  `BUS_TRANSPORT` for notifications.

Every accepted claim or receipt mutation requires durable, project-scoped
audit evidence. The coordination contract does not assume WITS's existing
case-bound `Event` model can represent that evidence. WITS owns a separate
coordination audit contract or an explicit valid project-to-case mapping; it
must not invent a case identity merely to satisfy the existing model.

WITS resolves the authenticated key-to-principal and key-to-label bindings
before all three routes. The caller never supplies the effective principal or
label. WITS compares record writer fields to the effective principal rather
than trusting them. Principal and label administration remain separate
owner/admin operations and are not coordination intake routes.

## Non-goals (v0)

- No consensus, no leader election, no peer-to-peer sync.
- No WITS-side duplicate of record storage.
- No policy inside the bridge: ceilings, quorums, and scope fences stay in
  lane configs and task packets. Machinery must not outrun judgment.
