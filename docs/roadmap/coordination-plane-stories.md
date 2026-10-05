# Coordination Plane Stories

Source: `docs/contracts/v0-coordination-plane.md`. Story style: DoD first,
one acceptance command where possible. Sizes are S (< half day) / M (day) /
L (multi-day, slice further).

Status: accepted implementation backlog. These stories define future
executable proof; their presence does not claim the coordination plane is
implemented.

## artifact-memory stories (AM)

### AM-1: Session-ledger ingestion (M)
As a coordinating agent, when my session ends I want done-log entries
imported as WorkReceipt-adjacent records so parallel sessions share memory
through the vault instead of file copies.
**Accept:** `artifact-memory import-session-ledger <done-log.md> --vault <v>`
creates one record per dated entry with provenance `session-ledger`, and a
dry-run prints the mapping without writing.

### AM-2: The three coordination record types (S)
TaskPacket, WorkReceipt, AccessLabel as first-class record schemas with
validation, digest, and labels (contract doc §Records). Project references are
UUIDs with display-name provenance. WorkReceipt evidence and artifact entries
are strict typed objects; unknown shapes are rejected. Vault-only privacy
fields never enter repository fixtures. Every body has deterministic
`schema_id`, stable UUID `originId`, and origin-namespaced `record_id`;
`revision_digest` is recomputed from canonical bytes and carried externally in
revision references. WorkReceipt binds an exact admitted TaskPacket revision.
TaskPacket claims are strict typed entries bound to the exact open revision;
the v0 `open`/`claimed` lifecycle and immutable predecessor transition are
validated. AccessLabel read grant and denial sets are duplicate-free and
disjoint.
Each strict schema admits only the structured optional `extensions` container;
the AM-6 freshness extension is optional and namespaced.
**Accept:** `artifact-memory records validate fixtures/coordination/*.json` —
valid fixtures pass; each field-omission fixture fails with a typed error;
duplicate human identifiers from distinct synthetic origin UUIDs do not
collide; mismatched origin/record IDs, stale or forked `taskRef` values, raw
provider URLs in artifact locations, and unknown top-level fields fail typed;
the optional freshness extension is preserved canonically. Negative fixtures
reject malformed claim entries, a claimed successor not bound to its exact
open predecessor, duplicate read UUIDs, and overlap between
`may.readProjects` and `mayNot.readProjects`.

### AM-3: Vault sync CLI — push/pull as set union (M)
As a machine-local vault, I want `artifact-memory sync --hub <url>` so
local appends converge to the hub and back, idempotently.
**Accept:** integration test: two fresh vaults, disjoint appends on each,
push both to a hub dir, then pull both ⇒ both contain the union; a second
push/pull round is a no-op (byte-identical state); two valid revisions under one record ID merge by
`(record_id, revision_digest)`; different canonical bytes claiming the same
complete pair ⇒ quarantine error naming the pair and both observed content
digests, no merge. Each successful pull returns a canonical sync receipt whose
authorized-set count and digest match the resulting local set and whose
submitted pairs have typed admission outcomes; rejected or quarantined pairs
are absent from the authorized set. Tampering with the receipt or local set
fails typed and does not advance the last-successful-sync marker. Golden
vectors cover empty and reordered sets, Unicode identifiers, typed submission
outcomes, exclusions, pagination, missing/duplicate pages, and AccessLabel
rotation. Rotation rebuilds only the generated authorized projection from the
full replacement manifest; canonical vault history is retained and suppressed
records do not enter context export.

### AM-4: Outbox semantics — local append is never blocked by the hub (M)
Sync failures spool; work continues.
**Accept:** with the hub unreachable, `record append` succeeds locally and
`sync` retries later; on recovery the union holds; no record is lost or
duplicated (count invariant across a 100-append soak).

### AM-5: Kickoff-pack generator (S)
`artifact-memory kickoff --project sample-service` emits informational
fresh-session context (session-start protocol + authority boundary + current
queue) from the context pack + queue records.
**Accept:** generated prompt contains the verification command from the unique
current revision of the lexicographically latest open task admitted by the
latest successful authenticated sync receipt, identifies the receipt's
observation time and hub scope generation, contains the standing no-authority
lines, and renders `acceptanceCommand` only as escaped untrusted data with an
explicit `do not execute` instruction; golden-file test. Synthetic malicious
commands containing newlines, shell substitutions, metacharacters, and
instruction-like prose remain inert and produce no tool invocation. A
missing/tampered receipt, local authorized-set mismatch, pending/rejected/
quarantined revision, or forked/broken TaskPacket predecessor chain fails
typed. The retained receipt is integrity evidence from an authenticated
session, not issuer authenticity or authority.

