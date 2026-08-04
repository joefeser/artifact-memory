# v0 independent exchange conformance

Issue #23 uses the v2 reference sender and two materially separate admission
implementations. The reference receiver uses Artifact Memory's schemas,
canonicalization, validator, and exchange runtime. The independent receiver is
stdlib-only and imports none of those helpers; it parses duplicate-key-aware
JSON, recomputes envelope, bundle, record-revision, and receipt identities, and
implements the bounded complete embedded-bundle profile itself.

The checked fixture under `fixtures/synthetic/exchange/independent-v1/` sends
one synthetic canonical record and artifact reference through both receivers.
For each case, both sides emit an identical schema-valid v2 admission receipt:

- an unknown optional extension is admitted and preserved unchanged;
- an unknown required extension is quarantined with
  `required-extension-unsupported`;
- the same required extension is admitted and preserved after support is
  explicitly declared;
- repeated identical manifest declarations are deduplicated and admitted;
- a v1 record's opaque extension remains uninterpreted and is admitted.

Artifact retrieval is never attempted and remains separately authorized. The
fixture does not claim durable replay, external artifact resolution,
cross-party authenticity, provider trust, or a universal second
implementation. Compatible receipts are informational evidence only and grant
no execution, disclosure, routing, spending, credential, deployment, merge,
or mutation authority.
