# HTTP task pickup

Pickup retrieves and claims coordination evidence. It does not launch an agent,
run the packet's acceptance command, or grant execution or spending authority.
The normative behavior is [HTTP task claim v0](../contracts/http-task-claim-v0.md).

## Provision first

An owner must configure an HTTPS WITS hub, project-specific bearer capabilities,
stable principal IDs, compatible exact publisher/worker AccessLabel bindings,
and server-owned origin/project policy. The worker must be the packet's
`assignedWriter`; pickup is not an unrestricted idle-worker queue. The worker
needs `coordination:read:<project>` and `coordination:claim:<project>`. Receipt
sync additionally needs `coordination:sync:work-receipt:<project>` and the label's
corresponding grants. Publisher task sync needs its task sync capability.

Keys are supplied through an environment variable. Provision them out of band;
never put a bearer in shell arguments, task records, logs, or receipts. A
Tailscale connection alone does not replace HTTPS or these bindings. Current
HTTP project onboarding is still unsupported; this command does not create an
onboarding link or infer an approval from projected records.

## Claim one explicit open reference

Use owner-provisioned values for the hub URL, logical hub identity, project,
principal, AccessLabel reference and one original open TaskPacket reference.
Both reference files contain only `record_id` and `revision_digest`.

```sh
artifact-memory claim --vault ./worker-vault --hub "$HUB_URL" \
  --hub-id "$HUB_ID" --project-id "$PROJECT_ID" --principal-id "$PRINCIPAL_ID" \
  --access-label-ref "$(cat access-label-ref.json)" \
  --task-ref "$(cat exact-open-task-ref.json)" \
  --bearer-env ARTIFACT_MEMORY_COORDINATION_BEARER --json
```

The command pulls verified authorized history, submits only the exact task
reference, then pulls again to verify the hub-minted claimed successor. It
returns a ref-only receipt with `outcome: verified`, a claim ID, replay flag and
verifying sync receipt ID. The result's no-authority boundary still applies.

A 409 stops as `claim-conflict`; it never selects a different task. If a response
or verification fails, the hub may already have admitted the claim. A later
explicit retry must use the same original open reference, which lets the hub
confirm replay. Do not create a new successor locally, change the reference,
or interpret a timeout as an unclaimed task.

Work receipts remain local append first, then sync through the existing HTTP
adapter. A separate read-only observer can pull the authorized task history and
receipt. No complete AccessLabel or withheld record identity is returned.

## Synthetic proof

With installed WITS dependencies and Docker, set `WITS_SOURCE_ROOT` to a clean
checkout at the exact source pin in `scripts/run_wits_claim_integration.py`:

```sh
python3 scripts/run_wits_claim_integration.py
```

The driver creates and removes only its owned disposable synthetic database.
The proof publishes one task through the real authenticated route, claims it
with the CLI, verifies exact replay and another-principal conflict, appends and
syncs measured harness evidence, and lets an observer retrieve three authorized
revisions with one count-only exclusion. Next's actual post-response context
runs the in-process notification sink. This is a single-machine protocol
fixture; it is not deployed two-host or automatic Codex execution evidence.
