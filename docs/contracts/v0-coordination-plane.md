# v0 Coordination Plane Contract (draft for owner review)

Status: DRAFT — written 2026-09-25 from the 88mph coordinator sessions
(evidence: phases 0-2 of the parity-harness program, one shared checkout
with a live second coordinator session, and the WITS code read of
`what-is-the-spec` @ current main).

## Problem

Multiple agents (GLM coordinator sessions, Codex, flash fleets, a
sensitive-work machine) need shared coordination state: a task queue with
one owner per project, append-only work receipts from many writers, and
scoped access for the sensitive machine. Today that state is gitignored
markdown on one Mac (`done-log.md`, `coordinator-state.md`) — proven
effective, single point of failure, non-parallel by construction.

## Architecture (three jobs, three components)

**Transport ≠ storage ≠ validation.**

- **Storage** = this repo's record model (append-only, revision digests,
  provenance). One system of record. WITS never keeps a second copy of
  coordination truth (the two-writers lesson from 88mph's entity runtime).
- **Validation** = WITS (`what-is-the-spec`) as the bridge: schema-check,
  digest-verify, writer-authorize every record before commit; enforce
  single-writer on queue records; enforce claim exclusivity.
- **Transport** = HTTP to WITS (synchronous claim/post), with the bus
  (BUS_TRANSPORT) used only for fan-out notifications, never intake truth.

## Local-first sync (outbox pattern)

1. A writer ALWAYS appends to its local vault first. The local append is
   the primary act; delivery is secondary.
2. A background syncer pushes new local records to the hub (WITS on
   dockercache). Delivery is idempotent: sync is set union of immutable
   records; retries are safe; order does not matter.
3. Pull is the same union in reverse. Each machine converges to the full
   record set.
4. **Integrity rule (the only failure mode):** same record ID with
   different revision digests across replicas = quarantine + human review.
   Never auto-resolve. Everything else merges by union.
5. **Claims are hub-authoritative; receipts are local-append.** Cross-
   machine mutual exclusion ("no other machine claimed this task") cannot
   be decided locally without consensus, and this design has none. Hub
   down ⇒ agents finish packets they already hold; claims wait.
6. Hub durability = dockercache ZFS + existing offsite chain. The hub is
   a single-host failure domain BY DESIGN for v0; degradation is
   "work local, sync later," never data loss.

## Repo identity (owner amendment 2026-09-25)

Every repo carries `.agent-memory/repo.json` at its root — committed,
non-secret — binding it to a stable identity:

```json
{ "uuid": "0f1c...-...", "humanName": "88mphServer" }
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
records). Merging is safe when (a) record IDs are origin-unique (ULID
plus a vault/origin component, so independently grown vaults cannot mint
the same ID), and (b) AccessLabels travel with records, so scoping
survives any union. The quarantine rule (same ID + different digest) is
the backstop. Vault separation remains the default for isolation;
merging is an operator convenience (e.g., one dashboard across projects),
never a requirement.

## Records (three new record types)

### 1. TaskPacket (`agent-memory://coordination/task-packet/v0`)

```json
{
  "taskId": "task-<ulid>",
  "projectId": "<repo uuid from .agent-memory/repo.json>",
  "projectName": "88mphServer",
  "title": "Phase 4: function-vs-direct write classification",
  "dod": {
    "description": "Harness scenario proves function writes pass the same kernel contract as direct writes",
    "acceptanceCommand": "PARITY_HARNESS=1 npx jest entity-write-parity-harness",
    "expected": "12/12 PASS"
  },
  "scopeFence": {
    "allowedPaths": ["sdk-sync-pipeline/src/runtime/**"],
    "forbiddenPaths": ["88mph-api-server/src/database/**"]
  },
  "assignedWriter": "glm-coordinator-session-7",
  "claims": [],
  "status": "open | claimed | done | blocked",
  "parentEpic": "epic-parity-harness"
}
```

### 2. WorkReceipt (`agent-memory://coordination/work-receipt/v0`)

The "receipts over narrative" rule as a data type. Every completion claim
MUST carry one; validators reject claims without them.

Privacy contract: WorkReceipts (including machine, writer, and token
notes) live ONLY in the vault and are never committed to any repo, public
or private. Repo-side surfaces (PR bodies, CI logs) may repeat the
evidence commands and counts; the receipt record itself is vault-resident.

`evidence` is a TYPED array — each element `{command, exitCode, counts,
artifacts}` — and validators reject unknown shapes. Loose evidence would
degrade receipts back into narrative.

```json
{
  "receiptId": "rcpt-<ulid>",
  "taskId": "task-...",
  "writer": "glm-coordinator-session-7",
  "machine": "<machine label>",
  "repo": "<repo uuid>",
  "repoName": "88mphServer",
  "headSha": "8526d2b55...",
  "evidence": [
    {
      "command": "PARITY_HARNESS=1 npx jest --passWithNoTests entity-write-parity-harness",
      "exitCode": 0,
      "counts": { "passed": 11, "failed": 0, "skipped": 0 },
      "artifacts": ["https://github.com/joefeser/88mphServer/pull/651"]
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
  "labelId": "label-sensitive-mac",
  "credentialHint": "agent-key issued for the sensitive machine only",
  "may": { "claimProjects": ["new-ui-project"], "postReceipts": ["new-ui-project"] },
  "mayNot": { "readProjects": ["88mphServer", "wits"] },
  "notes": "Sensitive machine: can pull its task packets and push receipts; cannot read other projects' records."
}
```

## WITS bridge boundary

WITS gains exactly two intake routes plus validation; it stores nothing
coordination-related outside the vault:

- `POST /api/agent/coordination/receipts` — validated append to the vault
  (schema + digest + writer check), then fan-out notification on the bus.
- `POST /api/agent/coordination/claims` — hub-authoritative claim with
  exclusivity check, single-writer queue enforcement.
- Existing strengths reused as-is: bearer + capability auth
  (`AgentApiKey`), append-only handoff precedent (`/api/handoffs`),
  `Event` model for audit, `BUS_TRANSPORT` for notifications.

## Non-goals (v0)

- No consensus, no leader election, no peer-to-peer sync.
- No WITS-side duplicate of record storage.
- No policy inside the bridge: ceilings, quorums, and scope fences stay in
  lane configs and task packets (the 88mph lesson: machinery must not
  outrun judgment).
