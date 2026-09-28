# 0035: Sync through the WITS HTTP validation bridge

## Decision

AM-3 accepts a local hub path or a WITS URL. The HTTP adapter uses Python's
standard-library TLS transport, refuses redirects and URL credentials, and
accepts cleartext HTTP only on localhost/literal loopback fixtures. Credential
material comes from an environment variable or an in-memory API argument.
Expected logical hub, principal and exact AccessLabel references are mandatory.
No bearer, URL or continuation token is persisted.

The adapter assembles bounded sequential pages from one unchanged receipt,
verifies the complete authorized record and pair set, then calls the existing
local projection writer. It does not create a new coordination store. A local
OS lock protects a ref-only pending request journal. Interrupted exchanges
replay the same batch through current hub authorization; a successful pull
consumes the journal. A push-only operation retains it for the following pull.
The server owns completion time and admission outcomes.

WITS requires administrative origin/project ownership and read permission for
identity-sensitive task and receipt admission. The coordination contract now
states those requirements. Claims remain hub-authoritative, and bus messages
remain notifications.

## Compatibility and limits

The local-path adapter and deterministic local test tokens remain unchanged.
HTTP uses opaque transport tokens and verifies their sequential receipt binding.
HTTP repo onboarding is rejected typed; its local filesystem transaction is not
silently reinterpreted as a network operation. A deployment must separately
provision bearer binding, retained labels, origin policy and server token secret.

One exchange is bounded to 120 seconds, 100 pages and 400 MiB total responses and the existing
v0 per-request/page limits. Environment proxy settings are not used; deployment
URLs must be directly reachable. The aggregate wire limit includes repeated
receipts, tokens and references, independently of WITS's 128 MiB vault scan.
With 10,000 records, a 1 MiB metadata reserve and 1 MiB maximum record,
WITS's greedy packing produces fewer than 68 byte-full pages, at most 20
500-record pages and one tail. The 100-page cap covers that bound with slack;
the entire HTTP envelope still must fit WITS's 4 MiB per-response limit. A bearer rotation is supplied out of band.

## CLI

```sh
# Set ARTIFACT_MEMORY_COORDINATION_BEARER outside command history.
python3 -m artifact_memory sync --vault ./synthetic-vault \
  --hub https://example.invalid/api/agent/coordination/sync \
  --hub-id coordination-hub://synthetic/hub-a \
  --principal-id coordination-principal://synthetic/agent-1 \
  --access-label-ref '{"record_id":"record://coordination/33333333-3333-4333-8333-333333333333/label/label-scoped-client","revision_digest":"sha-256:0000000000000000000000000000000000000000000000000000000000000000"}' \
  --phase both --json
```

The example uses a reserved domain and synthetic identities. The reference must
be replaced with the exact server-owned binding; record text cannot grant it.