### AM-6: Freshness linked to repo heads (S)
Records may carry `trueAsOfCommit` only through the optional
`https://artifact-memory.dev/extensions/coordination-freshness/v1` declaration;
readers mechanically detect drift.
**Accept:** `context-pack` marks records whose supported extension's
`trueAsOfCommit` is not an ancestor of the repo's current head as
`stale-verify`; unknown optional extensions remain opaque, and an unknown
required extension or top-level `trueAsOfCommit` fails closed.

### AM-9: Project onboarding — one command from zero to working agent (M)
As an operator, I point `artifact-memory onboard` at any repo — existing
with history, or brand new — and get: repo identity minted or verified
(`.agent-memory/repo.json`), vault created or linked with the project
label, AccessLabel registered (credential hint; key issuance is the WITS
side per W-2, and label binding requires separate WITS administrator
authority), first sync completed (local replica bootstrapped from the hub),
and the first kickoff pack emitted with a bootstrap receipt.
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

### AM-7: Per-label read scoping at sync and context export (M)
AccessLabel read permissions are default-deny at hub egress and enforced again
at context-pack generation, so restricted clients never receive other
projects' records.
**Accept:** sync delta and context pack generated with `label-scoped-client`
contain zero records for an excluded synthetic project; each exclusion appears
only as a count in its receipt, without protected record identities. The
restricted sync response contains no full AccessLabel body and no denied
project UUID or display name; local context export without a trusted policy
view denies rather than inferring access from an opaque label reference. After
a synthetic label narrows, a full replacement membership manifest advances
the scope generation, rebuilds the generated authorized projection, and
suppresses formerly visible records without deleting canonical history or
claiming erasure. An AccessLabel with duplicate or overlapping read grant and
denial UUIDs is rejected typed before use; sync and context export fail closed
if such a label reaches evaluation.

## WITS stories (W)

### W-1: Coordination intake routes (M)
`POST /api/agent/coordination/receipts` and `.../claims` per the contract:
bearer + capability auth (reuse `AgentApiKey`), validated append into the
vault store (no WITS-owned copy), claim exclusivity check.
**Accept:** integration test — two concurrent claims for one taskId: one
201, one 409, with the winner atomically appending one durable claimed
TaskPacket successor whose `predecessor` and strict claim-entry `taskRef` bind
the exact prior open revision; restart and sync reconstruct the same winner;
retrying that exact claim appends no duplicate successor; ordinary sync cannot
inject an `open`-to-`claimed` transition. A receipt with a failing schema or
wrong writer: 422 typed;
the authenticated key's server-owned principal binding, not the submitted
writer string, determines the expected writer; a correct-looking writer under
the wrong key is also 422 typed; a receipt referencing a stale TaskPacket
revision or a caller-selected AccessLabel that differs from the server binding
is also rejected typed;
project-scoped audit evidence written for accepted mutations through the
WITS-owned coordination audit contract, without inventing a case identity.

### W-2: Capability names for coordination (S)
Add `coordination:claim:<project>`, `coordination:receipt:<project>`,
`coordination:read:<project>`, `coordination:sync:task-packet:<project>`, and
`coordination:sync:work-receipt:<project>` capabilities to the capability
model; document them in `api-surface-map.md`. Sync egress and intake require
both the applicable capability and permission in the server-bound AccessLabel.
**Accept:** route tests independently remove each capability and label grant;
each missing gate denies the corresponding operation typed. Ordinary sync of
an AccessLabel body is always denied and no record-selected label can widen
the effective server binding.

### W-3: Bus notification only (S)
On accepted receipt/claim, publish a notification via `BUS_TRANSPORT`;
nothing durable is read from the bus; intake works with bus disabled.
**Accept:** with `BUS_TRANSPORT=in_process` (the default, per
`lib/bus/constants.ts`) all intake tests still pass — notifications are a
sink without a subscriber; with rabbitmq configured, a notification is
observed per mutation.

### W-4: Sync endpoint for AM-3 (S)
`POST /api/agent/coordination/sync` accepting a batch of records, returning
the authorized union delta (revisions the caller lacks and may read), a
canonical sync receipt with authorized-set count/digest and typed submission
outcomes, a count-only exclusion receipt, and enforcement of the quarantine
rule.
**Accept:** AM-3's integration test runs against this endpoint as its hub; a
restricted credential receives no excluded project record or protected
identity, receives no full AccessLabel body, and does receive the count-only
exclusion receipt. Boundary tests cover the exact V0 request byte, record
count, record size, nesting depth, field size, one-request-per-principal, and
response page limits; every over-limit request fails with its typed code and
admits zero pairs, while oversized authorized output paginates with
principal/scope-bound continuation tokens.

## Sequencing

AM-2 → AM-3 + AM-4 (storage correctness first) → W-1 + W-2 + W-4 (bridge)
→ AM-8 + **AM-9** + AM-5 (onboarding and ergonomics — the get-everyone-
moving slice) → AM-1, AM-6, AM-7, W-3 (history import and hardening). An
existing local-ledger flow remains valid until AM-3/W-1 land.
