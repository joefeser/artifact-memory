# v0 bounded knowledge exchange

The v2 exchange envelope carries an identity-bound bundle manifest containing
record revision digests and artifact references, plus an audience, correlation
ID, expiry, handling policy, and explicit no-authority boundary. The envelope
may include exact canonical records, but artifact bytes are references only and
retrieval remains a separate local authorization.

Admission is receiver-owned and produces one of six typed outcomes:
`admitted`, `rejected`, `quarantined`, `duplicate`, `unsupported`, or
`partially-resolved`. A caller-owned ledger records valid processed envelope
identities. Repeated replay returns the same deterministic `duplicate` receipt.
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
boundary rejects credential-shaped keys and bearer-token-shaped values without
echoing them into receipts. Receipts contain only stable diagnostics, admitted
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
produces machine- and human-readable receipts. It does not establish
cross-party authenticity or #23 independent implementation interoperability.
