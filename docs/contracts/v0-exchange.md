# v0 bounded knowledge exchange

The v2 exchange envelope carries an identity-bound bundle manifest containing
record revision digests and artifact references, plus an audience, correlation
ID, expiry, handling policy, and explicit no-authority boundary. The envelope
may include exact canonical records, but artifact bytes are references only and
retrieval remains a separate local authorization.

Admission is receiver-owned and produces one of six typed outcomes:
`admitted`, `rejected`, `quarantined`, `duplicate`, `unsupported`, or
`partially-resolved`. The receiver must inject a durable ledger whose `claim`
operation atomically inserts an envelope identity only when it has not already
been processed. Admission without that dependency, or with a failed/malformed
claim result, is quarantined as `replay-ledger-unavailable`; the reference
runtime never silently substitutes process-local memory. Repeated replay through
the shared ledger returns the same deterministic `duplicate` receipt.
An envelope with some resolvable and some unresolved record revisions returns
`partially-resolved`; contradictory declarations or bytes are quarantined.
Expired or malformed envelopes are rejected, and unsupported schemas remain
explicit.

The receiver must supply its expected audience out of band; a mismatch is
rejected before record admission. Bundled records may not exceed the envelope's
handling sensitivity. A v1 record with no explicit sensitivity fails closed as
`restricted`. Locally available revisions count as resolved only when the
receiver supplies matching sensitivity metadata that is permitted by the
envelope handling policy.

Bearer credentials are prohibited in envelopes. The reference admission
boundary examines values without interpreting opaque extension keys and rejects
private-key headers, token-shaped bearer/header values, and recognized token
prefixes without echoing them into receipts. Receipts contain only stable diagnostics, admitted
and unresolved record IDs, artifact references, and the retrieval/authority
boundary.

The v1 envelope and receipt remain readable for compatibility. The v2 schemas
are the completed issue #22 contract because they add explicit bundle identity,
partial-resolution truth, deterministic stateful replay, and credential
containment without changing v1 semantics.

Exchange is not a WITS/HACP Task Packet, Route Task, owner grant, execution
authorization, or Codex continuation payload. A receiver may later create an
authority-bearing task through its own authenticated WITS process, but that
authority is not hidden in this envelope or receipt.

The checked fixture under `fixtures/synthetic/exchange/v2/` independently
replays all six outcomes, including contradictory and repeated input, and
produces machine- and human-readable receipts. The separate issue #23 fixture
under `fixtures/synthetic/exchange/independent-v1/` proves compatible v2
receipts across the reference receiver and a materially separate stdlib-only
receiver for the complete embedded-bundle extension seam. Neither fixture
establishes cross-party authenticity or trust.
