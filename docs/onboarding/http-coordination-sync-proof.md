# Synthetic HTTP coordination sync proof

Issue: joefeser/artifact-memory#153. WITS source is pinned to merged `dev`
commit `d07f850d07a447e7672ae40a0e61b67029e71d02` (PR #1453).

The opt-in test starts a loopback HTTP wrapper around the real WITS POST route,
with its actual AgentApiKey bearer authentication, exact capabilities and
server-bound label resolution. It does not replace the route's authorization or
vault implementation. The hub, clients, records, key material and database are
synthetic and disposable. Existing local servers are not used or stopped.

## Prerequisites

- Python 3.11 or newer, Node and the pinned WITS checkout with installed
  dependencies and generated Prisma client.
- A dedicated disposable PostgreSQL database with pgvector, provisioned using
  the pinned WITS Prisma schema. Do not point the test at an existing database.
- `WITS_SOURCE_ROOT` names that clean checkout; `TEST_DATABASE_URL` names only
  the disposable database. Neither value belongs in commits or proof output.

Run Prisma's `db push` and `generate` in that checkout with `DATABASE_URL` set
to the disposable database. No reset/data-loss flags are needed for a fresh DB.
Then run from this repository:

```sh
RUN_WITS_HTTP_INTEGRATION=1 AM153_DISPOSABLE_DATABASE=synthetic \
  python3 -m unittest tests.test_coordination_http_wits -v
```

The test checks the pinned WITS HEAD and tracked source diff. It provisions and
removes only its own synthetic project/key rows, uses an ephemeral loopback
port, and stops its wrapper after the test. Provision the required environment
variables outside command history. The default suite skips this integration.

## Receipt

```text
Ran 1 test
OK
AM153-WITS: admitted=2(task+receipt) rejected=1 quarantined=1 pages=2 excluded=1 retry=verified no-op=verified
```

This proves HTTP record admission, exact per-submission outcomes, opaque
continuation assembly, a verified complete authorized projection, denied
identity/label exclusion, interrupted apply recovery and unchanged pull no-op.
Quarantine is tested on a separate corrupt synthetic client with push-only
transport; the adapter does not repair or overwrite that local collision.
The test is a single machine route integration; it does not claim deployment,
cross-platform mounts, live credentials, broker delivery, or multi-writer
convergence. The existing AM-3 local-path conformance remains a separate gate.
