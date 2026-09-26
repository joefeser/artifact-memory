# v0 Coordination Plane Contract

Status: accepted design; implementation is tracked by AM-1 through AM-9 and
W-1 through W-4 and is not claimed by this document-only change.
Decision: `docs/decisions/0029-coordinate-through-local-first-vault-records.md`.
All names, identifiers, commands, paths, and locations in this public contract
are synthetic examples rather than deployment records.

This contract precedes implementation deliberately. No coordination feature or
interoperability claim is complete until the applicable executable acceptance
commands and synthetic fixtures in
`docs/roadmap/coordination-plane-stories.md` pass. Contract prose is not a
substitute for those tests.

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
`artifact-memory/coordination-sync-receipt/v0`. Its strict fields are:

- `schema_id` and digest-derived `receipt_id`;
- the authenticated `principal_id`, exact `access_label_ref`, and logical
  `hub_id` (never a hostname or URL);
- integer `scope_generation` and RFC 3339 `completed_at`;
- `authorized_membership` with exact `pair_count`, `pair_set_digest`, and
  `page_count`;
- `excluded_count`, with no excluded identity or content; and
- `submission_outcomes`, each binding one exact submitted pair to one of
  `admitted`, `rejected`, or `quarantined` plus a typed outcome code;
- `transport_state: "authenticated"`, `issuer_state: "unverified"`, and the
  constant no-authority boundary.

Each outcome object contains exactly `record_ref`, `outcome`, and `code`.
Initial codes are `admitted`, `schema-invalid`, `digest-mismatch`,
`unauthorized-project`, `unauthorized-record-type`, `label-mismatch`,
`principal-mismatch`, `same-pair-different-bytes`, `resource-limit`, and
`unsupported-required-extension`. `same-pair-different-bytes` is quarantined;
`admitted` is admitted; all other initial codes are rejected.

```json
{
  "schema_id": "artifact-memory/coordination-sync-receipt/v0",
  "receipt_id": "coordination-sync-receipt://sha-256/db27d742213c3788b696d3e9ffdfb65c431100eb652a6526c5e87627fe24c136",
  "hub_id": "coordination-hub://synthetic/hub-a",
  "principal_id": "coordination-principal://synthetic/agent-1",
  "access_label_ref": {
    "record_id": "record://coordination/33333333-3333-4333-8333-333333333333/label/label-scoped-client",
    "revision_digest": "sha-256:164b6b386cdedf382529cc57cf7c929446a1f360b164c13d1243849231f4596a"
  },
  "scope_generation": 7,
  "completed_at": "2026-09-25T19:00:00Z",
  "authorized_membership": {
    "pair_count": 1,
    "pair_set_digest": "sha-256:a64fac5313d6206df32c107ff0d3cefdd382dbf712dcb77ddbddd44065278ade",
    "page_count": 1
  },
  "excluded_count": 2,
  "submission_outcomes": [
    {
      "record_ref": {
        "record_id": "record://coordination/33333333-3333-4333-8333-333333333333/task/task_01J00000000000000000000000",
        "revision_digest": "sha-256:93be6b6e63c11906c955f835da6e7f547c1672e1b173cf59126ac03f43f41022"
      },
      "outcome": "admitted",
      "code": "admitted"
    }
  ],
  "transport_state": "authenticated",
  "issuer_state": "unverified",
  "authority_boundary": "sync receipt grants no execution, disclosure, authorization, or trust"
}
```

`receipt_id` is
`coordination-sync-receipt://sha-256/<lowercase-hex>`, where the hex value is
SHA-256 over the canonical JSON object containing every receipt field except
`schema_id` and `receipt_id`. The canonical JSON profile is
`docs/contracts/v0-canonical-records.md`.

The authorized pair set is represented as an array of objects containing
exactly `record_id` and `revision_digest`. Sort the array first by `record_id`
and then by `revision_digest`, both by Unicode code point with no normalization.
`pair_set_digest` is SHA-256 over the canonical JSON bytes of that sorted
array. The empty set hashes the canonical bytes of `[]`. Ordering differences
therefore cannot produce different valid digests.

