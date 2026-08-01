# v0 Artifact Memory ↔ WITS adapter boundary

The v2 adapter accepts exact Artifact Memory record revisions, sensitivity and
disclosure constraints, freshness, and optional TraceMap evidence references.
It emits an opaque WITS projection reference and a deterministic admission
receipt. WITS owns owner meaning, decisions, readiness, task preparation,
routing, authority, and reconciliation; Artifact Memory neither recreates nor
interprets those schemas.

The initial provider anchor is WITS commit
`d675ba6d632dc03826f27940014d4cd672f7d910` in
`joefeser/what-is-the-spec`. The referenced WITS contracts are its memory-card
schema, fresh-context template, HACP Task Packet RFC, and Route Task schema.
WITS is BSL 1.1 with a 2030-01-01 change date to Apache-2.0. Artifact Memory
records only repository, exact commit, contract paths, and license provenance;
it copies no WITS implementation or product-owned schema text.

## Admission truth

The adapter reports admitted, rejected, unsupported, stale, superseded,
mixed-revision-context, conflict, sensitivity-mapping-unavailable, disclosure-denied,
evidence-reference-unavailable, and authority-bearing-request-rejected
outcomes. Provider responses are bound to the deterministic request digest.
Nested Task Packet, Route Task, continuation, destination, approval, or
execution fields fail closed.

The synthetic conformance fixture starts with the pinned `SyntheticOrders`
TraceMap proof and ends after informational context recall, generated-index
rebuild, encrypted backup, and isolated restore. Its final stage is
`stop-before-hacp-task-creation`; it creates no HACP Task Packet, Route Task,
destination, continuation payload, authority grant, or execution request.

The opaque synthetic WITS response proves only Artifact Memory's side of the
process boundary. It is not a live WITS interoperability claim and does not
prove authority-safe coordinated use. That stronger claim requires a
separately authenticated WITS process and WITS-owned conformance evidence.
