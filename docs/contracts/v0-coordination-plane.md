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
complete `(record_id, revision_digest)` identity. AccessLabels travel with
records so scoping survives a union, and the hub enforces that scoping before
egress. Vault separation remains the default for isolation; merging is an
operator convenience, never a requirement.

## Records (three new record types)

### 1. TaskPacket (`agent-memory://coordination/task-packet/v0`)

```json
{
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
  "assignedWriter": "agent-session-synthetic-1",
  "claims": [],
  "status": "open",
  "parentEpic": "epic-synthetic-parity"
}
```

### 2. WorkReceipt (`agent-memory://coordination/work-receipt/v0`)

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
  "receiptId": "rcpt-01J00000000000000000000001",
  "taskId": "task_01J00000000000000000000000",
  "writer": "agent-session-synthetic-1",
  "machine": "synthetic-client-a",
  "projectId": "11111111-1111-4111-8111-111111111111",
  "projectName": "sample-service",
  "headSha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
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
  "recordedAt": "2026-09-25T17:20:00Z"
}
```

### 3. AccessLabel (`agent-memory://coordination/access-label/v0`)

Pins what a credential may see and do. Maps onto WITS's existing
`AgentApiKey` capability model (`docs/api-surface-map.md`: bearer agent-key
+ capability + project checks).

```json
{
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
  "notes": "Synthetic scoped client may access one project and cannot read the other."
}
```

## WITS bridge boundary

WITS gains exactly two mutation routes plus one authenticated sync route; it
stores no second copy of coordination truth outside the vault:

- `POST /api/agent/coordination/receipts` — validated append to the vault
  (schema + digest + writer check), then fan-out notification on the bus.
- `POST /api/agent/coordination/claims` — hub-authoritative claim with
  exclusivity check, single-writer queue enforcement.
- `POST /api/agent/coordination/sync` — authenticated union exchange. The
  response is filtered by the credential-bound AccessLabel and read
  capabilities before egress and includes a count-only exclusion receipt.
- Existing strengths reused as-is: bearer + capability auth
  (`AgentApiKey`), append-only handoff precedent (`/api/handoffs`), and
  `BUS_TRANSPORT` for notifications.

Every accepted claim or receipt mutation requires durable, project-scoped
audit evidence. The coordination contract does not assume WITS's existing
case-bound `Event` model can represent that evidence. WITS owns a separate
coordination audit contract or an explicit valid project-to-case mapping; it
must not invent a case identity merely to satisfy the existing model.

## Non-goals (v0)

- No consensus, no leader election, no peer-to-peer sync.
- No WITS-side duplicate of record storage.
- No policy inside the bridge: ceilings, quorums, and scope fences stay in
  lane configs and task packets. Machinery must not outrun judgment.