The response carries a paginated
`artifact-memory/coordination-authorized-membership-page/v0` manifest listing
only pairs the caller is authorized to know. Page order and boundaries do not
enter `pair_set_digest`; the reconstructed complete sorted array does. Each
page contains exactly `schema_id`, `receipt_ref`, zero-based `page_index`,
`page_count`, `pairs`, and an opaque `next_token` string or null. The token is
transport state, not portable identity or authority, and must not enter logs or
the canonical vault. On a
changed AccessLabel revision or `scope_generation`, the hub returns a full
replacement manifest. The replica rebuilds a generated authorized projection
from that manifest and suppresses pairs absent from it. It does not delete the
append-only canonical vault or claim erasure. For an unchanged scope, a delta
plus the previously verified manifest may be used. Missing pages, duplicate or
conflicting pairs, count/digest mismatch, or use of a prior-generation manifest
fails typed and cannot advance the last-successful-sync marker.

Successful receipts are ordered by `completed_at`. Exact `receipt_id` replay is
idempotent. A receipt earlier than the last successful receipt fails
`sync-receipt-stale`; a distinct receipt with the same `completed_at` fails
`sync-receipt-order-conflict`. V0 therefore never guesses an order between two
different scope or membership observations at the same timestamp.

Submitted pairs receive typed `admitted`, `rejected`, or `quarantined`
outcomes; rejected and quarantined submissions never enter the authorized set.
The receipt and manifest never name excluded records, projects, labels, or
other protected identities. They are durable evidence of what the client
observed over an authenticated channel; under
`docs/contracts/v0-authenticity-assessment.md` they remain
`integrity-verified / issuer-unverified`. Authenticated transport does not turn
a later-restored receipt into issuer authenticity, trust, or authority.

### V0 sync resource bounds

Limits are checked before or during bounded parsing, before canonicalization or
storage. One request is at most 8 MiB, 1,000 submitted records, 1 MiB per
canonical record, nesting depth 64, and 1 MiB per string field. One principal
may have only one sync request in flight. Violations return respectively
`sync-request-too-large`, `sync-record-limit`, `sync-record-too-large`,
`sync-depth-limit`, `sync-field-too-large`, or `sync-principal-busy`; no pair is
admitted from the rejected request.

The one-in-flight boundary spans pending-outcome loading, response construction,
local projection application, and deletion of the exact pending envelope named
by that response. A non-empty pending envelope must be acknowledged by pull
before another push; it cannot be overwritten by a later request.

Response pages are at most 4 MiB and 500 records. A larger authorized delta or
membership manifest is paginated with opaque, principal- and
`scope_generation`-bound continuation tokens. A token cannot widen scope and
expires without changing canonical state. Implementations may configure lower
deployment limits but must advertise them before intake; they cannot claim v0
interoperability with higher limits or an unbounded mode.

## Canonical coordination identity and task state

Each TaskPacket, WorkReceipt, and AccessLabel is itself one canonical record
revision. Its strict body includes `schema_id`, `record_id`, and a stable UUID
`originId` in addition to the type-specific identifier. The mapping is
deterministic:

- TaskPacket: `record://coordination/<originId>/task/<taskId>`;
- WorkReceipt: `record://coordination/<originId>/receipt/<receiptId>`; and
- AccessLabel: `record://coordination/<originId>/label/<labelId>`.

The origin UUID identifies the minting vault or hub namespace, not a machine,
path, network address, or custodian. It is immutable for the logical record.
Receivers reject a body whose `record_id`, `originId`, and type-specific
identifier do not match this mapping.

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

For the v0 claim lifecycle, `status` is either `open` or `claimed`. An `open`
TaskPacket has an empty `claims` array. A `claimed` TaskPacket has exactly one
claim entry, containing exactly `claimId`, `principalId`, `taskRef`, and
`claimedAt`. `claimId` is a hub-minted, origin-unique ULID-bearing identifier;
`principalId` is the stable principal resolved from the authenticated key;
`taskRef` is the exact `(record_id, revision_digest)` pair of the open revision
that was claimed; and `claimedAt` is an RFC 3339 timestamp assigned by the hub.
Unknown claim fields fail strict validation.

