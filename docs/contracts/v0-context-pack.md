# v0 informational context pack

The completed #20 base contract is `artifact-memory/context-pack/v2`. The
earlier v1 schema remains available as a legacy read contract. Strict v2 and v3
schemas remain unchanged. The reference exporter emits v2 for ordinary packs,
v3 when revocation suppression evidence is present, and negotiated v4 when a
lifecycle exclusion must be receipted. The independent reader accepts v2, v3,
and v4.

Context packs are bounded selections of canonical Artifact Memory knowledge for
an independent reader. They carry source record revisions, artifact references,
sensitivity and redaction outcomes, generic external-evidence metadata, and
freshness information. Protected bytes remain references.

The API names `authorized_record_ids` and `authorized_evidence` are retained for
compatibility, but both are unauthenticated caller-supplied selection inputs.
Artifact Memory verifies neither an owner nor an authorization grant from those
values. In legacy v2/v3 receipts, `not-authorized` means only "not present in the
caller-supplied selection." It must not be interpreted as an authenticated
access-control decision. V4 names the counter `not-caller-selected` and records
`selection_input_trust: caller-supplied/not-authenticated` explicitly.

Records are sorted by logical identity and revision digest. `export_context`
directly enforces lifecycle eligibility; correctness does not depend on a
caller first using `current_records()`. Only `accepted` or `sealed` records can
be selected. Draft, superseded, and rejected revisions are excluded before
freshness is evaluated, even when their logical identities were caller-selected
and freshness was asserted current. V4 reports this as an aggregate `lifecycle`
count separate from freshness without disclosing excluded identities. More than
one lifecycle-eligible revision for the same logical record fails closed.

Only lifecycle-eligible records with an operator-asserted `current` freshness
status at the declared selection time may be selected. Sensitivity, freshness,
lifecycle, and revocation failures exclude the whole record; the portable
selection receipt reports only counts. Artifact bytes and provider-internal
rows are never embedded.

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

A valid acknowledgement bound to an exact supplied revision that is already
lifecycle-ineligible is checked but does not participate in revocation
selection or appear in the pack's revocation receipt references. Lifecycle is
the exclusion reason and its aggregate counter remains separate. Malformed,
unapplied, or revision-mismatched acknowledgements still fail context export
with a typed context error.

## Version negotiation

The exporter defaults to the frozen v2/v3 capability set, preserving existing
pack identities and strict-reader behavior when every input record is lifecycle
eligible. A lifecycle exclusion cannot be represented honestly in their closed
selection-receipt schemas, so export fails with `context-schema-unnegotiated`
unless the caller advertises `artifact-memory/context-pack/v4`. It never folds a
lifecycle exclusion into freshness or the legacy `not-authorized` counter.

V4 always includes lifecycle, freshness, sensitivity, revocation, and
`not-caller-selected` counters. It supports optional validated revocation
receipt bindings. If only v4 is negotiated, ordinary and revocation-aware packs
may also use v4. No v2 or v3 field was added, renamed, or relaxed.

The CLI preserves its v2/v3 default and exposes repeatable
`--support-context-schema` negotiation. A lifecycle-aware command invocation
must include `--support-context-schema artifact-memory/context-pack/v4`; it is
never selected silently for an old caller.

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

Human selection-receipt rendering first runs the same independent semantic pack
validation used by recall. A schema-valid pack with a mismatched pack identity,
record selection, evidence binding, ordering, or byte bound is not rendered.
