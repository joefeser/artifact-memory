# v0 portable candidate admission and record evolution

Issue #66 adds `knowledge-candidate/v1` and
`candidate-admission-receipt/v1`. A candidate is a digest-bound draft proposal,
not canonical current knowledge and not authority.

The candidate records its exact source record revisions, agent or adapter
provenance, sensitivity, uncertainty through the draft record, and required
owner review. Admission records one caller-supplied decision as `accepted`,
`rejected`, `quarantined`, `duplicate`, `stale`, `unsupported`, or `conflict`.
An accepted candidate produces a new `knowledge-record/v3` revision; it never
overwrites the candidate or a predecessor.

Acceptance requires explicit consumer negotiation of the candidate record
schema. An unnegotiated v3 result is receipted as `unsupported`; it is not
silently converted to v2 because that would discard evolution semantics.

Knowledge-record v3 permits explicit `supersedes`, `disputes`, and
`contradicts` relationships. Each relationship carries both the canonical
record target and its exact SHA-256 revision digest, and that pair must match
one of the exact source revisions considered by the candidate. Artifact Memory
stores the relationship and revision binding; WITS owns meaning, owner
approval, readiness, reconciliation, and conflict resolution.

Knowledge-record v2 remains unchanged for existing consumers. Producers must
negotiate v3 before emitting the new relationship values; there is no silent
remapping because that would discard evolution meaning.

The admission receipt binds the candidate identity and candidate revision to
the exact source references, external decision reference, and resulting record
revision. It grants no execution, routing, disclosure, mutation, merge,
deployment, spending, credential, declassification, or approval authority.

This v0 slice does not capture raw transcripts or model reasoning, infer trust
from ranking, resolve conflicts, perform bulk capture, or provide semantic
retrieval.