A claim request body contains exactly one field, `taskRef`, with exactly
`record_id` and `revision_digest`; the caller cannot submit `claimId`,
`principalId`, `claimedAt`, status, predecessor, or replacement TaskPacket
bytes. Those values are resolved or minted by the hub after authentication.

A successful claim is one atomic compare-and-append operation. The hub requires
`taskRef` to name the unique current admitted leaf, requires that leaf to be
`open` with no claims, and requires its `assignedWriter` to equal the
server-bound principal. In the same durable transaction, the hub appends one
successor TaskPacket whose `predecessor` and claim-entry `taskRef` both equal
the requested pair, whose prior fields are unchanged except for
`status: "claimed"` and the one appended claim, and whose resulting exact pair
becomes the unique admitted leaf. Only the claims route may admit that
`open`-to-`claimed` transition; ordinary sync rejects a client-authored claim
transition. The hub returns 201 only after the successor is durable. A
concurrent request that lost the compare appends nothing and returns 409. A
retry by the same principal for the same exact `taskRef` returns the already
admitted successor without appending another revision; any other stale,
already-claimed, or conflicting request returns 409. Thus claim exclusivity is
recoverable from canonical TaskPacket history after restart or sync rather
than existing only in a transient lock or audit entry.

Every TaskPacket and WorkReceipt carries `accessLabelRef`, an exact object with
`record_id` and `revision_digest` for the AccessLabel revision governing its
project disclosure. For ordinary intake, the hub requires this reference to
equal the label revision bound server-side to the authenticated key. A client
cannot select another accepted label merely by naming it. Assigning a different
label requires a separate authenticated administrative operation outside the
three coordination routes. The reference identifies policy; it does not grant
authority by itself.

