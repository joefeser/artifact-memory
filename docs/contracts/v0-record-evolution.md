# v0 portable candidate admission and record evolution

Issue #66 introduced `knowledge-candidate/v1` and
`candidate-admission-receipt/v1`. Issue #83 adds the negotiated
`knowledge-candidate/v2` and `candidate-admission-receipt/v2` repair. A
candidate is a digest-bound draft proposal, not canonical current knowledge and
not authority.

Candidate v2 records its exact source record revisions, agent or adapter
provenance, sensitivity, required owner review, and an explicit
`candidate_scope`. Scope has a producer-selected portable namespace and a
sorted, unique set of bounded input references. Bounded inputs describe what
the producer considered; `source_record_refs` separately bind canonical record
revisions used by evolution relationships. Provenance and scope references use
the portable logical `scheme://segment[/segment]` reference form. V2 fails
closed to the registered logical schemes `actor`, `adapter`, `artifact`,
`artifact-version`, `authority`, `candidate`, `content`, `decision`,
`external-evidence-binding`, `fixture`, `record`, `record-revision`, `release`,
`task`, `tombstone`, and `transformation`. Location, transport, provider,
authority/userinfo, query, fragment, and bearer URL forms are forbidden. A new
logical scheme requires a later contract revision; producers cannot improvise
one. References are provenance claims, not authenticated grants. Source record
references must also have unique logical record identities; two revisions of
the same source cannot make candidate identity or admission order-dependent.

Candidate v2 can carry first-class `uncertainty` without asserting a
`knowledge-record/v3.derivative`. Existing derivative uncertainty remains
unchanged. Admission records one caller-supplied decision as `accepted`,
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

For a v2 accepted `supersedes` relationship, admission also requires the exact
current predecessor record. The result contains a new immutable predecessor
revision whose lifecycle is `superseded`; the caller persists it according to
local policy. Receipt v2 binds the old digest, old lifecycle, superseded
revision digest, and accepted replacement revision. Admission never mutates the
input predecessor. `disputes` and `contradicts` preserve exact relationships but
do not imply a predecessor lifecycle transition.

Knowledge-record v2 remains unchanged for existing consumers. Producers must
negotiate v3 before emitting the new relationship values; there is no silent
remapping because that would discard evolution meaning.

The admission receipt binds the candidate identity and candidate revision to
the exact source references, external decision reference, and resulting record
revision. It grants no execution, routing, disclosure, mutation, merge,
deployment, spending, credential, declassification, or approval authority.

## Compatibility and negotiation

Candidate and receipt v1 are frozen. Their strict schemas, canonical bodies,
candidate IDs, revision digests, receipt IDs, return shape, and released v0.1.0
accepted fixture remain valid and replayable. The v1 namespace algorithm is
retained only for v1 replay.

Explicit scope and uncertainty require candidate v2 because v1 rejects unknown
properties and a required scope field would re-key every existing candidate.
For v2, namespace, sorted scope, validated provenance, and optional uncertainty
are part of the canonical body, so changing any populated value intentionally
changes both `candidate_id` and `candidate_revision_digest`. V2 namespace is
read directly from `candidate_scope.namespace`; provenance ordering cannot
change it. Builders emit v1 when no v2 fields are requested and v2 only when
both namespace and bounded inputs are supplied.

Consumers must support the candidate version they validate and must separately
negotiate the embedded result-record schema. Unknown candidate contracts fail
closed because their identity rules are unknown. A known candidate whose result
schema was not negotiated continues to receive the typed `unsupported` outcome;
there is no silent schema downgrade.

Admission receipt validation is semantic as well as structural. A reader
recomputes the digest-derived receipt ID, checks the candidate ID/digest pair,
enforces canonical source ordering, and verifies that predecessor transitions
bind unique declared source revisions to the receipted result revision. A
shape-valid receipt with a retained ID and altered transition is rejected.
Receipt-only validation proves internal integrity, not authenticity or the
truth of a predecessor lifecycle claim. Verifying the superseded revision body
still requires the corresponding canonical record evidence.

The checked v2 synthetic fixtures replay accepted supersession, rejection,
dispute, independent uncertainty, immutable predecessor transition, and direct
lifecycle-aware context suppression. The v1 accepted fixture is replayed
unchanged as the compatibility proof.

The lifecycle repair also exposed a released Codex-history v1 fixture that had
presented draft derivatives as context. That v1 schema and fixture remain
byte-for-byte frozen. The corrected zero-record proof uses
`codex-history-conformance-receipt/v2` and the v2 fixture directory, so an old v1
reader is never sent a newly incompatible v1 payload.

This v0 slice does not capture raw transcripts or model reasoning, infer trust
from ranking, resolve conflicts, perform bulk capture, or provide semantic
retrieval.
