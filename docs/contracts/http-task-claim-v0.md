# Authenticated HTTP task pickup v0

This client contract extends v0 coordination transport. It grants no execution,
spending, tool, approval, deployment or disclosure authority. TaskPacket and
WorkReceipt schemas and the existing authorized projection remain unchanged.

`artifact-memory claim` requires one explicit exact open TaskPacket reference,
project UUID, logical hub ID, authenticated principal ID, exact AccessLabel
reference and HTTP hub URL. The bearer comes from an environment variable or
an in-memory library argument, never an argument or durable receipt. Remote
hubs require HTTPS. Redirects and environment proxy forwarding are disabled.

Before claiming, the client completes a bounded authenticated pull through the
existing HTTP sync adapter. It verifies the current authorized projection and
requires the task's project, assigned writer and AccessLabel to match the
configured bindings. Only an exact current open leaf or the exact original
open reference of an already claimed leaf for that principal may proceed.
The latter still requires the hub to confirm replay; local history grants no
claim authority.

The claim request is only `POST /api/agent/coordination/claims` with
`{"taskRef": <exact open reference>}`. The hub requires the exact project claim
capability, credential-bound label claim grant and server-owned origin/project
policy before identity lookup. It alone mints and admits the claimed successor.
A new claim returns 201 with `replay: false`; exact authenticated replay returns
200 with `replay: true`. A 409 is a typed conflict. The client never chooses
another task, changes the requested revision, or resolves a conflict itself.

Success requires a second complete verified pull. The returned reference must
be the current claimed leaf in its authorized projection, whose predecessor
and sole claim's taskRef match the original exact request, whose principal,
project and AccessLabel still match, and whose body digest matches its reference.
The command reports only those references, claim ID, pinned bindings, replay
flag and verifying sync receipt ID. It never persists a separate claim database
or local successor manufactured from a claim response.

A lost response, invalid response or failed reconciliation is an unverified
outcome, never successful pickup. The hub may already have admitted the claim.
Retry requires a new explicit command for the same original exact reference;
there is no automatic claim retry, fallback task, local release or reassignment.
Post-claim reconciliation uses the existing sync pending-outcome protocol and
projection lock. Local command locks are transport exclusion only.

An operator must separately provision keys, compatible publisher/worker label
bindings, server origin ownership, HTTPS and worker runtime. HTTP project
onboarding and automatic runner launch are separate contracts. This command
does not execute `dod.acceptanceCommand` or launch an agent.

## Security and compatibility impact

The command sends a bearer only to the configured validated hub, bypasses
environment proxies and rejects redirects. It adds no execution authority,
local claim truth, automatic claim retries or credential persistence. A task
already observed as claimed requires an explicit hub replay response; a 201
response cannot be reported as verified new admission for that history.

The CLI addition is opt-in. Existing TaskPacket, WorkReceipt, AccessLabel and
sync schemas, byte limits and existing sync proof source pin are unchanged.
Root, sync-endpoint and claim-endpoint hub URLs normalize to their separate
pull and claim endpoints. The shared synthetic hub proof runs against both
independently pinned WITS revisions.
