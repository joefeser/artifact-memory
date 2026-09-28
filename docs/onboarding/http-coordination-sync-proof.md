# Synthetic HTTP coordination sync proof

Issue: joefeser/artifact-memory#153. WITS source is pinned to merged `dev`
commit `d07f850d07a447e7672ae40a0e61b67029e71d02` (PR #1453).

The opt-in test starts a loopback HTTP wrapper around the real WITS POST route,
with its actual AgentApiKey bearer authentication, exact capabilities and
server-bound label resolution. It does not replace the route's authorization or
vault implementation. The hub, clients, records, key material and database are
synthetic and disposable. Existing local servers are not used or stopped.

## Prerequisites

- Python 3.11 or newer, Node, Docker and a dedicated clean checkout of the
  pinned WITS ref with its dependencies installed. Prisma generation writes
  ignored files in that checkout, so use an isolated test checkout.
- Set `WITS_SOURCE_ROOT` outside command history to that checkout. Its
  machine-local value does not belong in commits or proof output.

Run from this repository:

```sh
python3 scripts/run_wits_http_integration.py
```

The runner creates a uniquely named synthetic pgvector container, discovers its
loopback port, provisions the pinned Prisma schema and generated client, runs
the route proof, and removes only the container it created, including on test
failure. It never consumes an existing database URL or resets an existing DB.
The test checks pinned WITS HEAD and tracked source, creates/removes its own
synthetic project/key rows, and stops its ephemeral HTTP wrapper. The default
unit suite skips this cross-repository integration.

## Receipt

```text
Ran 1 test
OK
AM153-WITS: admitted=2(task+receipt) rejected=1 quarantined=1 pages=2 excluded=1 retry=verified no-op=verified denials=8(count-invariant)
AM153 fixture: provisioned=verified cleanup=verified
```

This proves HTTP record admission, exact per-submission outcomes, opaque
continuation assembly, a verified complete authorized projection, denied
identity/label exclusion, interrupted apply recovery and unchanged pull no-op.
Four unknown/foreign-origin probes and four write-only task/receipt probes
assert exact `unauthorized-project` outcomes for known and absent identities,
and unchanged exclusion counts. The write-only fixture has a bearer read
capability to reach the route but an AccessLabel denying project reads; its
write grants cannot bypass that label.
Quarantine is tested on a separate corrupt synthetic client with push-only
transport; the adapter does not repair or overwrite that local collision.
The test is a single machine route integration; it does not claim deployment,
cross-platform mounts, live credentials, broker delivery, or multi-writer
convergence. The existing AM-3 local-path conformance remains a separate gate.
