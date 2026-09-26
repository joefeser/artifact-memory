# Local coordination sync proof

The v0 coordination contract defines HTTP transport through WITS. Artifact
Memory also ships a provider-free local-directory adapter so the immutable
set-union and receipt behavior can be tested without claiming WITS
interoperability.

The adapter requires three distinct roots or inputs:

- a local vault containing append-only canonical coordination revisions;
- a synthetic hub directory containing server-owned session, principal, and
  exact AccessLabel bindings; and
- an opaque session handle. The client cannot select the effective principal
  or AccessLabel carried by the receipt.

After synthetic hub configuration and local record creation through the Python
API, the explicit convergence phases are:

```sh
artifact-memory sync \
  --vault /path/to/disposable-vault \
  --hub /path/to/disposable-hub \
  --session-id coordination-session://synthetic/session-1 \
  --phase push \
  --completed-at 2026-09-25T20:00:00Z \
  --json

artifact-memory sync \
  --vault /path/to/disposable-vault \
  --hub /path/to/disposable-hub \
  --session-id coordination-session://synthetic/session-1 \
  --phase pull \
  --completed-at 2026-09-25T20:00:01Z \
  --json
```

Paths are adapter configuration, never durable identity. A pull stores the
canonical receipt and a receipt-bound generated authorized projection, then
advances the last-successful marker. Missing pages, duplicate pages, digest or
count mismatches, response-record mismatches, and receipt tampering fail typed
before the marker advances. AccessLabel rotation replaces only the generated
projection; canonical history remains append-only.

Full AccessLabel bodies and continuation tokens are never written into a
restricted replica. Exclusions are count-only. Coordination records, receipts,
and generated views are informational and grant no execution, mutation,
routing, disclosure, credential, spending, deployment, approval, or merge
authority.

Run the public synthetic proof with:

```sh
python3 scripts/run_coordination_sync_conformance.py --check
```

This local adapter does not authenticate a network connection, issue a real
credential, implement WITS routes, or establish issuer authenticity. Those
remain separate WITS integration work.