All three bodies may contain an optional `extensions` object conforming to
`docs/contracts/v0-extensions.md`. AM-6 uses the optional
`https://artifact-memory.dev/extensions/coordination-freshness/v1` declaration
with `version: "v1"`, `required: false`, and an object value containing exactly
`trueAsOfCommit`, a lowercase 40- or 64-hex Git object ID. Readers that support
the extension evaluate freshness; other readers preserve it opaquely. Unknown
required extensions fail closed. Adding `trueAsOfCommit` as a new top-level
field under the v0 schema is forbidden.

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
  "record_id": "record://coordination/33333333-3333-4333-8333-333333333333/task/task_01J00000000000000000000000",
  "originId": "33333333-3333-4333-8333-333333333333",
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
    "record_id": "record://coordination/33333333-3333-4333-8333-333333333333/label/label-scoped-client",
    "revision_digest": "sha-256:164b6b386cdedf382529cc57cf7c929446a1f360b164c13d1243849231f4596a"
  },
  "assignedWriter": "agent-session-synthetic-1",
  "claims": [],
  "status": "open",
  "parentEpic": "epic-synthetic-parity",
  "predecessor": null,
  "extensions": {
    "https://artifact-memory.dev/extensions/coordination-freshness/v1": {
      "version": "v1",
      "required": false,
      "value": { "trueAsOfCommit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }
    }
  },
  "authority_boundary": "informational only; authority requires independently authenticated WITS enforcement"
}
```

The claim entry in the hub-created successor has this strict shape; its
`taskRef` and the successor's `predecessor` both name the open revision above:

```json
{
  "claimId": "claim_01J00000000000000000000002",
  "principalId": "agent-session-synthetic-1",
  "taskRef": {
    "record_id": "record://coordination/33333333-3333-4333-8333-333333333333/task/task_01J00000000000000000000000",
    "revision_digest": "sha-256:93be6b6e63c11906c955f835da6e7f547c1672e1b173cf59126ac03f43f41022"
  },
  "claimedAt": "2026-09-25T19:05:00Z"
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

`taskRef` is required and binds the receipt to one exact admitted TaskPacket
revision. Validators resolve that pair, require its `record_id` to encode the
same task identity, and verify matching project, effective AccessLabel, and
assigned writer. Evidence against a superseded revision remains historical
evidence for that revision; it cannot complete a newer or forked revision.

```json
{
  "schema_id": "artifact-memory/coordination-work-receipt/v0",
  "record_id": "record://coordination/33333333-3333-4333-8333-333333333333/receipt/rcpt-01J00000000000000000000001",
  "originId": "33333333-3333-4333-8333-333333333333",
  "receiptId": "rcpt-01J00000000000000000000001",
  "taskRef": {
    "record_id": "record://coordination/33333333-3333-4333-8333-333333333333/task/task_01J00000000000000000000000",
    "revision_digest": "sha-256:93be6b6e63c11906c955f835da6e7f547c1672e1b173cf59126ac03f43f41022"
  },
  "writer": "agent-session-synthetic-1",
  "machine": "synthetic-client-a",
  "projectId": "11111111-1111-4111-8111-111111111111",
  "projectName": "sample-service",
  "headSha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "accessLabelRef": {
    "record_id": "record://coordination/33333333-3333-4333-8333-333333333333/label/label-scoped-client",
    "revision_digest": "sha-256:164b6b386cdedf382529cc57cf7c929446a1f360b164c13d1243849231f4596a"
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
          "location": {
            "endpoint_ref": "endpoint://synthetic/review-store",
            "relative_path": "reviews/42.json"
          },
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
  "record_id": "record://coordination/33333333-3333-4333-8333-333333333333/label/label-scoped-client",
  "originId": "33333333-3333-4333-8333-333333333333",
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
    "readProjects": ["11111111-1111-4111-8111-111111111111"],
    "syncTaskPackets": ["11111111-1111-4111-8111-111111111111"],
    "syncWorkReceipts": ["11111111-1111-4111-8111-111111111111"]
  },
  "mayNot": {
    "readProjects": ["22222222-2222-4222-8222-222222222222"]
  },
  "notes": "Synthetic scoped client may access one project and cannot read the other.",
  "authority_boundary": "informational only; authority requires independently authenticated WITS enforcement"
}
```

Within one AccessLabel revision, `may.readProjects` and
`mayNot.readProjects` are sets and MUST be disjoint. A duplicate UUID within
either array or a UUID present in both arrays makes the label invalid; it is
rejected before binding or use, with a typed validation error. There is no
grant-versus-denial precedence rule for an invalid label. If a bound label is
later found to violate this invariant, sync and context export fail closed
rather than choosing either interpretation.

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

In particular, `dod.acceptanceCommand` is issuer-unverified record data. A
kickoff pack renders it only inside a clearly labeled, escaped untrusted-data
block and includes an explicit `do not execute` instruction. It must never
splice command text into an instruction, shell, tool call, or executable code
block. Running it requires separate authenticated execution authority and any
operator confirmation required by that authority contract. Shell metacharacters,
newlines, substitutions, and prompt-like prose remain inert quoted data.

## WITS bridge boundary

WITS gains exactly two mutation routes plus one authenticated sync route; it
stores no second copy of coordination truth outside the vault:

- `POST /api/agent/coordination/receipts` — validated append to the vault
  (schema + digest + writer check), then fan-out notification on the bus.
- `POST /api/agent/coordination/claims` — hub-authoritative claim with
  exclusivity check, single-writer queue enforcement.
- `POST /api/agent/coordination/sync` — authenticated union exchange. The
  hub intersects the key's project-scoped capability with its server-bound
  AccessLabel. Egress requires `coordination:read:<project>`. Intake requires
  `coordination:sync:task-packet:<project>` or
  `coordination:sync:work-receipt:<project>` for the submitted type. Ordinary
  sync never admits AccessLabel bodies; label administration is separate. The
  response includes the canonical sync receipt, authorized membership
  manifest, and count-only exclusion receipt. Restricted responses never
  include full AccessLabel bodies or denied identities.
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
than trusting them and requires each submitted `accessLabelRef` to equal the
effective server-bound label. Possessing another valid label reference grants
nothing. Principal and label administration remain separate owner/admin
operations and are not coordination intake routes.

The sync route enforces the V0 resource bounds before expensive validation,
applies all-or-nothing request rejection for a limit violation, and paginates
bounded responses. Capability, label, principal, resource, and schema checks
are independent fail-closed gates; passing one never substitutes for another.

## Non-goals (v0)

- No consensus, no leader election, no peer-to-peer sync.
- No WITS-side duplicate of record storage.
- No policy inside the bridge: ceilings, quorums, and scope fences stay in
  lane configs and task packets. Machinery must not outrun judgment.
