# v0 informational context pack

The completed #20 base contract is `artifact-memory/context-pack/v2`. The
earlier v1 schema remains available as a legacy read contract, and v2 remains
unchanged for strict consumers. The reference exporter emits v2 for ordinary
packs and v3 when revocation suppression evidence is present; the independent
reader accepts both.

Context packs are bounded selections of canonical Artifact Memory knowledge for
an independent reader. They carry source record revisions, artifact references,
sensitivity and redaction outcomes, generic external-evidence metadata, and
freshness information. Protected bytes remain references.

The exporter requires an explicit set of authorized record identities and an
explicit set of authorized provider-record identities. Records are sorted by
identity. Only records with an operator-asserted `current` freshness status at
the declared selection time may be selected. Sensitivity and freshness failures
exclude the whole record; the portable selection receipt reports exclusion
counts and does not disclose withheld record identities. Artifact bytes and
provider-internal rows are never embedded.

An authorized provider record is selected by the pair of provider identity and
opaque provider record identity. It must also name a generic evidence binding
referenced by a selected canonical record. Provider identities are not assumed
to make opaque record identities globally unique, and provider provenance does
not establish authenticity.

The selection receipt binds the exact canonical source-record set, selected
record revisions, generic provider references, selection policy, byte bound,
freshness assertion, redaction behavior, and reference-only artifact policy.
Freshness is a disclosed assertion, not inferred truth. The same inputs and
selection metadata produce the same pack identity and ordering.

When a caller supplies validated tombstone suppression, the v3 selection uses
the `validated-tombstone-suppression` policy, requires canonical revocation
receipt references, and records a revocation exclusion count. The pack
contains no suppressed record. This remains
endpoint- and pack-generation-scoped; it does not revoke an already-issued
immutable pack or prove deletion from an unknown copy.

The pack is not a WITS memory card, WITS fresh-context packet, HACP Task
Packet, Route Task, Codex continuation payload, or authority-bearing envelope.
It cannot authorize execution, routing, disclosure, repository mutation,
merge, deployment, spending, credentials, or declassification. A later WITS
adapter may create its own projection only through separately owned contracts;
it must not copy WITS schema text into Artifact Memory.

The synthetic conformance fixture passes a serialized pack to a materially
separate stdlib-only reader. Its recall receipt contains only selected
summaries and references and states that artifact retrieval was not attempted
and execution, mutation, and disclosure authority are absent. The fixture ends
at informational recall; it does not create a HACP task or invoke a provider.
