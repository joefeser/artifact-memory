# Coordination Plane Stories (draft for owner review)

Source: `docs/contracts/v0-coordination-plane.md`. Story style: DoD first,
one acceptance command where possible. Sizes are S (< half day) / M (day) /
L (multi-day, slice further).

## artifact-memory stories (AM)

### AM-1: Session-ledger ingestion (M)
As a coordinating agent, when my session ends I want done-log entries
imported as WorkReceipt-adjacent records so parallel sessions share memory
through the vault instead of file copies.
**Accept:** `artifact-memory import-session-ledger <done-log.md> --vault 88mph-operator-memory`
creates one record per dated entry with provenance `session-ledger`, and a
dry-run prints the mapping without writing.

### AM-2: The three coordination record types (S)
TaskPacket, WorkReceipt, AccessLabel as first-class record schemas with
validation, digest, and labels (contract doc §Records).
**Accept:** `artifact-memory records validate fixtures/coordination/*.json` —
valid fixtures pass; each field-omission fixture fails with a typed error.

### AM-3: Vault sync CLI — push/pull as set union (M)
As a machine-local vault, I want `artifact-memory sync --hub <url>` so
local appends converge to the hub and back, idempotently.
**Accept:** integration test: two fresh vaults, disjoint appends on each,
sync both against a hub dir ⇒ both contain the union; re-sync is a no-op
(byte-identical state); same-ID/different-digest pair ⇒ quarantine error
naming both digests, no merge.

### AM-4: Outbox semantics — local append is never blocked by the hub (M)
Sync failures spool; work continues. 
**Accept:** with the hub unreachable, `record append` succeeds locally and
`sync` retries later; on recovery the union holds; no record is lost or
duplicated (count invariant across a 100-append soak).

### AM-5: Kickoff-pack generator (S)
`artifact-memory kickoff --project 88mphServer` emits the fresh-session
prompt (session-start protocol + standing rules + current queue) from the
context pack + queue records — what was hand-written on 2026-09-25.
**Accept:** generated prompt contains the verification command from the
latest open task's DoD and the standing authorization lines; golden-file
test.

### AM-6: Freshness linked to repo heads (S)
Records may carry `trueAsOfCommit`; readers mechanically detect drift.
**Accept:** `context-pack` marks records whose `trueAsOfCommit` is not an
ancestor of the repo's current head as `stale-verify`.

### AM-9: Project onboarding — one command from zero to working agent (M)
As an operator, I point `artifact-memory onboard` at any repo — existing
with history, or brand new — and get: repo identity minted or verified
(`.agent-memory/repo.json`), vault created or linked with the project
label, AccessLabel registered (credential hint; key issuance is the WITS
side per W-2), first sync completed (local replica bootstrapped from the
hub), and the first kickoff pack emitted with a bootstrap receipt.
**Accept:** (a) fresh repo: `onboard` → repo.json exists with a new UUID,
kickoff pack renders, bootstrap receipt validates; (b) existing repo with
prior records: UUID minted, existing session-ledger/history importable via
AM-1, no duplicate records; (c) idempotent: second run changes nothing
(byte-identical vault state); (d) an un-onboarded repo calling any plane
command (sync/claim/receipt) fails with a typed error naming `onboard` as
the fix.

### AM-8: Repo identity manifest (S)
Every repo carries `.agent-memory/repo.json` (`uuid`, `humanName`),
committed and non-secret; all records reference the UUID (contract §Repo
identity).
**Accept:** two fixtures with the same `humanName` but different UUIDs
coexist in one vault with zero ambiguity; records referencing an unknown
UUID fail validation with a typed error; rename of `humanName` changes no
record digests.

### AM-7: Per-label read scoping in context packs (M)
AccessLabel `mayNot.readProjects` enforced at pack generation, so the
sensitive machine's packs never contain other projects' records.
**Accept:** pack generated with label `label-sensitive-mac` contains zero
records labeled `88mphServer`; exclusion appears in the selection receipt
(count-only).

## WITS stories (W)

### W-1: Coordination intake routes (M)
`POST /api/agent/coordination/receipts` and `.../claims` per the contract:
bearer + capability auth (reuse `AgentApiKey`), validated append into the
vault store (no WITS-owned copy), claim exclusivity check.
**Accept:** integration test — two concurrent claims for one taskId: one
201, one 409; a receipt with a failing schema or wrong writer: 422 typed;
events written for accepted mutations (reuse the `Event` model).

### W-2: Capability names for coordination (S)
Add `coordination:claim:<project>` and `coordination:receipt:<project>`
capabilities to the capability model; document in `api-surface-map.md`.
**Accept:** route tests reject keys lacking the capability; map row added.

### W-3: Bus notification only (S)
On accepted receipt/claim, publish a notification via `BUS_TRANSPORT`;
nothing durable is read from the bus; intake works with bus disabled.
**Accept:** with `BUS_TRANSPORT=in_process` (the default, per
`lib/bus/constants.ts`) all intake tests still pass — notifications are a
sink without a subscriber; with rabbitmq configured, a notification is
observed per mutation.

### W-4: Sync endpoint for AM-3 (S)
`POST /api/agent/coordination/sync` accepting a batch of records, returning
the union delta (records the caller lacks), enforcing the quarantine rule.
**Accept:** AM-3's integration test runs against this endpoint as its hub.

## Context updates (2026-09-25)

- Qodo review departs in ~1 month (cost); the quorum method will be
  re-established (lane config change) — Codex remains the required
  reviewer either way. No story in this file depends on Qodo.
- WITS already contains `lib/coordination/artifact-memory-boundary/
  projection.ts` — W-1 builds on that seam, not from zero.

## Sequencing

AM-2 → AM-3 + AM-4 (storage correctness first) → W-1 + W-2 + W-4 (bridge)
→ AM-8 + **AM-9** + AM-5 (onboarding and ergonomics — the get-everyone-
moving slice) → AM-1, AM-6, AM-7, W-3 (history import and hardening). The 88mph parity
program does not block on any of this; today's markdown-ledger flow remains
valid until AM-3/W-1 land.
