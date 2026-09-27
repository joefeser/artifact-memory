# 0034: Export coordination context only from an authorized projection

Status: accepted for AM-7

## Context

Canonical coordination storage intentionally retains immutable record
revisions. That property cannot answer whether a record remains visible under
the latest AccessLabel. A context exporter that reads canonical storage
directly, trusts caller-selected records, or treats local presence as admission
could disclose a record after its project scope was denied.

The sync protocol already creates a full replacement authorized-membership
manifest and receipt for each scope generation. It also reports excluded
records as a count so clients can detect hidden state without learning denied
identities.

## Decision

`artifact-memory coordination-context` exports only the exact records named by
the latest verified authorized projection. Before export, the runtime verifies
the successful-sync marker, authenticated sync receipt, scope generation,
AccessLabel reference, authorized pair-set count and digest, and each local
record revision. Missing or inconsistent policy evidence fails closed.

The result uses the new strict
`artifact-memory/coordination-context-pack/v0` contract. It binds the pack to
the sync receipt and pair-set digest, carries exclusions only as a count, and
forbids full AccessLabel bodies. Pack identity covers the complete canonical
body. Generic knowledge context-pack v2-v4 contracts remain unchanged.

## Consequences

- Label narrowing replaces generated membership and context visibility without
  deleting canonical record history or claiming erasure.
- A locally present record is not sufficient evidence of current admission.
- Excluded project names, UUIDs, record identities, and bodies are not exposed
  through the restricted sync response or context pack.
- Duplicate or overlapping read scopes fail before use; malformed labels fail
  typed if they reach sync or context validation.
- The pack is informational and grants no execution, mutation, routing,
  disclosure, credential, spending, deployment, approval, or merge authority.
